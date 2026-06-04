# =========================
# Core build configuration
# =========================
build_dir := cmake-build
flag      := Debug   # default; overridden by 'fast' target

# Original convenience targets
all: build
fast dev: all

dev: flag = Debug
fast: flag = Release

.PHONY: gen build

gen:
	@mkdir -p ${build_dir}
	@echo "cmake -B${build_dir} -H. -DCMAKE_BUILD_TYPE=${flag}"
	@eval "cmake -B${build_dir} -H. -DCMAKE_BUILD_TYPE=${flag}"

build: gen
	@echo "cd ${build_dir} && make -j8"
	@eval "cd ${build_dir} && make -j8"

# =========================
# Paths for labels + runner
# =========================
BIN_DIR         := bin
CONSTRUCT_BIN   := $(BIN_DIR)/construct
SIM_BIN         := $(BIN_DIR)/simulate_first_mile
SIM_ORTOOLS_BIN := $(BIN_DIR)/simulate_first_mile_ortools
DUMP_BIN        := $(BIN_DIR)/dump_distance_matrix

DATASET_DIR    := dataset/MELTON
INPUT_DIR      := files/inputs
MATRICES_DIR   := $(DATASET_DIR)/melton_generic_matrix
CONFIG_DIR     := config

GRAPH_DIST     := $(DATASET_DIR)/melton_graph_distance.txt
GRAPH_TIME     := $(DATASET_DIR)/melton_graph_time.txt

PFX_DIST       := $(DATASET_DIR)/melton_dist
PFX_TIME       := $(DATASET_DIR)/melton_time

COMMUTERS_CSV  := $(INPUT_DIR)/commuters.csv
STATIONS_CSV   := $(INPUT_DIR)/stations.csv
SPEED_TABLE    := $(INPUT_DIR)/melton_graph_speed.txt
CONFIG_FILE    := $(CONFIG_DIR)/base_config.json

# =========================
# Results directories
# =========================
RESULTS_DIR        := results
ORTOOLS_DIR        := $(RESULTS_DIR)/ortools
PYVRP_DIR          := $(RESULTS_DIR)/pyvrp

# OR-Tools outputs
ASSIGN_OUT         := $(ORTOOLS_DIR)/assignments.csv
AV_ROUTES_OUT      := $(ORTOOLS_DIR)/av_routes.csv
BASELINE_JSON      := $(ORTOOLS_DIR)/baseline.json
METRICS_JSON       := $(ORTOOLS_DIR)/metrics.json
COMPARE_JSON       := $(ORTOOLS_DIR)/comparison.json

# PyVRP outputs
PYVRP_ASSIGN       := $(PYVRP_DIR)/assignments.csv
PYVRP_ROUTES       := $(PYVRP_DIR)/av_routes.csv
PYVRP_BASELINE     := $(PYVRP_DIR)/baseline.json
PYVRP_METRICS      := $(PYVRP_DIR)/metrics.json
PYVRP_COMPARE      := $(PYVRP_DIR)/comparison.json

# =========================
# Labels + run targets
# =========================

.PHONY: labels labels_dist labels_time run solver_run ls_labels ls_outputs

labels: labels_dist labels_time

labels_dist: $(PFX_DIST).dorder $(PFX_DIST).dlabel
$(PFX_DIST).dorder $(PFX_DIST).dlabel: $(CONSTRUCT_BIN) $(GRAPH_DIST)
	@test -f "$(GRAPH_DIST)" || (echo "Missing $(GRAPH_DIST)"; exit 1)
	@mkdir -p "$(DATASET_DIR)"
	$(CONSTRUCT_BIN) "$(GRAPH_DIST)" "$(PFX_DIST)" "$(PFX_DIST)"
	@ls -l "$(PFX_DIST).dorder" "$(PFX_DIST).dlabel"

labels_time: $(PFX_TIME).dorder $(PFX_TIME).dlabel
$(PFX_TIME).dorder $(PFX_TIME).dlabel: $(CONSTRUCT_BIN) $(GRAPH_TIME)
	@test -f "$(GRAPH_TIME)" || (echo "Missing $(GRAPH_TIME)"; exit 1)
	@mkdir -p "$(DATASET_DIR)"
	$(CONSTRUCT_BIN) "$(GRAPH_TIME)" "$(PFX_TIME)" "$(PFX_TIME)"
	@ls -l "$(PFX_TIME).dorder" "$(PFX_TIME).dlabel"

