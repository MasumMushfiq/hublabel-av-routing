// build_commuters_reachable.cpp
// Generate commuters.csv with EXACT schema:
//   id,origin_node,destination_node,pickup_earliest,drop_off_latest
//
// - Reads a nodes CSV with {id, lat, lon} (column names auto-detected, case-insensitive).
// - Uses farthest-point sampling (Haversine) to order all nodes by spatial spread.
// - For each candidate in that order, checks reachability via query_path(origin, dest, path).
// - Collects exactly N reachable commuters (skipping unreachable nodes).
// - Assigns time windows using a pluggable TimeWindowPolicy (see time_window_policy.h).
//
// Compile (link with your graph library that provides query_path):
//   g++ -std=c++17 -O2 build_commuters_reachable.cpp -o build_commuters
//
// ─── Time-window policies ────────────────────────────────────────────────────
//
//  --tw-policy fixed  --pickup-earliest HH:MM  --drop-off-latest HH:MM
//      (default when no --tw-policy is given; replicates legacy behaviour)
//
//  --tw-policy normal_peak
//      --peak-time HH:MM          required  centre of the Gaussian
//      --cutoff-minutes N         required  half-width clamping range (±N min)
//      --window-width-minutes M   required  width of each commuter's window
//
//      Each commuter gets:
//        drop_off_latest  ~ N(peak_time, σ)  clamped to [peak-N, peak+N]
//        pickup_earliest  = drop_off_latest - M minutes
//        σ is derived automatically as cutoff/3  (±3σ ≈ 99.7 % inside cutoff)
//
// ─── Full usage ──────────────────────────────────────────────────────────────
//
//  Fixed (legacy):
//   ./build_commuters --nodes melton_nodes.csv --dest-node 10353 --n 300
//     --out commuters.csv
//     --tw-policy fixed --pickup-earliest 07:00 --drop-off-latest 08:00
//
//  Normal peak:
//   ./build_commuters --nodes melton_nodes.csv --dest-node 10353 --n 300
//     --out commuters.csv
//     --tw-policy normal_peak --peak-time 08:00 --cutoff-minutes 60
//     --window-width-minutes 30
//
//  Optional flags (all policies):
//     [--labels LABEL_PREFIX]  [--seed 42]  [--allow-dest-as-origin]
//
// ─────────────────────────────────────────────────────────────────────────────

#include <algorithm>
#include <cassert>
#include <cmath>
#include <fstream>
#include <iostream>
#include <memory>
#include <random>
#include <sstream>
#include <string>
#include <vector>
#include <limits>
#include <optional>
#include <set>

#include "planner/hub_label_utils.h"
#include "planner/id_types.h"
#include "planner/time_window_policy.h"

// ─────────────────────────────────────────────────────────────────────────────
// CSV helpers
// ─────────────────────────────────────────────────────────────────────────────

static inline std::string lower_copy(std::string s) {
    std::transform(s.begin(), s.end(), s.begin(),
                   [](unsigned char c){ return std::tolower(c); });
    return s;
}

// Simple CSV split – assumes no embedded commas / quotes.
static std::vector<std::string> split_csv_line(const std::string& line) {
    std::vector<std::string> out;
    std::string cur;
    for (char ch : line) {
        if (ch == ',') { out.push_back(cur); cur.clear(); }
        else           { cur.push_back(ch); }
    }
    out.push_back(cur);
    return out;
}

struct NodeRow { int node_id; double lat; double lon; };

// ─────────────────────────────────────────────────────────────────────────────
// Args
// ─────────────────────────────────────────────────────────────────────────────

struct Args {
    // Core
    std::string nodes_path;
    std::string labels_prefix = "dataset/MELTON/melton_dist";
    int         dest_node     = -1;
    int         n             = -1;
    std::string out_path;
    uint64_t    seed          = 42;
    bool        allow_dest_as_origin = false;

    // ── Time-window policy selection ──────────────────────────────────────
    // --tw-policy fixed | normal_peak   (default = "fixed")
    std::string tw_policy = "fixed";

    // fixed policy args
    std::string pickup_earliest = "07:00";
    std::string drop_off_latest = "08:00";

    // normal_peak policy args
    std::string peak_time          = "";   // HH:MM
    int         cutoff_minutes     = -1;
    int         window_width_min   = -1;
};

