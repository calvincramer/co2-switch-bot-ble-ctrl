# SwitchBot Meter Pro CO2 BLE Protocol
The **current** sensor information is sent in bluetooth advertisements (no pairing needed).

- model `W4900010`
- device type byte `0x35`

## Current Sensor Advertisement Layout
A meter advertisement has two payloads, the service data and the manufacturer data.

### Service data - UUID `0000fd3d-0000-1000-8000-00805f9b34fb`
SwitchBot's assigned 16-bit UUID is `0xFD3D` and has three bytes:

```
350064

Byte val explanation
0    35  (& 0x7F) device type, 0x35 for Meter Pro CO2. Bit 7 is encrypted flag
1    00  group / reserved
2    64  (& 0x7F) battery percentage. 100%
```

### Manufacturer data - company ID `0x0969` (2409)
16 bytes:

```
b0e9feb8d4e2 36e4 02 9a b4 0016 02a9 00

Bytes   val explanation
0-5   | b0e9feb8d4e2 | device MAC address
6-7   | 36e4         | unknown
8     | 02           | (& 0x0F) temperature decimal, in tenths of degree celsius. 0.2C
9     | 9a           | (& 0x7F) temperature whole number degree celsius. (& 0x80) is the sign bit where 1 means positive, 0 is negative. +26C
10    | b4           | (& 0x7F) humidity percentage. (& 0x80) is the display-in-F flag. 52%, display in Fahrenheit
11-12 | 0016         | unknown
13-14 | 02a9         | CO2 in ppm, big-endian unsigned. 681 PPM
15    | 00           | padding

So 'b0e9feb8d4e2 36e4 02 9a b4 0016 02a9 00' is 681 PPM, 26.2C (79.2F b/c of F flag), 52% humidity
```
