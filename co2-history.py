#!/usr/bin/env python3

"""
This script downloads the stored measurement history from a SwitchBot Meter Pro CO2.

See reverse-engineer/protocol-history.md for more info.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import math
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_16

UUID_SWITCHBOT_SERVICE_DATA = normalize_uuid_16(0xFD3D)
DEVICE_TYPE_METER_PRO_CO2 = 0x35

# The device receives commands on one characteristic and answers with a
# notification on the other. Naming is from the device's point of view.
CHAR_WRITE = "cba20002-224d-11e6-9fb8-0002a5d5c51b"
CHAR_NOTIFY = "cba20003-224d-11e6-9fb8-0002a5d5c51b"

# First reply byte indicating success
STATUS_OK = frozenset({0x01, 0x06, 0x0C})

RECORDS_PER_READ = 4
RECORDS_PER_GROUP = 2
GROUP_SIZE_BYTES = 9

CSV_COLUMNS = ["ts", "temp_c", "humidity_percent", "co2_ppm"]


class ProtocolError(RuntimeError):
    pass


@dataclass(frozen=True)
class SectionInfo:
    """Metadata for one storage section: what it holds and how it is spaced."""

    section: int
    start_time: int
    end_time: int
    count: int
    interval: int

    def timestamp_of(self, index: int) -> datetime:
        """Wall-clock time of record `index`, counting back from the newest.

        Anchored on end_time rather than start_time: the app does the same,
        and the two disagree by one interval in captured syncs.
        """
        epoch = self.end_time - (self.count - 1 - index) * self.interval
        return datetime.fromtimestamp(epoch, timezone.utc).astimezone()


@dataclass(frozen=True)
class HistoryRecord:
    timestamp: datetime
    temp_celsius: float
    humidity_percent: int
    co2_ppm: int

    def format_line(self) -> str:
        return "  ".join(
            [
                self.timestamp.isoformat(timespec="seconds"),
                f"{self.temp_celsius:5.1f} C",
                f"{self.humidity_percent:3d}%",
                f"{self.co2_ppm:5d} ppm",
            ]
        )

    def as_row(self) -> dict[str, str | float | int]:
        return {
            "ts": self.timestamp.isoformat(timespec="seconds"),
            "temp_c": self.temp_celsius,
            "humidity_percent": self.humidity_percent,
            "co2_ppm": self.co2_ppm,
        }


class Requests:
    """All commands sent to device"""

    @staticmethod
    def get_store_info() -> bytes:
        """Ask which storage sections exist."""
        return bytes([0x57, 0x0F, 0x69, 0x08, 0x01])

    @staticmethod
    def get_section_info(section: int) -> bytes:
        """Ask for one section's time range, record count and sample interval."""
        return bytes([0x57, 0x0F, 0x69, 0x08, 0x02, section])

    @staticmethod
    def read_records(section: int, offset: int, count: int) -> bytes:
        """Ask for `count` records starting at record index `offset`."""
        return bytes([0x57, 0x0F, 0x69, 0x08, 0x03, section]) + offset.to_bytes(4, "big") + bytes([count])

    @staticmethod
    def set_clock() -> bytes:
        """Push this machine's clock and UTC offset to the device.

        The whole-hour part of the offset goes in its own byte biased by +12; any
        sub-hour remainder is folded into the timestamp and also sent as minutes.
        """
        now = datetime.now().astimezone()
        offset = now.utcoffset()
        total_seconds = int(offset.total_seconds()) if offset is not None else 0
        # Java truncates toward zero here, so -12600 // 3600 == -4 would be wrong.
        whole_hours = int(total_seconds / 3600)
        remainder = abs(total_seconds) % 3600
        epoch = int(time.time()) + (-remainder if total_seconds < 0 else remainder)
        return (
            bytes([0x57, 0x00, 0x05, 0x03, (whole_hours + 12) & 0xFF])
            + epoch.to_bytes(8, "big")
            + bytes([remainder // 60])
        )


class Response:
    """Decode all responses"""

    @staticmethod
    def parse_store_info(reply: bytes) -> list[int]:
        """Section IDs. Count is the low nibble of byte 1, IDs follow it."""
        if len(reply) < 2:
            raise ProtocolError(f"store info reply too short: {reply.hex()}")
        n = reply[1] & 0x0F
        if len(reply) < 2 + n:
            raise ProtocolError(f"store info claims {n} sections but reply is {reply.hex()}")
        return list(reply[2 : 2 + n])

    @staticmethod
    def parse_section_info(section: int, reply: bytes) -> SectionInfo:
        """Times are 4-byte epochs, count is 4 bytes, interval is 2. All big-endian.

        Older meters use a 2-byte count here; the Pro widened it.
        """
        if len(reply) < 15:
            raise ProtocolError(f"section info reply too short: {reply.hex()}")
        return SectionInfo(
            section=section,
            start_time=int.from_bytes(reply[1:5], "big"),
            end_time=int.from_bytes(reply[5:9], "big"),
            count=int.from_bytes(reply[9:13], "big"),
            interval=int.from_bytes(reply[13:15], "big"),
        )

    @staticmethod
    def parse_record_resp(reply: bytes, count: int) -> list[tuple[float, int, int]]:
        """Decode a read reply into at most `count` records."""
        body = reply[1:]
        expected = math.ceil(count / RECORDS_PER_GROUP) * GROUP_SIZE_BYTES
        if len(body) != expected:
            raise ProtocolError(f"expected {expected} bytes for {count} records, got {len(body)}: {reply.hex()}")
        records: list[tuple[float, int, int]] = []
        for i in range(0, len(body), GROUP_SIZE_BYTES):
            records += Response.__parse_record_group(body[i : i + GROUP_SIZE_BYTES])
        return records[:count]

    @staticmethod
    def __parse_record_group(group: bytes) -> list[tuple[float, int, int]]:
        """Unpack one 9-byte group into its two (temp, humidity, co2) records.

        A record is 36 bits: 12-bit temperature, 8-bit humidity, 16-bit CO2. Two
        of them round up to 9 bytes, which is why the tenths digits of both
        temperatures share byte 2.
        """
        tenths = group[2]
        out = []
        for whole, humidity, tenth, co2 in (
            (group[0], group[1], tenths >> 4, int.from_bytes(group[5:7], "big")),
            (group[3], group[4], tenths & 0x0F, int.from_bytes(group[7:9], "big")),
        ):
            temp = (whole & 0x7F) + tenth / 10.0
            # Bit 7 SET means positive, which is the opposite of the usual convention.
            if not whole & 0x80:
                temp = -temp
            out.append((round(temp, 1), humidity & 0x7F, co2))
        return out


class MeterSession:
    """Commands are sent one at a time and each have a response"""

    def __init__(self, client: BleakClient, timeout: float) -> None:
        self.client = client
        self.timeout = timeout
        self._pending: asyncio.Future[bytes] | None = None

    def _on_notify(self, _sender: object, data: bytearray) -> None:
        if self._pending is not None and not self._pending.done():
            self._pending.set_result(bytes(data))

    async def start(self) -> None:
        # Write 0x0001 to the CCCD, which the device requires before it will answer anything
        await self.client.start_notify(CHAR_NOTIFY, self._on_notify)

    async def request(self, payload: bytes) -> bytes:
        """Send request, wait for reply"""
        self._pending = asyncio.get_running_loop().create_future()
        try:
            await self.client.write_gatt_char(CHAR_WRITE, payload, response=True)
            reply = await asyncio.wait_for(self._pending, self.timeout)
        except asyncio.TimeoutError as exc:
            raise ProtocolError(f"no reply to {payload.hex()} within {self.timeout}s") from exc
        finally:
            self._pending = None
        if not reply:
            raise ProtocolError(f"empty reply to {payload.hex()}")
        if reply[0] not in STATUS_OK:
            raise ProtocolError(f"command {payload.hex()} failed with status 0x{reply[0]:02x}")
        return reply


def show_progress(done: int, total: int, page: int, pages: int, started: float) -> None:
    elapsed = time.monotonic() - started
    rate = done / elapsed if elapsed > 0 else 0.0
    eta = (total - done) / rate if rate > 0 else 0.0
    bar_width = 30
    filled = int(bar_width * done / total) if total else bar_width
    print(
        f"\r  [{'#' * filled}{'.' * (bar_width - filled)}] "
        f"page {page:>4}/{pages}  {done:>5}/{total} records  ETA {eta:4.0f}s",
        end="",
        file=sys.stderr,
        flush=True,
    )


async def download_section(session: MeterSession, info: SectionInfo, page_size: int) -> list[HistoryRecord]:

    def _plan_pages(total: int, page_size: int) -> list[tuple[int, int]]:
        """Returns list of (offset, count) pairs covering every record with possibly a short page last."""
        pages = []
        offset = 0
        while offset < total:
            pages.append((offset, min(page_size, total - offset)))
            offset += page_size
        return pages

    pages = _plan_pages(info.count, page_size)
    print(
        f"  {info.count} records, one every {info.interval}s, {info.timestamp_of(0):%Y-%m-%d %H:%M} to {info.timestamp_of(info.count - 1):%Y-%m-%d %H:%M}",
        file=sys.stderr,
    )
    print(f"  fetching {len(pages)} pages...", file=sys.stderr)

    records: list[HistoryRecord] = []
    started = time.monotonic()
    for page_number, (offset, count) in enumerate(pages, start=1):
        reply = await session.request(Requests.read_records(info.section, offset, count))
        for i, (temp, humidity, co2) in enumerate(Response.parse_record_resp(reply, count)):
            records.append(
                HistoryRecord(
                    timestamp=info.timestamp_of(offset + i),
                    temp_celsius=temp,
                    humidity_percent=humidity,
                    co2_ppm=co2,
                )
            )
        show_progress(len(records), info.count, page_number, len(pages), started)
    print(f"\n  done in {time.monotonic() - started:.1f}s", file=sys.stderr)
    return records


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download stored history from a SwitchBot Meter Pro CO2.")
    parser.add_argument("--address", metavar="MAC", help="device address (default: scan for one)")
    parser.add_argument("--csv", type=Path, metavar="PATH", help="also write records to this CSV file")
    parser.add_argument(
        "--set-clock",
        action="store_true",
        help="set device time to time of this machine",
    )
    return parser.parse_args()


async def find_device(address: str | None, timeout: float) -> BLEDevice | None:
    if address is not None:
        return await BleakScanner.find_device_by_address(address, timeout=timeout)
    for device, adv in (await BleakScanner.discover(timeout=timeout, return_adv=True)).values():
        service_data = adv.service_data.get(UUID_SWITCHBOT_SERVICE_DATA)
        if service_data and (service_data[0] & 0x7F) == DEVICE_TYPE_METER_PRO_CO2:
            return device
    return None


async def main() -> int:
    args = parse_args()

    # Find and connect to device
    print("Scanning...", file=sys.stderr)
    device = await find_device(args.address, timeout=20)
    if device is None:
        target = args.address or "a Meter Pro CO2"
        print(f"Could not find {target}.", file=sys.stderr)
        return 1
    print(f"Connecting to {device.address}...", file=sys.stderr)

    all_records: list[HistoryRecord] = []
    async with BleakClient(device) as client:
        session = MeterSession(client, timeout=10)
        await session.start()

        # Possibly set time on device
        if args.set_clock:
            await session.request(Requests.set_clock())
            print("  clock set", file=sys.stderr)

        # Get store info
        sections = Response.parse_store_info(await session.request(Requests.get_store_info()))
        print(f"  {len(sections)} section(s): {sections}", file=sys.stderr)

        for section in sections:
            # Get info about this store
            info = Response.parse_section_info(section, await session.request(Requests.get_section_info(section)))
            if info.count == 0:
                print(f"  section {section} is empty", file=sys.stderr)
                continue
            # Download data
            all_records += await download_section(session, info, page_size=RECORDS_PER_READ)

    # Output data
    for record in all_records:
        print(record.format_line())

    if args.csv is not None:
        with args.csv.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            writer.writerows(record.as_row() for record in all_records)
        print(f"Wrote {len(all_records)} records to {args.csv}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(130)
    except ProtocolError as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(1)