static void print_usage(const char* prog) {
    std::cerr
        << "Usage:\n"
        << "  " << prog << " --nodes NODES.csv --dest-node ID --n N --out commuters.csv\n"
        << "     [--labels LABEL_PREFIX]  [--seed 42]  [--allow-dest-as-origin]\n"
        << "\n"
        << "  Time-window policy (choose one):\n"
        << "    --tw-policy fixed\n"
        << "        --pickup-earliest HH:MM   (default 07:00)\n"
        << "        --drop-off-latest HH:MM   (default 08:00)\n"
        << "\n"
        << "    --tw-policy normal_peak\n"
        << "        --peak-time HH:MM           [required]\n"
        << "        --cutoff-minutes N           [required]  half-width of clamped range\n"
        << "        --window-width-minutes M     [required]  per-commuter window width\n"
        << "\n";
}

static bool parse_args(int argc, char** argv, Args& a) {
    for (int i = 1; i < argc; ++i) {
        std::string k = argv[i];
        auto require_next = [&]() -> std::string {
            if (i + 1 >= argc) {
                std::cerr << "Flag " << k << " requires a value.\n";
                std::exit(1);
            }
            return std::string(argv[++i]);
        };

        // ── core ──────────────────────────────────────────────────────────
        if      (k == "--nodes")              { a.nodes_path   = require_next(); }
        else if (k == "--dest-node")          { a.dest_node    = std::stoi(require_next()); }
        else if (k == "--n")                  { a.n            = std::stoi(require_next()); }
        else if (k == "--out")                { a.out_path     = require_next(); }
        else if (k == "--seed")               { a.seed         = std::stoull(require_next()); }
        else if (k == "--labels")             { a.labels_prefix= require_next(); }
        else if (k == "--allow-dest-as-origin") { a.allow_dest_as_origin = true; }

        // ── policy selector ───────────────────────────────────────────────
        else if (k == "--tw-policy")          { a.tw_policy    = require_next(); }

        // ── fixed policy args ─────────────────────────────────────────────
        else if (k == "--pickup-earliest")    { a.pickup_earliest = require_next(); }
        else if (k == "--drop-off-latest")    { a.drop_off_latest = require_next(); }

        // ── normal_peak policy args ────────────────────────────────────────
        else if (k == "--peak-time")          { a.peak_time       = require_next(); }
        else if (k == "--cutoff-minutes")     { a.cutoff_minutes  = std::stoi(require_next()); }
        else if (k == "--window-width-minutes"){ a.window_width_min= std::stoi(require_next()); }

        else {
            std::cerr << "Unknown argument: " << k << "\n";
            print_usage(argv[0]);
            return false;
        }
    }

    bool core_ok = !a.nodes_path.empty() && a.dest_node >= 0
                   && a.n > 0 && !a.out_path.empty();
    if (!core_ok) {
        print_usage(argv[0]);
        return false;
    }

    // Validate policy-specific required args
    if (a.tw_policy == "normal_peak") {
        if (a.peak_time.empty() || a.cutoff_minutes <= 0 || a.window_width_min <= 0) {
            std::cerr << "[normal_peak] requires --peak-time, --cutoff-minutes, "
                         "--window-width-minutes (all > 0).\n";
            print_usage(argv[0]);
            return false;
        }
    } else if (a.tw_policy != "fixed") {
        std::cerr << "Unknown --tw-policy '" << a.tw_policy
                  << "'.  Supported: fixed, normal_peak\n";
        return false;
    }

    return true;
}

// ─────────────────────────────────────────────────────────────────────────────
// Column auto-detection
// ─────────────────────────────────────────────────────────────────────────────

static int pick_col_idx(const std::vector<std::string>& headers,
                        const std::vector<std::string>& candidates) {
    for (size_t i = 0; i < headers.size(); ++i)
        for (auto& c : candidates) if (headers[i] == c) return (int)i;
    std::vector<std::string> lower(headers.size());
    for (size_t i = 0; i < headers.size(); ++i) lower[i] = lower_copy(headers[i]);
    for (size_t i = 0; i < headers.size(); ++i)
        for (auto& c : candidates) if (lower[i] == lower_copy(c)) return (int)i;
    return -1;
}

// ─────────────────────────────────────────────────────────────────────────────
// Geo helpers (Haversine)
// ─────────────────────────────────────────────────────────────────────────────

static inline double radians(double d) { return d * M_PI / 180.0; }

static double haversine_km(double lat1, double lon1, double lat2, double lon2) {
    static const double R = 6371.0088;
    double phi1 = radians(lat1), phi2 = radians(lat2);
    double dphi = radians(lat2 - lat1);
    double dl   = radians(lon2 - lon1);
    double a = std::sin(dphi/2)*std::sin(dphi/2)
             + std::cos(phi1)*std::cos(phi2)*std::sin(dl/2)*std::sin(dl/2);
    return R * 2.0 * std::asin(std::sqrt(a));
}