run: $(SIM_BIN) $(PFX_DIST).dorder $(PFX_DIST).dlabel $(PFX_TIME).dorder $(PFX_TIME).dlabel
	@test -f "$(COMMUTERS_CSV)" || (echo "Missing $(COMMUTERS_CSV)"; exit 1)
	@test -f "$(STATIONS_CSV)"  || (echo "Missing $(STATIONS_CSV)";  exit 1)
	$(SIM_BIN) "$(COMMUTERS_CSV)" "$(STATIONS_CSV)" "$(PFX_DIST)" "$(PFX_TIME)" "$(ASSIGN_OUT)"
	@ls -l "$(ASSIGN_OUT)" "$(AV_ROUTES_OUT)" || true

solver_run: $(SIM_ORTOOLS_BIN) $(PFX_DIST).dorder $(PFX_DIST).dlabel
	@test -f "$(COMMUTERS_CSV)" || (echo "Missing $(COMMUTERS_CSV)"; exit 1)
	@test -f "$(SPEED_TABLE)"   || (echo "Missing $(SPEED_TABLE)";   exit 1)
	@test -f "$(CONFIG_FILE)"   || (echo "Missing $(CONFIG_FILE)";   exit 1)
	@mkdir -p "$(ORTOOLS_DIR)"
	$(SIM_ORTOOLS_BIN) \
		"$(COMMUTERS_CSV)" \
		"$(STATIONS_CSV)" \
		"$(PFX_DIST)" \
		"$(SPEED_TABLE)" \
		"$(ASSIGN_OUT)" \
		"$(AV_ROUTES_OUT)" \
		"$(CONFIG_FILE)" \
		"$(BASELINE_JSON)" \
		"$(METRICS_JSON)" \
		"$(COMPARE_JSON)"
	@echo ""
	@echo "✓ OR-Tools outputs written to $(ORTOOLS_DIR):"
	@ls -lh "$(ASSIGN_OUT)" "$(AV_ROUTES_OUT)" "$(BASELINE_JSON)" \
	        "$(METRICS_JSON)" "$(COMPARE_JSON)" 2>/dev/null || true

# =========================
# Matrix dump target
# =========================

.PHONY: dump_matrices

dump_matrices: $(DUMP_BIN) $(PFX_DIST).dorder $(PFX_DIST).dlabel
	@test -f "$(COMMUTERS_CSV)" || (echo "Missing $(COMMUTERS_CSV)"; exit 1)
	@test -f "$(SPEED_TABLE)"   || (echo "Missing $(SPEED_TABLE)";   exit 1)
	@mkdir -p "$(MATRICES_DIR)"
	@echo ""
	@echo "╔════════════════════════════════════════════════════════════════╗"
	@echo "║           BUILDING DISTANCE / DURATION MATRICES                ║"
	@echo "╚════════════════════════════════════════════════════════════════╝"
	$(DUMP_BIN) \
		--labels   "$(PFX_DIST)" \
		--nodes    "$(COMMUTERS_CSV)" \
		--station  $(DEST_NODE) \
		--speed    "$(SPEED_TABLE)" \
		--out-dir  "$(MATRICES_DIR)"
	@echo ""
	@echo "✓ Matrices written to $(MATRICES_DIR):"
	@ls -lh "$(MATRICES_DIR)"

# =========================
# PyVRP simulation target
# =========================

.PHONY: pyvrp_run

pyvrp_run:
	@test -d "$(MATRICES_DIR)" || \
		(echo "Missing matrices dir. Run: make dump_matrices"; exit 1)
	@test -f "$(MATRICES_DIR)/distances.npy" || \
		(echo "Matrices not built yet. Run: make dump_matrices"; exit 1)
	@test -f "$(COMMUTERS_CSV)" || (echo "Missing $(COMMUTERS_CSV)"; exit 1)
	@test -f "$(STATIONS_CSV)"  || (echo "Missing $(STATIONS_CSV)";  exit 1)
	@test -f "$(CONFIG_FILE)"   || (echo "Missing $(CONFIG_FILE)";   exit 1)
	@mkdir -p "$(PYVRP_DIR)"
	@echo ""
	@echo "╔════════════════════════════════════════════════════════════════╗"
	@echo "║           PyVRP FIRST-MILE SIMULATION                          ║"
	@echo "╚════════════════════════════════════════════════════════════════╝"
	python python/simulate_first_mile_pyvrp.py \
		"$(COMMUTERS_CSV)" \
		"$(STATIONS_CSV)" \
		"$(MATRICES_DIR)" \
		"$(PYVRP_ASSIGN)" \
		"$(PYVRP_ROUTES)" \
		"$(CONFIG_FILE)" \
		"$(PYVRP_BASELINE)" \
		"$(PYVRP_METRICS)" \
		"$(PYVRP_COMPARE)"
	@echo ""
	@echo "✓ PyVRP outputs written to $(PYVRP_DIR):"
	@ls -lh "$(PYVRP_ASSIGN)" "$(PYVRP_ROUTES)" "$(PYVRP_BASELINE)" \
	        "$(PYVRP_METRICS)" "$(PYVRP_COMPARE)" 2>/dev/null || true

