# Reverse Engineering Sync
This is to get the previous measurements that are stored on the device, not just listening for the current data from the bluetooth advertisements.

## Steps
1. Get old android phone that I wiped, sign into google (twice yay for long randomized passwords)
2. install SwitchBot app
3. computer `sudo apt install adb android-sdk-platform-tools-common`
4. enable things in developer settings
    - USB Debugging
    - Bluetooth HCI snoop log
5. plug phone into computer
6. `adb devices`
7. turn off bluetooth then back on
8. open app and run sync for device
9. have Claude to use `dumpsys bluetooth_manager` to get data ...