// Greedy farthest-point sampling – returns a spatially-spread ordering of [0..m).
static std::vector<size_t> farthest_point_ordering(const std::vector<NodeRow>& nodes,
                                                    uint64_t seed) {
    const size_t m = nodes.size();
    std::vector<size_t> order;
    order.reserve(m);
    if (m == 0) return order;

    std::mt19937_64 rng(seed);
    size_t start = std::uniform_int_distribution<size_t>(0, m - 1)(rng);
    order.push_back(start);

    std::vector<double> dmin(m, std::numeric_limits<double>::infinity());
    for (size_t i = 0; i < m; ++i) {
        if (i == start) { dmin[i] = 0.0; continue; }
        dmin[i] = haversine_km(nodes[i].lat, nodes[i].lon,
                               nodes[start].lat, nodes[start].lon);
    }

    for (size_t iter = 1; iter < m; ++iter) {
        size_t best = 0; double best_d = -1.0;
        for (size_t i = 0; i < m; ++i)
            if (std::isfinite(dmin[i]) && dmin[i] > best_d)
                { best_d = dmin[i]; best = i; }
        order.push_back(best);
        for (size_t i = 0; i < m; ++i) {
            if (i == best) { dmin[i] = 0.0; continue; }
            double d = haversine_km(nodes[i].lat, nodes[i].lon,
                                    nodes[best].lat, nodes[best].lon);
            if (d < dmin[i]) dmin[i] = d;
        }
    }
    return order;
}

// ─────────────────────────────────────────────────────────────────────────────
// Main
// ─────────────────────────────────────────────────────────────────────────────

