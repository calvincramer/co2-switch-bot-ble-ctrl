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
# help
./co2-current.py -h
./co2-history.py -h
./co2-current.py     # watch for all advertisements, also see MAC addr here for later

./co2-history.py --csv co2.csv  # write CSV log
./co2-current.py --csv co2.csv  # append readings to log
```

## Recording Useful Data
The device advertises the same measurement multiple times before re-sensing the CO2, so by default a reading is only reported when the value changes or when `--min-interval` seconds have passed since the last report. This reduces useless data.
