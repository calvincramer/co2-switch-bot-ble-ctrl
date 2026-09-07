# Decompile and look at SwitchBot app to verify protocol
- Android app version 10.1, using JADX

## Setup
Download the APK from phone:
```sh
# Get the downloaded
adb shell pm list packages | grep -i switchbot    # com.theswitchbot.switchbot

# Inspect version info
adb shell dumpsys package com.theswitchbot.switchbot | grep -E 'versionName|versionCode|lastUpdateTime'
#    versionCode=30000146 minSdk=24 targetSdk=35
#    versionName=10.1
#    lastUpdateTime=2026-09-06 22:19:46

# Download all APKs
adb shell pm path com.theswitchbot.switchbot | sed 's/^package://' | tr -d '\r' | while read -r p; do adb pull "$p"; done
```

Export JADX project to App with "Export Project"

## Notes
Where to look?
- com/theswitchbot
- com/qihoo

- has UUIDs for the CO2 monitor:
    - com/theswitchbot/common/ble/impl/WoBleClient
    - com/qihoo/ble.scan/O0000OOo

