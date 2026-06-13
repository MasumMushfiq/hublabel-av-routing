//
// Created by Md Mushfiq on 25/3/2026.
//

// dump_distance_matrix.cpp
//
// Pre-computes two N×N matrices for every pair of locations:
//   distances.npy   — int64, millimetres    (used for VRP arc costs)
//   durations.npy   — int64, milliseconds   (used for time window feasibility)
//
// Matrix layout:  row/col 0 = station (depot)
//                 row/col 1..N = commuters in commuters.csv order
//
// One duration matrix is built per vehicle type (different max_speed_kmph),
// so PyVRP can evaluate time windows correctly for each vehicle type.
//
// Add to CMakeLists.txt:
//   add_executable(dump_distance_matrix dump_distance_matrix.cpp)
//   target_link_libraries(dump_distance_matrix PRIVATE
//       <same libs as simulate_first_mile_ortools>
//   )
//
// Usage:
//   ./dump_distance_matrix \
//       --labels   dataset/MELTON/melton_dist \
//       --nodes    commuters.csv \
//       --station  19858 \
//       --speed    speed_table.txt \
//       --out-dir  matrices/
//
// Outputs (all in --out-dir):
//   distances.npy          — shape (N+1, N+1) int64 mm
//   duration_30kmph.npy    — shape (N+1, N+1) int64 ms  (Scooter)
//   duration_45kmph.npy    — shape (N+1, N+1) int64 ms  (Moped)
//   duration_70kmph.npy    — shape (N+1, N+1) int64 ms  (Minibus)
//   duration_80kmph.npy    — shape (N+1, N+1) int64 ms  (Car)
//   nodes.txt              — node IDs in matrix order (station first)

#include <iostream>
#include <fstream>
#include <sstream>
#include <vector>
#include <string>
#include <cstdint>
#include <cmath>
#include <algorithm>
#include <stdexcept>
#include <unordered_map>

#include "planner/hub_label_utils.h"
#include "planner/id_types.h"
#include "planner/edge_attrs.h"

// ── argument parsing ──────────────────────────────────────────────────────

struct Args {
    std::string labels_prefix;
    std::string nodes_csv;
    int         station_node = -1;
    std::string speed_table;
    std::string out_dir = ".";
};

static Args parse_args(int argc, char** argv) {
    Args a;
    for (int i = 1; i + 1 < argc; ++i) {
        std::string k = argv[i], v = argv[i + 1];
        if      (k == "--labels")  { a.labels_prefix = v; ++i; }
        else if (k == "--nodes")   { a.nodes_csv     = v; ++i; }
        else if (k == "--station") { a.station_node  = std::stoi(v); ++i; }
        else if (k == "--speed")   { a.speed_table   = v; ++i; }
        else if (k == "--out-dir") { a.out_dir        = v; ++i; }
    }
    if (a.labels_prefix.empty() || a.nodes_csv.empty() ||
        a.station_node < 0 || a.speed_table.empty()) {
        std::cerr <<
            "Usage: dump_distance_matrix\n"
            "  --labels   <dist_label_prefix>\n"
            "  --nodes    <commuters.csv>\n"
            "  --station  <station_node_id>\n"
            "  --speed    <speed_table.txt>\n"
            "  --out-dir  <output_directory>  (default: .)\n";
        std::exit(1);
    }
    return a;
}

// ── read origin_node column from commuters.csv ────────────────────────────

static std::vector<int> read_commuter_nodes(const std::string& path) {
    std::ifstream f(path);
    if (!f) throw std::runtime_error("Cannot open: " + path);

    std::string header;
    std::getline(f, header);

    // find origin_node column index
    int origin_col = -1, col_idx = 0;
    std::istringstream hss(header);
    std::string col;
    while (std::getline(hss, col, ',')) {
        if (col == "origin_node") { origin_col = col_idx; break; }
        ++col_idx;
    }
    if (origin_col < 0)
        throw std::runtime_error("Column 'origin_node' not found in: " + path);

    std::vector<int> nodes;
    std::string line;
    while (std::getline(f, line)) {
        if (line.empty()) continue;
        std::istringstream ss(line);
        std::string field;
        for (int c = 0; c <= origin_col; ++c) std::getline(ss, field, ',');
        nodes.push_back(std::stoi(field));
    }
    return nodes;
}

