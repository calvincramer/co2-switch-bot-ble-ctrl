# SwitchBot Meter Pro CO2 BLE protocol
Everything this device measures is in its advertisements, no pairing needed.

- model `W4900010`
- device type byte `0x35`

## Advertisement layout
A meter advertisement has two payloads, the service data and the manufacturer data.

### Service data - UUID `0000fd3d-0000-1000-8000-00805f9b34fb`
SwitchBot's assigned 16-bit UUID `0xFD3D`. Three bytes:

| Byte | Meaning |
| --- | --- |
| 0 | `& 0x7F` = device type: **`0x35` Meter Pro CO2**, `0x34` Meter Pro. Bit 7 = "encrypted" flag, mask it off |
| 1 | reserved / group membership |
| 2 | `& 0x7F` = battery percentage |

### Manufacturer data - company ID `0x0969` (2409)

| Byte | Meaning |
| --- | --- |
| 0-5 | device MAC address |
| 6-7 | unknown |
| 8 | `& 0x0F` = temperature decimal, in tenths of degree celsius |
| 9 | `& 0x7F` = temperature whole number degree celsius; `& 0x80` = sign - **bit set means positive** |
| 10 | `& 0x7F` = humidity percentage; `& 0x80` = display-in-°F flag |
| 11-12 | unknown |
| 13-14 | **CO2 in ppm, big-endian uint16** |
| 15 | padding |

The sign bit is inverted from the obvious convention: `0x80` set is a *positive*
temperature.

## Example Decoding
```python
temperature_c = (1 if mfr[9] & 0x80 else -1) * ((mfr[9] & 0x7F) + (mfr[8] & 0x0F) / 10)
humidity_pct  = mfr[10] & 0x7F
co2_ppm       = int.from_bytes(mfr[13:15], "big")   # only if len(mfr) >= 15
battery_pct   = service_data[2] & 0x7F
```

## Example Capture
```
service data  35 00 64
manufacturer  b0e9feb8d4e2 54e4 03 9a b0 00 0b 02a6 00
```

- device type = `0x35`
- battery = `100%`
- MAC = `B0:E9:FE:B8:D4:E2`
- temperature = +26C + 0.3C = 26.3C
- humidity = 48%, F display flag set
- CO2 = 678 ppm.

## Sources

- [koyashiro - SwitchBot Meter Pro CO2 BLE analysis](https://github.com/koyashiro/zenn-contents/blob/main/articles/switch-bot-meter-pro-co2-ble.md)
- [pySwitchbot](https://github.com/sblibs/pySwitchbot) - `adv_parsers/meter.py`, `adv_parsers/_sensor_th.py`, `devices/meter_pro.py`
- [Theengs Decoder - SwitchBot Meter Pro (CO2)](https://decoder.theengs.io/devices/SBMP.html) ([`SBMP_json.h`](https://github.com/theengs/decoder/blob/development/src/devices/SBMP_json.h))
- [SmartHomeScene - ESPHome BLE integration guide](https://smarthomescene.com/guides/how-to-integrate-switchbot-meter-pro-and-meter-pro-co2-in-esphome/)
- [OpenWonderLabs SwitchBotAPI-BLE - meter device types](https://github.com/OpenWonderLabs/SwitchBotAPI-BLE/blob/latest/devicetypes/meter.md)
- [Home Assistant discussion #2305 - manual CO2 reading trigger](https://github.com/orgs/home-assistant/discussions/2305)
- [Home Assistant issue #132155 - Meter Pro CO2 detected as a Light Strip](https://github.com/home-assistant/core/issues/132155)
