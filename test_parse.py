#!/usr/bin/env python3

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from co2 import COMPANY_ID_SWITCHBOT, UUID_SWITCHBOT_SERVICE_DATA, parse_reading

DEVICE = BLEDevice("E1:22:33:44:55:66", "MeterPro CO2", None)

# Capture from the koyashiro write-up. 24.2C, 44%, 903 ppm, battery 100%
SERVICE_CO2 = "350064"
MFR_CO2 = "00005E00530069E402982C0031038700"


def make_adv(service_data: bytes, mfr_data: bytes, rssi: int = -58) -> AdvertisementData:
    return AdvertisementData(
        local_name="MeterPro CO2",
        manufacturer_data={COMPANY_ID_SWITCHBOT: mfr_data} if mfr_data else {},
        service_data={UUID_SWITCHBOT_SERVICE_DATA: service_data} if service_data else {},
        service_uuids=[UUID_SWITCHBOT_SERVICE_DATA],
        tx_power=None,
        rssi=rssi,
        platform_data=(),
    )


def decode(service_hex: str, mfr_hex: str, rssi: int = -58):
    adv = make_adv(bytes.fromhex(service_hex), bytes.fromhex(mfr_hex), rssi)
    return parse_reading(DEVICE, adv)


class ParserTest(unittest.TestCase):
    def test_documented_sample_payload(self):
        reading = decode(SERVICE_CO2, MFR_CO2)
        self.assertEqual(reading.temp_celsius, 24.2)
        self.assertEqual(reading.humidity_percent, 44)
        self.assertEqual(reading.co2_ppm, 903)
        self.assertEqual(reading.battery_percent, 100)
        self.assertEqual(reading.model, "Meter Pro CO2")
        self.assertEqual(reading.rssi_dbm, -58)
        self.assertFalse(reading.is_fahrenheit_disp)

    def test_sign_bit_clear_means_negative_temperature(self):
        # Byte 9 bit 7 SET means positive, so clearing it flips the sign.
        reading = decode(SERVICE_CO2, "00005E00530069E402182C0031038700")
        self.assertEqual(reading.temp_celsius, -24.2)

    def test_fahrenheit_flag_does_not_corrupt_humidity(self):
        # Byte 10 bit 7 is a display flag, humidity is the low 7 bits.
        reading = decode(SERVICE_CO2, "00005E00530069E40298AC0031038700")
        self.assertEqual(reading.humidity_percent, 44)
        self.assertTrue(reading.is_fahrenheit_disp)

    def test_encrypted_flag_does_not_change_device_type(self):
        # Bit 7 of service data byte 0 must be masked off before matching.
        reading = decode("B50064", MFR_CO2)
        self.assertEqual(reading.model, "Meter Pro CO2")

    def test_co2_above_spec_range_is_discarded(self):
        reading = decode(SERVICE_CO2, "00005E00530069E402982C0031FFFF00")
        self.assertIsNone(reading.co2_ppm)
        self.assertEqual(reading.temp_celsius, 24.2)

    def test_no_service_data(self):
        self.assertIsNone(decode("", MFR_CO2))

    def test_wrong_device_type(self):
        self.assertIsNone(decode("690064", MFR_CO2))

    def test_no_manu_data(self):
        self.assertIsNone(decode(SERVICE_CO2, ""))

    def test_manu_data_too_short(self):
        self.assertIsNone(decode(SERVICE_CO2, "00005E005300"))

    def test_zero_packet(self):
        self.assertIsNone(decode("350000", "00005E00530069E400800031000000"))


if __name__ == "__main__":
    unittest.main()
