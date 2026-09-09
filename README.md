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
```

## Usage
```sh
# run tests
python3 -m unittest

# help
./co2Adv.py -h
./co2Hist.py -h
./co2Adv.py     # watch for all advertisements, also see MAC addr here for later

./co2Hist.py --csv co2.csv  # merge stored history into the CSV log
./co2Adv.py --csv co2.csv  # add live readings to the same log

./co2Hist.py --start 2026-01-01 --end 2026-01-02  # download data in a time range
```
Time range flags take ISO times (`2026-01-02`, `2026-01-02T14:30`), local unless an offset is given. Either one can be left off to mean "as far back as the device goes" or "up to the newest record". Only the records inside the range are read off the device, so a short window syncs in a fraction of the time of a full download.

## The CSV Log
Both scripts write the same file and are safe to run at the same time. However the rows get there, the file stays sorted oldest first with exactly one row per point in time, so re-downloading history over an existing log adds only what is missing instead of duplicating it. Writes go through `co2_csv.py`, which locks the file for the read-modify-write.

## Recording Useful Data
The device advertises the same measurement multiple times before re-sensing the CO2, so by default a reading is only reported when the value changes or when `--min-interval` seconds have passed since the last report. This reduces useless data.