# =========================
# Commuter generation
# Shared variables used by both targets below.
# =========================
COMMUTERS_BIN  := $(BIN_DIR)/build_commuters_reachable
NODES_CSV      := $(INPUT_DIR)/melton_nodes_lat_lon.csv
DEST_NODE      := 19858
SEED           := 42

RESIDENTIAL_OSM_PBF              := dataset/OSM_DATA/melton_osm.pbf
RESIDENTIAL_CANDIDATE_NODES      := $(INPUT_DIR)/melton_residential_candidate_nodes.csv
RESIDENTIAL_CANDIDATE_POINTS     := $(INPUT_DIR)/melton_residential_candidate_points.csv
RESIDENTIAL_CANDIDATE_MAPPING    := $(INPUT_DIR)/melton_residential_candidate_node_mapping.csv
RESIDENTIAL_CANDIDATE_METADATA   := $(INPUT_DIR)/melton_residential_candidates_metadata.json
RESIDENTIAL_COMMUTERS_CSV        := $(INPUT_DIR)/commuters_residential.csv
RESIDENTIAL_COMMUTERS_METADATA   := $(INPUT_DIR)/commuters_residential_metadata.json
RESIDENTIAL_MATRICES_DIR         := $(DATASET_DIR)/melton_residential_matrix
RESIDENTIAL_SMOKE_DIR            := experiments/test_results/residential_smoke_balanced
RESIDENTIAL_WALKING_THRESHOLD_M  := 800

# ── synthetic: commuters_run ──────────────────────────────────────────────────
# Generates commuters.csv with synthetic time windows via the C++ binary alone.
# Use this for controlled experiments where you want a Gaussian/fixed time window.
#
#   make commuters_run                                   # normal_peak defaults
#   make commuters_run TW_POLICY=fixed COMMUTER_N=300
# ─────────────────────────────────────────────────────────────────────────────
COMMUTER_N       := 10

TW_POLICY        := normal_peak
PICKUP_EARLIEST  := 07:00
DROP_OFF_LATEST  := 08:00
PEAK_TIME        := 08:00
CUTOFF_MIN       := 60
WINDOW_WIDTH_MIN := 30

ifeq ($(TW_POLICY),fixed)
  TW_FLAGS := --tw-policy fixed \
              --pickup-earliest $(PICKUP_EARLIEST) \
              --drop-off-latest $(DROP_OFF_LATEST)
else ifeq ($(TW_POLICY),normal_peak)
  TW_FLAGS := --tw-policy normal_peak \
              --peak-time $(PEAK_TIME) \
              --cutoff-minutes $(CUTOFF_MIN) \
              --window-width-minutes $(WINDOW_WIDTH_MIN)
else
  $(error Unknown TW_POLICY='$(TW_POLICY)'. Supported: fixed, normal_peak)
endif

.PHONY: commuters_run

commuters_run: $(COMMUTERS_BIN)
	@test -f "$(NODES_CSV)" || (echo "Missing nodes CSV: $(NODES_CSV)"; exit 1)
	@mkdir -p "$(INPUT_DIR)"
	@echo ""
	@echo "╔════════════════════════════════════════════════════════════════╗"
	@echo "║         GENERATING COMMUTERS  [synthetic time windows]         ║"
	@echo "╚════════════════════════════════════════════════════════════════╝"
	@echo "  Policy : $(TW_POLICY)"
	$(COMMUTERS_BIN) \
		--nodes     "$(NODES_CSV)" \
		--dest-node $(DEST_NODE) \
		--n         $(COMMUTER_N) \
		--out       "$(COMMUTERS_CSV)" \
		--seed      $(SEED) \
		$(TW_FLAGS)
	@echo ""
	@echo "✓ Commuters written to: $(COMMUTERS_CSV)"
	@ls -lh "$(COMMUTERS_CSV)" 2>/dev/null || true

