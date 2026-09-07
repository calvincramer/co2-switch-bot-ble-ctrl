# SwitchBot Meter Pro CO2 BLE Protocol
The **current** sensor information is sent in bluetooth advertisements. No pairing is needed to read this information.

- model `W4900010`
- device type byte `0x35`

## Current Sensor Advertisement Layout
A meter advertisement has two payloads, the service data and the manufacturer data.

### Service data - UUID `0000fd3d-0000-1000-8000-00805f9b34fb`
SwitchBot's assigned 16-bit UUID is `0xFD3D` and has three bytes:

- byte 0 - `& 0x7F` is device type: `0x35` is Meter Pro CO2. Bit 7 is "encrypted" flag
- byte 1 - reserved / group membership
- byte 2 - `& 0x7F` is battery percentage

### Manufacturer data - company ID `0x0969` (2409)
16 bytes:

- bytes 0-5 - device MAC address
- bytes 6-7 - unknown
- byte 8 - `& 0x0F` - temperature decimal, in tenths of degree celsius
- byte 9 - `& 0x7F` - temperature whole number degree celsius. `& 0x80` is the sign, where set means positive!
- byte 10 - `& 0x7F` - humidity percentage. `& 0x80` is the display-in-F flag
- bytes 11-12 - unknown
- bytes 13-14 - CO2 in ppm, big-endian unsigned
- byte 15 - padding

### Sources

- [koyashiro - SwitchBot Meter Pro CO2 BLE analysis](https://github.com/koyashiro/zenn-contents/blob/main/articles/switch-bot-meter-pro-co2-ble.md)
- [pySwitchbot](https://github.com/sblibs/pySwitchbot) - `adv_parsers/meter.py`, `adv_parsers/_sensor_th.py`, `devices/meter_pro.py`
- [Theengs Decoder - SwitchBot Meter Pro (CO2)](https://decoder.theengs.io/devices/SBMP.html) ([`SBMP_json.h`](https://github.com/theengs/decoder/blob/development/src/devices/SBMP_json.h))
- [SmartHomeScene - ESPHome BLE integration guide](https://smarthomescene.com/guides/how-to-integrate-switchbot-meter-pro-and-meter-pro-co2-in-esphome/)
- [OpenWonderLabs SwitchBotAPI-BLE - meter device types](https://github.com/OpenWonderLabs/SwitchBotAPI-BLE/blob/latest/devicetypes/meter.md)
- [Home Assistant discussion #2305 - manual CO2 reading trigger](https://github.com/orgs/home-assistant/discussions/2305)
- [Home Assistant issue #132155 - Meter Pro CO2 detected as a Light Strip](https://github.com/home-assistant/core/issues/132155)
