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
send 0x0011                                   CCCD enable. Enable notifications / response channel
send 570f6805040000000000000000000000         Daylight savings time config
recv 01                                       OK
send 0x0011                                   CCCD enable, again. Redundant probably
send 5700050308 00000000 6a9e1faf 00          set clock = 2026-09-06 21:21:35
recv 01                                       OK
send 570f690801                               ask for info about log store sections on device
recv 01 510100040302                          log store section response
send 570f69080201                             get section info for section 1
recv 01 6a9e1a4b 6a9e1f73 0000000c 0078       section info response
send 570f690803 01 00000000 04                request 4 records @ offset 0
recv 01 99307799300285028c993088993002770272  read response
send 570f690803 01 00000004 04                request 4 records @ offset 4
recv 01 9931999931027a02799a32009a33028c0287  read response
send 570f690803 01 00000008 04                request 4 records @ offset 8
recv 01 9a34119a34029102999a34129a3402a702aa  read response
```

### Daylight savings time config message:
```
57 0f 68 0504 000000000000000000 0000
              <hasDst> | <startMon startDay startHr startMin> | <endMon endDay endHr endMin> | <offset u16 BE>

byte   value   explain
0     | 57   | magic
1     | 0f   | command ID
2     | 68   | sub command ID for device time config
3-4   | 0504 | command ID for setting DST
5     | 0    | 00 or 01 for using DST or not
6     | 0    | DST start - month
7     | 0    | DST start - day of month
8     | 0    | DST start - hour
9     | 0    | DST start - minute
10    | 0    | DST end - month
11    | 0    | DST end - day of month
12    | 0    | DST end - hour
13    | 0    | DST end - minute
14-15 | 0    | offset big endian - unknown
```

### Set clock message:
```
57000503 08 00000000 6a9e1faf 00
                     ^^^^^^^^-----> big endian unit timestamp. 1788747695 = Sun Sep  6 09:21:35 PM CDT 2026

57 | magic
00 | command 0 no password variant
05 | command ID for time
03 | sub command ID for setting the time
08 | timezone with 12 offset. so 8-12 = -4 -> UTC-4 (which is what timezone the phone was set it)
00000000 | unused
6a9e1faf | timestamp
00 | sub-hour offset for timezone in minutes. For timezones that don't fall on an hour.
```

### Log Store Section Information
```
Request
570f690801 = 57 0f 69 08 01
57 | magic
0f | command number
69 | subcommand number for history / storage
08 | sub sub command number
01 | operation for getting storage info

Response
01510100040302 = 01 51 01 00040302
01 | OK
51 | masked & 0x0F so really is 1 -> section count. There is 1 section
01 | section ID is 1
everything else not used
```
This command is not important.

### Get section info request:
```
570f69080201 = 57 0f 69 08 02 01
---
57 | magic
0f | command number
69 | sub command for history / storage
08 | sub sub command number
02 | sub command id for getting storage section info
01 | section ID
```

### Section info response:
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

Byte  value      explain
0   | 57       | magic
1   | 0f       | command ID 15 (no password)
2   | 69       | subcommand number for history / storage
3-4 | 0803     | sub command ID for read samples
5   | 01       | section ID (from section information message)
6-9 | 00000008 | offset / index start
10  | 04       | number of records requested
```

### Read 4 records response:
- 18 bytes holds 4 records
- 9 bytes for two records each
```
01 99307799300285028c 993088993002770272
OK ^^^^first two^^^^^ ^^^^second two^^^^

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
- most of the time read requests are for 4 records, but I've also seen request for 2 records

### Service and Characteristic UUIDS
- cba20d00-224d-11e6-9fb8-0002a5d5c51b - primary service
- cba20003-224d-11e6-9fb8-0002a5d5c51b - RX responses
- cba20002-224d-11e6-9fb8-0002a5d5c51b - TX writes