# ── real data: myki_commuters ─────────────────────────────────────────────────
# Generates commuters.csv with real Myki tap-on times as drop_off_latest,
# and spatially-sampled reachability-verified origin nodes from the C++ binary.
#
#   make myki_commuters                        # all available weeks
#   make myki_commuters MYKI_YEAR=2016 MYKI_WEEK=10
# ─────────────────────────────────────────────────────────────────────────────
MYKI_ROOT    := dataset/MYKI/Samp_9
MYKI_SCRIPT  := python/build_myki_commuters.py
# Peak window (start/end) is read from CONFIG_FILE — single source of truth.
# Pickup buffer is a data-building parameter, separate from solver grace period.
PICKUP_BUF   := 30

# Set MYKI_DATE to restrict to a single day YYYY-MM-DD (strongly recommended).
# Without it, all weekdays in the week are pooled into one commuter set.
#   make myki_commuters MYKI_YEAR=2018 MYKI_WEEK=26 MYKI_DATE=2018-06-25
MYKI_YEAR    := 2018
MYKI_WEEK    := 26
MYKI_DATE    := 2018-06-25
# Build --year / --week / --date flags only when the variables are set
_YEAR_FLAG = $(if $(MYKI_YEAR),--year $(MYKI_YEAR),)
_WEEK_FLAG = $(if $(MYKI_WEEK),--week $(MYKI_WEEK),)
_DATE_FLAG = $(if $(MYKI_DATE),--date $(MYKI_DATE),)

.PHONY: myki_commuters residential_candidates myki_commuters_residential dump_matrices_residential pyvrp_run_residential_smoke residential_smoke

myki_commuters: $(COMMUTERS_BIN)
	@test -d "$(MYKI_ROOT)" || \
		(echo "Missing MYKI data: $(MYKI_ROOT)"; exit 1)
	@test -f "$(NODES_CSV)" || \
		(echo "Missing nodes CSV: $(NODES_CSV)"; exit 1)
	@mkdir -p "$(INPUT_DIR)"
	@echo ""
	@echo "╔════════════════════════════════════════════════════════════════╗"
	@echo "║         GENERATING COMMUTERS  [Myki tap-on times]              ║"
	@echo "╚════════════════════════════════════════════════════════════════╝"
	python $(MYKI_SCRIPT) \
		--myki-root     $(MYKI_ROOT) \
		--nodes-file    $(NODES_CSV) \
		--dest-node     $(DEST_NODE) \
		--cpp-bin       $(COMMUTERS_BIN) \
		--labels        $(PFX_DIST) \
		--out           $(COMMUTERS_CSV) \
		--config        $(CONFIG_FILE) \
		--pickup-buffer $(PICKUP_BUF) \
		--seed          $(SEED) \
		$(_YEAR_FLAG) $(_WEEK_FLAG) $(_DATE_FLAG)
	@echo ""
	@echo "✓ Commuters written to: $(COMMUTERS_CSV)"
	@ls -lh "$(COMMUTERS_CSV)" 2>/dev/null || true

residential_candidates:
	@test -f "$(RESIDENTIAL_OSM_PBF)" || \
		(echo "Missing residential OSM PBF: $(RESIDENTIAL_OSM_PBF)"; exit 1)
	@test -f "$(NODES_CSV)" || \
		(echo "Missing road nodes CSV: $(NODES_CSV)"; exit 1)
	@mkdir -p "$(INPUT_DIR)"
	@echo ""
	@echo "╔════════════════════════════════════════════════════════════════╗"
	@echo "║        BUILDING RESIDENTIAL ORIGIN CANDIDATE NODES            ║"
	@echo "╚════════════════════════════════════════════════════════════════╝"
	python python/build_residential_origin_candidates.py \
		--osm-pbf "$(RESIDENTIAL_OSM_PBF)" \
		--road-nodes "$(NODES_CSV)" \
		--station-node $(DEST_NODE) \
		--walking-threshold-m $(RESIDENTIAL_WALKING_THRESHOLD_M) \
		--out-nodes "$(RESIDENTIAL_CANDIDATE_NODES)" \
		--out-points "$(RESIDENTIAL_CANDIDATE_POINTS)" \
		--out-mapping "$(RESIDENTIAL_CANDIDATE_MAPPING)" \
		--metadata-out "$(RESIDENTIAL_CANDIDATE_METADATA)"
	@echo ""
	@echo "✓ Residential candidate nodes written to: $(RESIDENTIAL_CANDIDATE_NODES)"
	@ls -lh "$(RESIDENTIAL_CANDIDATE_NODES)" "$(RESIDENTIAL_CANDIDATE_METADATA)" 2>/dev/null || true

