#!/usr/bin/env python3

"""
This script continuously listens for the current sensor information from a SwitchBot Meter Pro CO2.

See reverse-engineer/protocol-advertisements.md for more info.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from bleak.uuids import normalize_uuid_16

import co2_csv

# Service data UUID: 0000fd3d-0000-1000-8000-00805f9b34fb
UUID_SWITCHBOT_SERVICE_DATA = normalize_uuid_16(0xFD3D)

# Manufacturer data company ID. Bleak strips these two bytes from the payload.
COMPANY_ID_SWITCHBOT = 0x0969  # decimal 2409

# Service data byte 0, the first 7 bits
DEVICE_TYPE_METER_PRO_CO2 = 0x35

# High range of the sensor spec. Anything larger is a bad packet.
CO2_MAX_PPM = 9999


@dataclass(frozen=True)
class Reading:
    timestamp: datetime
    address: str
    name: str | None
    device_type: int
    temp_celsius: float
    humidity_percent: int
    co2_ppm: int | None
    battery_percent: int | None
    is_fahrenheit_disp: bool
    rssi_dbm: int | None

    @property
    def model(self) -> str:
        return "Meter Pro CO2"

    @property
    def values(self) -> tuple:
        """The measurements only, for deciding whether a reading actually changed."""
        return (self.temp_celsius, self.humidity_percent, self.co2_ppm, self.battery_percent)

    def as_row(self) -> dict[str, str | float | int | None]:
        return {
            "ts": self.timestamp.isoformat(timespec="seconds"),
            # "addr": self.address,
            # "model": self.model,
            "temp_c": self.temp_celsius,
            "humidity_percent": self.humidity_percent,
            "co2_ppm": self.co2_ppm,
            # "battery_percent": self.battery_percent,
            # "rssi_dbm": self.rssi_dbm,
        }

    def format_line(self) -> str:
        return "  ".join(
            [
                self.timestamp.isoformat(timespec="seconds"),
                self.address,
                f"{self.temp_celsius:5.1f} C",
                f"{self.humidity_percent:3d}%",
                f"{self.co2_ppm:5d} ppm" if self.co2_ppm is not None else "    -- ppm",
                "batt " + (f"{self.battery_percent:3d}%" if self.battery_percent is not None else " --%"),
                f"{self.rssi_dbm:4d} dBm" if self.rssi_dbm is not None else "  -- dBm",
                self.model,
            ]
        )


def parse_device_type(service_data: bytes | None) -> int | None:
    """Get the device type from byte 0 of the service data"""
    if not service_data or len(service_data) < 1:
        return None
    device_type = service_data[0] & 0b01111111
    if device_type != DEVICE_TYPE_METER_PRO_CO2:
        return None
    return device_type


def parse_reading(device: BLEDevice, adv: AdvertisementData) -> Reading | None:
    """Decode an advertisement into a Reading or None if the advertisement is bad"""
    service_data = adv.service_data.get(UUID_SWITCHBOT_SERVICE_DATA)
    device_type = parse_device_type(service_data)
    if device_type is None:
        return None

    # Temperature and humidity live in the manufacturer data, not the service data.
    # Meter Pro sends 15 bytes, Meter Pro CO2 sends 16.
    mfr_data = adv.manufacturer_data.get(COMPANY_ID_SWITCHBOT)
    if not mfr_data or len(mfr_data) < 11:
        return None

    # Byte 9 bit 7 SET means positive. Sign is inverted from what you'd expect.
    temp_sign = 1 if mfr_data[9] & 0b10000000 else -1
    temperature_c = temp_sign * ((mfr_data[9] & 0b01111111) + (mfr_data[8] & 0b00001111) / 10)
    humidity_pct = mfr_data[10] & 0b01111111
    fahrenheit_display = bool(mfr_data[10] & 0b10000000)

    battery_pct: int | None = None
    if len(service_data) >= 3:
        battery_pct = service_data[2] & 0b01111111

    # An all-zero packet is the device saying nothing, not 0 C / 0% / 0 ppm.
    if temperature_c == 0 and humidity_pct == 0 and battery_pct == 0:
        return None

    co2_ppm: int | None = None
    if len(mfr_data) >= 15:
        co2 = int.from_bytes(mfr_data[13:15], "big")
        if co2 <= CO2_MAX_PPM:
            co2_ppm = co2

    return Reading(
        timestamp=datetime.now(timezone.utc).astimezone(),
        address=device.address,
        name=device.name,
        device_type=device_type,
        temp_celsius=round(temperature_c, 1),
        humidity_percent=humidity_pct,
        co2_ppm=co2_ppm,
        battery_percent=battery_pct,
        is_fahrenheit_disp=fahrenheit_display,
        rssi_dbm=adv.rssi,
    )


class Monitor:
    """
    Listens for meter advertisements and emits the interesting ones.

    The device re-broadcasts the same numbers every second or so, and only
    samples CO2 every half hour, so emitting every advertisement is mostly
    noise. By default a reading is emitted when a value changes, or when
    min_interval seconds have passed since the last one for that device.
    """

    def __init__(
        self,
        addresses: set[str] | None,
        min_interval: float,
        emit_all: bool,
        as_json: bool,
        csv_log: co2_csv.CsvLog | None,
    ) -> None:
        self.addresses = addresses
        self.min_interval = min_interval
        self.emit_all = emit_all
        self.as_json = as_json
        self.csv_log = csv_log
        self._last_emitted: dict[str, Reading] = {}

    def __matches_filter(self, device: BLEDevice) -> bool:
        """Address match?"""
        return self.addresses is None or device.address.upper() in self.addresses

    def __should_emit(self, reading: Reading) -> bool:
        """Different reading from previous? Or enough time has elapsed since previously emitted?"""
        if self.emit_all:
            return True
        previous = self._last_emitted.get(reading.address)
        if previous is None or previous.values != reading.values:
            return True
        return (reading.timestamp - previous.timestamp).total_seconds() >= self.min_interval

    def __emit(self, reading: Reading) -> None:
        """Output sensor readings somewhere/s"""
        # Screen
        if self.as_json:
            print(json.dumps(reading.as_row()), flush=True)
        else:
            print(reading.format_line(), flush=True)

        # File
        if self.csv_log is not None:
            self.csv_log.add(reading.as_row())
        return None

    def callback(self, device: BLEDevice, adv: AdvertisementData) -> None:
        if not self.__matches_filter(device):
            return None
        reading = parse_reading(device, adv)
        if reading is None:
            return None
        if self.__should_emit(reading):
            self.__emit(reading)
            self._last_emitted[reading.address] = reading
        return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read a SwitchBot Meter Pro CO2 over Bluetooth advertisements.")
    parser.add_argument(
        "--address",
        action="append",
        metavar="MAC",
        help="only report for this device",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        metavar="PATH",
        help="add readings to this CSV file. Works with an existing CSV file",
    )
    parser.add_argument(
        "--min-interval",
        type=float,
        default=300.0,
        metavar="SECONDS",
        help="re-report unchanged readings this often (default 300)",
    )
    parser.add_argument(
        "--emit-all",
        action="store_true",
        help="report every advertisement, without deduplicating",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=0.0,
        metavar="SECONDS",
        help="stop scanning after this long",
    )
    parser.add_argument("-j", "--json", action="store_true", help="print JSON lines")
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    addresses = {a.upper() for a in args.address} if args.address else None
    csv_log = co2_csv.CsvLog(args.csv) if args.csv is not None else None

    monitor = Monitor(
        addresses=addresses,
        min_interval=args.min_interval,
        emit_all=args.emit_all,
        as_json=args.json,
        csv_log=csv_log,
    )

    if not args.json:
        target = ", ".join(sorted(addresses)) if addresses else "any Meter Pro in range"
        print(f"Scanning for {target}... (ctrl-c to stop)", file=sys.stderr)

    try:
        # Active scanning is required since the measurements are in the scan response
        async with BleakScanner(monitor.callback):
            if args.timeout > 0:
                await asyncio.sleep(args.timeout)
            else:
                await asyncio.Event().wait()
    except asyncio.CancelledError:
        pass
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(130)