// ── load speed table ──────────────────────────────────────────────────────
// Format: u v length_m speed_kph  (space or tab separated)

static std::unordered_map<EdgeKey, EdgeAttr> load_speed_table(const std::string& path) {
    std::unordered_map<EdgeKey, EdgeAttr> tbl;
    std::ifstream f(path);
    if (!f) throw std::runtime_error("Cannot open speed table: " + path);
    std::string line;
    while (std::getline(f, line)) {
        if (line.empty() || line[0] == '#') continue;
        std::istringstream ss(line);
        int u, v; double length_m, speed_kph;
        if (!(ss >> u >> v >> length_m >> speed_kph)) continue;
        EdgeAttr ea;
        ea.length_m  = length_m;
        ea.speed_kph = speed_kph;
        tbl[edge_key(u, v)] = ea;
    }
    return tbl;
}

// ── travel time along a path ──────────────────────────────────────────────
// Same logic as your C++ time_ms_along_path

static int64_t travel_time_ms(const std::vector<int>& path,
                               const std::unordered_map<EdgeKey, EdgeAttr>& edge_tbl,
                               double max_kph)
{
    if (path.size() < 2) return 0;
    int64_t sum = 0;
    for (size_t i = 1; i < path.size(); ++i) {
        auto it = edge_tbl.find(edge_key(path[i-1], path[i]));
        if (it == edge_tbl.end()) { sum += 3'600'000; continue; }
        double eff_kph = std::min(it->second.speed_kph, max_kph);
        double mps = std::max(0.1, eff_kph) * (1000.0 / 3600.0);
        sum += static_cast<int64_t>(std::ceil((it->second.length_m / mps) * 1000.0));
    }
    return sum;
}

// ── write numpy .npy  (int64, C-order, version 1.0) ──────────────────────

static void write_npy_int64(const std::string& path,
                             const std::vector<int64_t>& data,
                             int rows, int cols)
{
    std::ofstream f(path, std::ios::binary);
    if (!f) throw std::runtime_error("Cannot write: " + path);

    const char magic[] = "\x93NUMPY\x01\x00";
    f.write(magic, 8);

    std::ostringstream hdr;
    hdr << "{'descr': '<i8', 'fortran_order': False, 'shape': ("
        << rows << ", " << cols << "), }";
    std::string hs = hdr.str();

    // pad so that (10 + len(header)) % 64 == 0
    size_t total = 10 + hs.size() + 1;  // 10 = 8 magic + 2 len bytes
    size_t pad = (64 - total % 64) % 64;
    hs.append(pad, ' ');
    hs += '\n';

    uint16_t hlen = static_cast<uint16_t>(hs.size());
    f.write(reinterpret_cast<const char*>(&hlen), 2);
    f.write(hs.data(), hs.size());
    f.write(reinterpret_cast<const char*>(data.data()),
            static_cast<std::streamsize>(data.size() * sizeof(int64_t)));
}

// ── main ──────────────────────────────────────────────────────────────────