myki_commuters_residential: $(COMMUTERS_BIN)
	@test -d "$(MYKI_ROOT)" || \
		(echo "Missing MYKI data: $(MYKI_ROOT)"; exit 1)
	@test -f "$(RESIDENTIAL_CANDIDATE_NODES)" || \
		(echo "Missing residential candidate nodes: $(RESIDENTIAL_CANDIDATE_NODES)"; \
		 echo "Run: make residential_candidates"; exit 1)
	@test -f "$(RESIDENTIAL_CANDIDATE_METADATA)" || \
		(echo "Missing residential candidate metadata: $(RESIDENTIAL_CANDIDATE_METADATA)"; \
		 echo "Run: make residential_candidates"; exit 1)
	@test -f "$(NODES_CSV)" || \
		(echo "Missing coordinate nodes CSV: $(NODES_CSV)"; exit 1)
	@mkdir -p "$(INPUT_DIR)"
	@echo ""
	@echo "╔════════════════════════════════════════════════════════════════╗"
	@echo "║    GENERATING COMMUTERS  [Myki + residential origin nodes]     ║"
	@echo "╚════════════════════════════════════════════════════════════════╝"
	python $(MYKI_SCRIPT) \
		--myki-root     $(MYKI_ROOT) \
		--nodes-file    $(RESIDENTIAL_CANDIDATE_NODES) \
		--coord-nodes-file $(NODES_CSV) \
		--dest-node     $(DEST_NODE) \
		--cpp-bin       $(COMMUTERS_BIN) \
		--labels        $(PFX_DIST) \
		--out           $(RESIDENTIAL_COMMUTERS_CSV) \
		--config        $(CONFIG_FILE) \
		--pickup-buffer $(PICKUP_BUF) \
		--seed          $(SEED) \
		--origin-sampling random \
		--metadata-out  $(RESIDENTIAL_COMMUTERS_METADATA) \
		--origin-candidate-source osm_residential_address_candidate_nodes \
		--residential-candidate-metadata $(RESIDENTIAL_CANDIDATE_METADATA) \
		$(_YEAR_FLAG) $(_WEEK_FLAG) $(_DATE_FLAG)
	@echo ""
	@echo "✓ Residential commuters written to: $(RESIDENTIAL_COMMUTERS_CSV)"
	@ls -lh "$(RESIDENTIAL_COMMUTERS_CSV)" "$(RESIDENTIAL_COMMUTERS_METADATA)" 2>/dev/null || true

dump_matrices_residential:
	$(MAKE) dump_matrices \
		COMMUTERS_CSV="$(RESIDENTIAL_COMMUTERS_CSV)" \
		MATRICES_DIR="$(RESIDENTIAL_MATRICES_DIR)"

pyvrp_run_residential_smoke:
	$(MAKE) pyvrp_run \
		COMMUTERS_CSV="$(RESIDENTIAL_COMMUTERS_CSV)" \
		MATRICES_DIR="$(RESIDENTIAL_MATRICES_DIR)" \
		CONFIG_FILE="$(CONFIG_FILE)" \
		PYVRP_DIR="$(RESIDENTIAL_SMOKE_DIR)" \
		PYVRP_ASSIGN="$(RESIDENTIAL_SMOKE_DIR)/assignments.csv" \
		PYVRP_ROUTES="$(RESIDENTIAL_SMOKE_DIR)/av_routes.csv" \
		PYVRP_BASELINE="$(RESIDENTIAL_SMOKE_DIR)/baseline.json" \
		PYVRP_METRICS="$(RESIDENTIAL_SMOKE_DIR)/metrics.json" \
		PYVRP_COMPARE="$(RESIDENTIAL_SMOKE_DIR)/comparison.json"

residential_smoke:
	$(MAKE) residential_candidates
	$(MAKE) myki_commuters_residential
	$(MAKE) dump_matrices_residential
	$(MAKE) pyvrp_run_residential_smoke

