#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

if [[ -x .venv/bin/python ]]; then
  PYTHON=.venv/bin/python
else
  PYTHON=python3
fi

COMMUTERS=files/inputs/footscray_commuters_residential.csv
STATION=files/inputs/footscray_station.csv
MATRICES=dataset/FOOTSCRAY/footscray_residential_matrix
BASE_CONFIG="${BASE_CONFIG:-config/footscray_base_config.json}"
OUTPUT_DIR=experiments/results/footscray/smoke_balanced_80seats_mb10_h0630_seed1
CONFIG="$OUTPUT_DIR/config.json"

for path in "$COMMUTERS" "$STATION" "$MATRICES/distances.npy" "$BASE_CONFIG"; do
  [[ -e "$path" ]] || { echo "ERROR: Missing required Footscray input: $path" >&2; exit 1; }
done

mkdir -p "$OUTPUT_DIR"

"$PYTHON" -c '
import json
import sys

source, destination = sys.argv[1:]
with open(source) as stream:
    config = json.load(stream)
config["experiment_name"] = "footscray_smoke_balanced_80seats_mb10_h0630"
config["description"] = "Generated Footscray smoke config with a 60-second solver limit."
config["solver_config"]["time_limit_seconds"] = 60
with open(destination, "w") as stream:
    json.dump(config, stream, indent=2)
    stream.write("\n")
' "$BASE_CONFIG" "$CONFIG"

"$PYTHON" python/simulate_first_mile_pyvrp.py \
  "$COMMUTERS" \
  "$STATION" \
  "$MATRICES" \
  "$OUTPUT_DIR/assignments.csv" \
  "$OUTPUT_DIR/av_routes.csv" \
  "$CONFIG" \
  "$OUTPUT_DIR/baseline.json" \
  "$OUTPUT_DIR/metrics.json" \
  "$OUTPUT_DIR/comparison.json" \
  1