int main(int argc, char** argv) {
    std::ios::sync_with_stdio(false);

    Args args;
    if (!parse_args(argc, argv, args)) return 1;

    // ── Build the requested policy ─────────────────────────────────────────
    std::unique_ptr<TimeWindowPolicy> policy;
    try {
        if (args.tw_policy == "fixed") {
            policy = std::make_unique<FixedPolicy>(
                args.pickup_earliest, args.drop_off_latest);
        } else {   // normal_peak – already validated in parse_args
            policy = std::make_unique<NormalPeakPolicy>(
                parse_hhmm(args.peak_time),
                args.cutoff_minutes,
                args.window_width_min);
        }
    } catch (const std::exception& ex) {
        std::cerr << "Policy construction failed: " << ex.what() << "\n";
        return 1;
    }

    // ── Read nodes CSV ─────────────────────────────────────────────────────
    std::ifstream fin(args.nodes_path);
    if (!fin) {
        std::cerr << "Nodes CSV not found: " << args.nodes_path << "\n";
        return 2;
    }
    std::string header_line;
    if (!std::getline(fin, header_line)) {
        std::cerr << "Empty nodes CSV.\n";
        return 3;
    }
    auto headers = split_csv_line(header_line);

    const std::vector<std::string> ID_CANDIDATES  = {"node_id","id","node","osmid"};
    const std::vector<std::string> LAT_CANDIDATES = {"lat","latitude","y"};
    const std::vector<std::string> LON_CANDIDATES = {"lon","lng","longitude","x"};

    int id_idx  = pick_col_idx(headers, ID_CANDIDATES);
    int lat_idx = pick_col_idx(headers, LAT_CANDIDATES);
    int lon_idx = pick_col_idx(headers, LON_CANDIDATES);

    if (id_idx < 0 || lat_idx < 0 || lon_idx < 0) {
        std::cerr << "Failed to auto-detect columns.\n"
                  << "Need id in {node_id,id,node,osmid}, "
                  << "lat in {lat,latitude,y}, "
                  << "lon in {lon,lng,longitude,x}.\n";
        return 4;
    }

    std::vector<NodeRow> nodes;
    nodes.reserve(1 << 20);
    std::string line;
    while (std::getline(fin, line)) {
        if (line.empty()) continue;
        auto cols = split_csv_line(line);
        if ((int)cols.size() <= std::max({id_idx, lat_idx, lon_idx})) continue;
        try {
            auto trim = [](std::string s) {
                size_t a = 0, b = s.size();
                while (a < b && std::isspace((unsigned char)s[a])) ++a;
                while (b > a && std::isspace((unsigned char)s[b-1])) --b;
                return s.substr(a, b - a);
            };
            int    nid = std::stoi(trim(cols[id_idx]));
            double lat = std::stod(trim(cols[lat_idx]));
            double lon = std::stod(trim(cols[lon_idx]));
            if (!args.allow_dest_as_origin && nid == args.dest_node) continue;
            if (std::isfinite(lat) && std::isfinite(lon))
                nodes.push_back({nid, lat, lon});
        } catch (...) { continue; }
    }
    fin.close();

    if (nodes.empty()) {
        std::cerr << "No valid origin candidates after filtering.\n";
        return 5;
    }
    if (args.n > (int)nodes.size()) {
        std::cerr << "Requested " << args.n << " commuters but only "
                  << nodes.size() << " candidates; will collect at most "
                  << nodes.size() << ".\n";
    }

    // ── Spatial ordering ───────────────────────────────────────────────────
    auto order = farthest_point_ordering(nodes, args.seed);

    // ── Load distance labels ───────────────────────────────────────────────
    if (!init_distance_labels(args.labels_prefix)) {
        std::cerr << "Failed to load distance labels: " << args.labels_prefix << "\n";
        return 3;
    }
    auto query_path = [](int s, int t, std::vector<int>& out) -> int {
        return distance_mm(s, t, &out);
    };

    // ── Banner ─────────────────────────────────────────────────────────────
    std::cout << "\n";
    std::cout << "╔════════════════════════════════════════════════════════════════╗\n";
    std::cout << "║              VALIDATING COMMUTER REACHABILITY                  ║\n";
    std::cout << "╚════════════════════════════════════════════════════════════════╝\n";
    std::cout << "  Time-window policy : " << policy->description() << "\n\n";

    // ── Collect reachable commuters ────────────────────────────────────────
    // RNG for time-window sampling (same seed → reproducible)
    std::mt19937_64 tw_rng(args.seed ^ 0xDEADBEEFCAFEULL);

    struct Commuter {
        int id; int origin; int dest;
        std::string pickup_earliest;
        std::string drop_off_latest;
    };
    std::vector<Commuter> reachable;
    reachable.reserve((size_t)std::min(args.n, (int)nodes.size()));

    int next_id = 0;
    for (size_t rank = 0;
         rank < order.size() && (int)reachable.size() < args.n;
         ++rank)
    {
        const auto& row = nodes[order[rank]];
        // Bidirectional reachability check:
        //   fwd: origin → station  (commuter's travel direction)
        //   rev: station → origin  (vehicle dispatched from depot to pickup)
        // Both must be reachable. A node that fails the reverse check will
        // receive a sentinel distance in the matrix and be unconditionally
        // skipped by the solver regardless of penalty or fleet size.
        std::vector<int> fwd_path, rev_path;
        int fwd_dist = query_path(row.node_id, args.dest_node, fwd_path);
        int rev_dist = query_path(args.dest_node, row.node_id, rev_path);

        bool fwd_ok = (fwd_dist > 0 && !fwd_path.empty());
        bool rev_ok = (rev_dist > 0 && !rev_path.empty());

        if (fwd_ok && rev_ok) {
            // Assign time window via policy
            TimeWindow tw = policy->assign((size_t)next_id, tw_rng);
            reachable.push_back({
                next_id++, row.node_id, args.dest_node,
                tw.pickup_earliest, tw.drop_off_latest
            });
        } else {
            if (!fwd_ok)
                std::cerr << u8"⚠️  Node " << row.node_id
                          << " unreachable → station " << args.dest_node
                          << " (forward)\n";
            if (!rev_ok)
                std::cerr << u8"⚠️  Node " << row.node_id
                          << " unreachable from station " << args.dest_node
                          << " (reverse — vehicle cannot reach pickup)\n";
        }
    }

    if ((int)reachable.size() < args.n) {
        std::cerr << "Only " << reachable.size() << " reachable origins found out of "
                  << nodes.size() << " candidates.\n";
    }

    // ── Write output CSV ───────────────────────────────────────────────────
    std::ofstream fout(args.out_path);
    if (!fout) {
        std::cerr << "Failed to open output path: " << args.out_path << "\n";
        return 7;
    }
    fout << "id,origin_node,destination_node,pickup_earliest,drop_off_latest\n";
    for (const auto& c : reachable) {
        fout << c.id << ","
             << c.origin << ","
             << c.dest << ","
             << c.pickup_earliest << ","
             << c.drop_off_latest << "\n";
    }
    fout.close();

    std::cerr << "Wrote " << reachable.size()
              << " commuters → " << args.out_path << "\n";
    return 0;
}