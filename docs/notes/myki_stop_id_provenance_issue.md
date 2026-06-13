# Myki stop-id provenance issue

Date checked: 2026-06-13

## Finding

The previous canonical Melton commuter generation used transaction column 7 with ID 18. Further inspection shows that transaction column 7 is not a station-specific StopLocationID. It appears to be a rail-line or corridor group code.

The station-specific stop identifier is transaction column 8, which joins to `dataset/MYKI/dimensions/stop_locations.txt`.

## Evidence

Melton platform StopLocationID:
- 19980 = Melton platform

A scan across all available Samp_9 ScanOnTransaction files found no train-mode rows for Melton platform ID 19980 or related Ballarat-corridor platform IDs.

The only Melton station-adjacent IDs found were:
- 21131
- 21132
- 21183
- 21184
- 21185

All matched rows for these IDs were mode=1 bus rows, not train rows.

Maximum daily unique cards for these bus stop IDs were small:
- 21131: 19
- 21132: 15
- 21183: 28
- 21184: 35
- 21185: 26

Therefore, Samp_9 does not contain usable station-level train tap-ons for Melton.

## Consequence

The previous 1465-commuter Melton instance is reproducible but not valid as Melton Station Myki-derived temporal demand. It was generated from column 7 group ID 18, which maps to a different rail corridor rather than Melton Station.

## Recommendation

For station-specific Myki demand generation, use:
- `--stop-id-column 8`
- platform StopLocationID values from `stop_locations.txt`

Valid station-level IDs currently identified:
- Caulfield: 19943, 22248
- Pakenham: 19880, 22252

Melton should not be used as a Myki-derived station-demand case unless another Myki sample containing Melton platform train rows is found.
