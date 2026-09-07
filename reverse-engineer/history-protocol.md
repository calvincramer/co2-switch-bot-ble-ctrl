# Reverse Engineering Sync
This is to get the previous measurements that are stored on the device, not just listening for the current data from the bluetooth advertisements.

## Get Bluetooth Packet Capture Steps
Setup
1. Get old android phone that I wiped, sign into google (twice yay for long randomized passwords)
    - OnePlus 6, Android 10
2. install SwitchBot app on the phone
3. setup computer
```sh
sudo apt install adb android-sdk-platform-tools-common wireshark tshark
sudo usermod -aG wireshark $USER
```
4. log out from user and log back in
5. enable things in developer settings
    - USB Debugging
    - Bluetooth HCI snoop log
6. plug phone into computer
7. `adb devices` to see it connected

Get capture
8. turn off bluetooth then back on
9. open Wireshark, select `Android Bluetooth Btsnoop Net ....`
    - type in `btatt` in the filter
10. open app and run sync for device
11. stop capture in Wireshark
12. save capture to file

## Capture Analysis
Pcap to useful format
```sh
for f in *.pcapng; do
    tshark -r "$f" -Y btatt -T fields -e frame.number -e frame.time_relative -e btatt.opcode -e btatt.handle -e btatt.value -e btatt.uuid128 -e btatt.starting_handle -e btatt.ending_handle -E separator=';' -E aggregator='|' -E quote=n > "${f%.pcapng}.csv"
done
```

### Command sequence:
```
x send 0x0011                                   CCCD enable. Enable notifications / response channel
  send 570f6805040000000000000000000000         ??? unknown setup
  recv 01
x send 0x0011                                   CCCD enable, again. Redundant probably
x send 5700050308 00000000 6a9e1faf 00          set clock = 2026-09-06 21:21:35
x recv 01
  send 570f690801                               query capability
  recv 01 510100040302                          ??? unknown, maybe related to the 4 bytes per read
x send 570f69080201                             query history metadata
x recv 01 6a9e1a4b 6a9e1f73 0000000c 0078       history metadata response
x send 570f690803 01 00000000 04                read 4 records @ offset 0
x recv 01 99307799300285028c993088993002770272
x send 570f690803 01 00000004 04                read 4 records @ offset 4
x recv 01 9931999931027a02799a32009a33028c0287
x send 570f690803 01 00000008 04                read 4 records @ offset 8
x recv 01 9a34119a34029102999a34129a3402a702aa
```

### Set clock message:
```
5700050308 00000000 6a9e1faf 00
                    ^^^^^^^^-----> big endian unit timestamp. 1788747695 = Sun Sep  6 09:21:35 PM CDT 2026
```

### Metadata response:
```
01 6a9e1a4b 6a9e1f73 0000000c 0078
---
01       | nothing                                |
6a9e1a4b | oldest record in Unix epoch big endian | 2026-09-06 20:58:35
6a9e1f73 | newest record in Unix epoch big endian | 2026-09-06 21:20:35
0000000c | record count                           | 12
0078     | sample interval in seconds             | 120 seconds
```

### Read request message:
```
570f690803 01 00000008 04 --> offset 0x8 read 4 records. Response will be 18 bytes
570f690803 01 0000017c 02 --> offset 0x17c read 2 records. Response will be 9 bytes
```

### Read 4 records response:
- 18 bytes holds 4 records
- 9 bytes for two records each
```
01 99307799300285028c 993088993002770272
        first two         second two

First two: 99 30 77 99 30 0285 028c
Byte
0   | Record A temp in celsius whole number part (& 0x7F), 0x80 bit high means positive, low means negative
1   | Record A humidity in percent (& 0x7F), 0x80 for display in Fahrenheit option
2   | high and low nibbles for A/B temperature decimal parts respectively. In tenths of a degree celsius
3   | Record B temp whole part
4   | Record B humidity
5-6 | Record A CO2 PPM big-endian
7-8 | Record B CO2 PPM big-endian
```

### Notes:
- All commands have SwitchBot 0x57 magic value
- responses begin with `0x01` byte
- history commands start with `57 0f 69 08`

### TODO:
- reverse engineer app for more info
- make python decoder
