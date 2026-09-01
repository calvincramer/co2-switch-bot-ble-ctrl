# CO2 Measurement for SwitchBot Meter Pro (CO2 Monitor)
I got a SwitchBot Meter Pro CO2 to measure CO2 (W4900010). This repo is to access the data directly, without an app or an account.

## Goals:
1. programmatic access to data on the device without needing an app or an account
2. get data over time periodically
3. see the data in nice graphs

## Setup
Recommended to use conda:
```sh
conda create --name co2 python=3.13
conda activate co2
python3 -m pip install -r requirements.txt

./co2.py
```

## Usage
```sh
./co2.py -h  # Help
./co2.py     # watch for all advertisements, also see MAC addr here for later

./co2.py --csv co2.csv  # append readings to a CSV log
```

## Logging Over Time Notes
The device rebroadcasts the same numbers constantly, so by default a reading is only reported when a value changes or when `--min-interval` seconds (default 300) have passed since the last report. That keeps a CSV log readable without dropping real changes. `--all` disables it and reports every advertisement.

```sh
./co2.py -o ~/co2.csv          # one row per change, or every 5 minutes
./co2.py -o ~/co2.csv -i 60    # ... or every minute
```