# =========================
# Unified clean targets
# =========================
.PHONY: clean clean_build clean_labels clean_outputs clean_matrices clean_results

clean: clean_build clean_labels clean_outputs clean_matrices
	@echo "Cleaned everything."

clean_build:
	@if [ -d "$(build_dir)" ]; then \
		echo "Cleaning CMake build in $(build_dir)"; \
		$(MAKE) -C "$(build_dir)" clean || true; \
	fi

clean_labels:
	@rm -f "$(PFX_DIST).dorder" "$(PFX_DIST).dlabel"
	@rm -f "$(PFX_TIME).dorder" "$(PFX_TIME).dlabel"

clean_outputs:
	@rm -f "$(ORTOOLS_DIR)"/*.csv "$(ORTOOLS_DIR)"/*.json
	@rm -f "$(PYVRP_DIR)"/*.csv   "$(PYVRP_DIR)"/*.json

clean_matrices:
	@rm -f "$(MATRICES_DIR)"/*.npy "$(MATRICES_DIR)"/*.txt

clean_results: clean_outputs

ls_labels:
	@ls -l "$(PFX_DIST).dorder" "$(PFX_DIST).dlabel" 2>/dev/null || true
	@ls -l "$(PFX_TIME).dorder" "$(PFX_TIME).dlabel" 2>/dev/null || true

ls_outputs:
	@echo "── OR-Tools ──────────────────────────"
	@ls -lh "$(ORTOOLS_DIR)"/*.csv "$(ORTOOLS_DIR)"/*.json 2>/dev/null || echo "  (none)"
	@echo "── PyVRP ─────────────────────────────"
	@ls -lh "$(PYVRP_DIR)"/*.csv   "$(PYVRP_DIR)"/*.json   2>/dev/null || echo "  (none)"
	@echo "── Matrices ──────────────────────────"
	@ls -lh "$(MATRICES_DIR)"/*.npy "$(MATRICES_DIR)"/*.txt 2>/dev/null || echo "  (none)"

# =========================
# Helper: help menu
# =========================
.PHONY: help
help:
	@echo ""
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  BUILD"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  dev              Configure + build (Debug)"
	@echo "  fast             Configure + build (Release)"
	@echo ""
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  DATA PREPARATION"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  commuters_run    Generate commuters.csv [synthetic time windows]"
	@echo "                   Override: COMMUTER_N, TW_POLICY, PEAK_TIME, ..."
	@echo ""
	@echo "  myki_commuters   Generate commuters.csv [real Myki tap-on times]"
	@echo "                   Override: MYKI_YEAR, MYKI_WEEK, MYKI_DATE"
	@echo ""
	@echo "  residential_candidates"
	@echo "                   Build OSM residential/address candidate node files"
	@echo "  myki_commuters_residential"
	@echo "                   Generate commuters_residential.csv [Myki + residential nodes]"
	@echo "  dump_matrices_residential"
	@echo "                   Build matrices for residential commuters"
	@echo ""
	@echo "  labels           Build distance + time hub labels"
	@echo "  dump_matrices    Build distance/duration matrices for PyVRP"
	@echo ""
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  SIMULATION"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  solver_run       Run OR-Tools simulation → results/ortools/"
	@echo "  pyvrp_run        Run PyVRP simulation    → results/pyvrp/"
	@echo "  pyvrp_run_residential_smoke"
	@echo "                   Run residential PyVRP smoke test"
	@echo "  residential_smoke"
	@echo "                   Run residential candidates → commuters → matrices → smoke"
	@echo ""
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  CLEAN / INSPECT"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  clean            Clean everything"
	@echo "  clean_build      Clean CMake build only"
	@echo "  clean_labels     Remove hub label files"
	@echo "  clean_matrices   Remove .npy matrix files"
	@echo "  clean_outputs    Remove results/ortools/ and results/pyvrp/"
	@echo "  ls_labels        List built label files"
	@echo "  ls_outputs       List all result + matrix files"
	@echo ""
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  EXAMPLES"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  make commuters_run COMMUTER_N=300 TW_POLICY=fixed"
	@echo "  make myki_commuters MYKI_YEAR=2018 MYKI_WEEK=26 MYKI_DATE=2018-06-25"
	@echo "  # Peak window comes from CONFIG_FILE time_window block (single source of truth)"
	@echo "  make dump_matrices && make pyvrp_run"
	@echo "  make solver_run CONFIG_FILE=config/experiment2.json"
	@echo ""