int main(int argc, char** argv) {
    Args args = parse_args(argc, argv);

    // Validate the commuter schema before loading large routing artifacts.
    std::vector<int> commuter_nodes;
    try {
        commuter_nodes = read_commuter_nodes(args.nodes_csv);
    } catch (const std::exception& e) {
        std::cerr << "ERROR: Invalid matrix input CSV: " << e.what() << "\n"
                  << "Expected a final commuter CSV with an 'origin_node' column, "
                  << "not a candidate-node pool.\n";
        return 1;
    }

    // 1. Load hub labels
    std::cerr << "Loading hub labels: " << args.labels_prefix << "\n";
    if (!init_distance_labels(args.labels_prefix)) {
        std::cerr << "ERROR: Failed to load hub labels.\n"; return 1;
    }

    // 2. Load speed table
    std::cerr << "Loading speed table: " << args.speed_table << "\n";
    auto edge_tbl = load_speed_table(args.speed_table);
    std::cerr << "  Loaded " << edge_tbl.size() << " edges\n";

    // 3. Report the already-validated commuter nodes
    int N = static_cast<int>(commuter_nodes.size());
    int M = N + 1;  // depot + N commuters
    std::cerr << "Commuters: " << N << "  →  matrix size: " << M << "×" << M << "\n";

    // 4. Build node list: [station, c0, c1, ...]
    std::vector<int> all_nodes;
    all_nodes.reserve(M);
    all_nodes.push_back(args.station_node);
    for (int n : commuter_nodes) all_nodes.push_back(n);

    // 5. Vehicle speeds to compute duration matrices for
    // Match your config: Scooter=25, Moped=45, Minibus=70, Car=80
    std::vector<double> speeds = {25.0, 30.0, 45.0, 70.0, 80.0};

    // 6. Allocate matrices
    std::vector<int64_t> dist_mm(M * M, 0);
    std::vector<std::vector<int64_t>> dur_ms(speeds.size(),
                                              std::vector<int64_t>(M * M, 0));

    // 7. Query all pairs
    std::cerr << "Querying " << M << "×" << M << " = " << (M*M) << " pairs...\n";
    int progress_step = std::max(1, M / 20);

    for (int i = 0; i < M; ++i) {
        if (i % progress_step == 0)
            std::cerr << "  " << (100 * i / M) << "%\r" << std::flush;

        for (int j = 0; j < M; ++j) {
            if (i == j) continue;

            std::vector<int> path;
            int d = distance_mm(
                static_cast<NodeID>(all_nodes[i]),
                static_cast<NodeID>(all_nodes[j]),
                &path
            );

            if (d <= 0) {
                // Unreachable — use large penalty
                dist_mm[i * M + j] = static_cast<int64_t>(1e12);
                for (auto& dm : dur_ms)
                    dm[i * M + j] = static_cast<int64_t>(1e10);
            } else {
                dist_mm[i * M + j] = static_cast<int64_t>(d);
                for (size_t s = 0; s < speeds.size(); ++s)
                    dur_ms[s][i * M + j] = travel_time_ms(path, edge_tbl, speeds[s]);
            }
        }
    }
    std::cerr << "  100%\n";
    std::cerr << "Done querying.\n\n";

    // 8. Write distance matrix
    std::string dist_path = args.out_dir + "/distances.npy";
    write_npy_int64(dist_path, dist_mm, M, M);
    std::cerr << "Written: " << dist_path << "\n";

    // 9. Write duration matrices (one per speed)
    for (size_t s = 0; s < speeds.size(); ++s) {
        std::string fname = args.out_dir + "/duration_"
                          + std::to_string(static_cast<int>(speeds[s]))
                          + "kmph.npy";
        write_npy_int64(fname, dur_ms[s], M, M);
        std::cerr << "Written: " << fname << "\n";
    }

    // 10. Write node order file
    std::string nodes_path = args.out_dir + "/nodes.txt";
    std::ofstream nf(nodes_path);
    for (int n : all_nodes) nf << n << "\n";
    std::cerr << "Written: " << nodes_path << "\n";

    std::cerr << "\n";
    std::cerr << "All matrices ready. Load in Python:\n";
    std::cerr << "  import numpy as np\n";
    std::cerr << "  dist   = np.load('" << args.out_dir << "/distances.npy')\n";
    std::cerr << "  dur_30 = np.load('" << args.out_dir << "/duration_30kmph.npy')\n";
    std::cerr << "  nodes  = [int(l) for l in open('" << nodes_path << "')]\n";
    std::cerr << "  # index 0 = station (" << args.station_node << ")\n";
    std::cerr << "  # index 1..N = commuters\n";

    return 0;
}
