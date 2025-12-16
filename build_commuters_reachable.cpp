//
// Created by Md Mushfiq on 7/11/2025.
//

// build_commuters_reachable.cpp
// Generate commuters.csv with EXACT schema:
// id,origin_node,destination_node,pickup_earliest,drop_off_latest
//
// - Reads a nodes CSV with {id, lat, lon} (column names auto-detected, case-insensitive).
// - Uses farthest-point sampling (Haversine) to order all nodes by spatial spread.
// - For each candidate in that order, checks reachability via query_path(origin, dest, path).
// - Collects exactly N reachable commuters (skipping unreachable nodes).
// - Writes CSV with constant time windows you can edit below.
//
// Compile (link with your graph library that provides query_path):
//   g++ -std=c++17 -O2 build_commuters_reachable.cpp -o build_commuters
//
// Usage:
//   ./build_commuters \
//     --nodes /path/to/melton_nodes_lat_lon.csv \
//     --dest-node 10353 \
//     --n 300 \
//     --out /path/to/commuters.csv \
//     [--seed 42] \
//     [--allow-dest-as-origin]
//
// Note: If you want to test compile without your graph lib, you can define DEMO_FAKE_QUERY
// which stubs query_path to "reachable". DO NOT use that in production.
//   g++ -std=c++17 -O2 -DDEMO_FAKE_QUERY build_commuters_reachable.cpp -o build_commuters

#include <algorithm>
#include <cassert>
#include <cmath>
#include <fstream>
#include <iostream>
#include <random>
#include <sstream>
#include <string>
#include <vector>
#include <limits>
#include <optional>
#include <set>

#include "planner/hub_label_utils.h"
#include "planner/id_types.h"

// ------------------ EDIT THESE DEFAULT TIME WINDOWS IF YOU WANT ------------------
static const std::string PICKUP_EARLIEST_DEFAULT = "07:00";
static const std::string DROP_OFF_LATEST_DEFAULT = "08:00";
// ---------------------------------------------------------------------------------

// ----- Reachability API (link your real implementation) -----
// #ifndef DEMO_FAKE_QUERY
// // Provided by your routing / hub-label lib
// // Returns distance (>0) and fills `path` if reachable; else <=0 / empty path.
// extern int query_path(int origin_node, int dest_node, std::vector<int>& path);
// #else
// // DEMO ONLY: mock "everything reachable" with positive distance.
// int query_path(int origin_node, int dest_node, std::vector<int>& path) {
//     (void)origin_node; (void)dest_node;
//     path = {origin_node, dest_node};
//     return 1; // positive => reachable
// }
// #endif

// ----------------- CSV helpers -----------------
static inline std::string lower_copy(std::string s) {
    std::transform(s.begin(), s.end(), s.begin(),
                   [](unsigned char c){ return std::tolower(c); });
    return s;
}

// very simple CSV split (assumes no embedded commas/quotes)
// If your nodes file can have quoted fields with commas, replace with a robust parser.
static std::vector<std::string> split_csv_line(const std::string& line) {
    std::vector<std::string> out;
    std::string cur;
    for (char ch : line) {
        if (ch == ',') { out.push_back(cur); cur.clear(); }
        else { cur.push_back(ch); }
    }
    out.push_back(cur);
    return out;
}

struct NodeRow {
    int node_id;
    double lat;
    double lon;
};

struct Args {
    std::string nodes_path;
    std::string labels_prefix = "dataset/MELTON/melton_dist";  // NEW - with default
    int dest_node = -1;
    int n = -1;
    std::string out_path;
    uint64_t seed = 42;
    bool allow_dest_as_origin = false;
};

static bool parse_args(int argc, char** argv, Args& a) {
    std::set<std::string> flags = {"--allow-dest-as-origin"};
    for (int i = 1; i < argc; ++i) {
        std::string k = argv[i];
        auto next = [&](int i)->std::optional<std::string>{
            if (i+1 < argc) return std::string(argv[i+1]);
            return std::nullopt;
        };
        if (k == "--nodes") {
            auto v = next(i); if (!v) return false; a.nodes_path = *v; ++i;
        } else if (k == "--dest-node") {
            auto v = next(i); if (!v) return false; a.dest_node = std::stoi(*v); ++i;
        } else if (k == "--n") {
            auto v = next(i); if (!v) return false; a.n = std::stoi(*v); ++i;
        } else if (k == "--out") {
            auto v = next(i); if (!v) return false; a.out_path = *v; ++i;
        } else if (k == "--seed") {
            auto v = next(i); if (!v) return false; a.seed = std::stoull(*v); ++i;
        } else if (k == "--allow-dest-as-origin") {
            a.allow_dest_as_origin = true;
        } else if (k == "--labels") {
            auto v = next(i); if (!v) return false;
            a.labels_prefix = *v; ++i;
        } else {
            std::cerr << "Unknown argument: " << k << "\n";
            return false;
        }
    }
    bool ok = !a.nodes_path.empty() && a.dest_node >= 0 && a.n > 0 && !a.out_path.empty();
    if (!ok) {
        std::cerr << "Usage:\n  " << argv[0] << " --nodes NODES.csv --dest-node ID --n N --out commuters.csv "
             << "[--labels LABEL_PREFIX] [--seed 42] [--allow-dest-as-origin]\n";

    }
    return ok;
}

// Try candidates, case-insensitive
static int pick_col_idx(const std::vector<std::string>& headers,
                        const std::vector<std::string>& candidates) {
    // direct
    for (size_t i = 0; i < headers.size(); ++i) {
        for (auto& c : candidates) if (headers[i] == c) return (int)i;
    }
    // case-insensitive
    std::vector<std::string> lower(headers.size());
    for (size_t i = 0; i < headers.size(); ++i) lower[i] = lower_copy(headers[i]);
    for (size_t i = 0; i < headers.size(); ++i) {
        for (auto& c : candidates) if (lower[i] == lower_copy(c)) return (int)i;
    }
    return -1;
}

// ------------- Geo helpers (Haversine in km) -------------
static inline double radians(double d){ return d * M_PI / 180.0; }
static double haversine_km(double lat1, double lon1, double lat2, double lon2) {
    static const double R = 6371.0088; // mean Earth radius (km)
    double phi1 = radians(lat1), phi2 = radians(lat2);
    double dphi = radians(lat2 - lat1);
    double dl   = radians(lon2 - lon1);
    double a = std::sin(dphi/2)*std::sin(dphi/2) +
               std::cos(phi1)*std::cos(phi2)*std::sin(dl/2)*std::sin(dl/2);
    double c = 2 * std::asin(std::sqrt(a));
    return R * c;
}

// Return an ordering of indices [0..m) by greedy farthest-point sampling across *all* candidates.
// Start index is random (seeded). Good for producing a spatially spread ranking.
static std::vector<size_t> farthest_point_ordering(const std::vector<NodeRow>& nodes, uint64_t seed) {
    const size_t m = nodes.size();
    std::vector<size_t> order;
    order.reserve(m);
    if (m == 0) return order;

    std::mt19937_64 rng(seed);
    std::uniform_int_distribution<size_t> unif(0, m-1);
    size_t start = unif(rng);
    order.push_back(start);

    // dmin[i] = distance from node i to nearest already-selected center
    std::vector<double> dmin(m, std::numeric_limits<double>::infinity());
    for (size_t i = 0; i < m; ++i) {
        if (i == start) { dmin[i] = 0.0; continue; }
        dmin[i] = haversine_km(nodes[i].lat, nodes[i].lon, nodes[start].lat, nodes[start].lon);
    }

    for (size_t iter = 1; iter < m; ++iter) {
        // pick i with max dmin[i]
        size_t next_i = 0;
        double best_d = -1.0;
        for (size_t i = 0; i < m; ++i) {
            if (std::isfinite(dmin[i]) && dmin[i] > best_d) {
                best_d = dmin[i];
                next_i = i;
            }
        }
        order.push_back(next_i);

        // update dmin wrt the newly selected center
        for (size_t i = 0; i < m; ++i) {
            if (i == next_i) { dmin[i] = 0.0; continue; }
            double d = haversine_km(nodes[i].lat, nodes[i].lon, nodes[next_i].lat, nodes[next_i].lon);
            if (d < dmin[i]) dmin[i] = d;
        }
        // Mark next_i as selected by keeping dmin as 0
    }
    return order;
}

// ------------------- Main -------------------
int main(int argc, char** argv) {
    std::ios::sync_with_stdio(false);

    Args args;
    if (!parse_args(argc, argv, args)) return 1;

    // Read CSV
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
    nodes.reserve(1<<20);

    // Read rows
    std::string line;
    size_t lineno = 1;
    while (std::getline(fin, line)) {
        ++lineno;
        if (line.empty()) continue;
        auto cols = split_csv_line(line);
        if ((int)cols.size() <= std::max({id_idx, lat_idx, lon_idx})) continue;

        try {
            // Trim spaces
            auto trim = [](std::string s){
                size_t a = 0, b = s.size();
                while (a < b && std::isspace((unsigned char)s[a])) ++a;
                while (b > a && std::isspace((unsigned char)s[b-1])) --b;
                return s.substr(a,b-a);
            };
            int nid = std::stoi(trim(cols[id_idx]));
            double lat = std::stod(trim(cols[lat_idx]));
            double lon = std::stod(trim(cols[lon_idx]));
            if (!args.allow_dest_as_origin && nid == args.dest_node) continue;
            if (std::isfinite(lat) && std::isfinite(lon)) {
                nodes.push_back({nid, lat, lon});
            }
        } catch (...) {
            // skip malformed row
            continue;
        }
    }
    fin.close();

    if (nodes.empty()) {
        std::cerr << "No valid origin candidates after filtering.\n";
        return 5;
    }

    // If requested N exceeds candidates, we can only try to gather at most candidates.size() reachables.
    if (args.n > (int)nodes.size()) {
        std::cerr << "Requested " << args.n << " commuters but only " << nodes.size()
                  << " origin candidates available; will attempt to collect " << nodes.size()
                  << " reachable commuters.\n";
    }

    // Order all candidates by farthest-point sampling (spatially spread ranking)
    auto order = farthest_point_ordering(nodes, args.seed);


    if (!init_distance_labels(args.labels_prefix))
    {
        std::cerr << "Failed to load distance labels: " << args.labels_prefix << "\n";
        return 3;
    }

    auto query_path = [](int s, int t, std::vector<int>& out)-> int
    {
        return distance_mm(s, t, &out);
    };


    std::cout << "\n";
    std::cout << "╔════════════════════════════════════════════════════════════════╗\n";
    std::cout << "║              VALIDATING COMMUTER REACHABILITY                  ║\n";
    std::cout << "╚════════════════════════════════════════════════════════════════╝\n";

    struct Commuter { int id; int origin; int dest; };
    std::vector<Commuter> reachable;
    reachable.reserve((size_t)std::min(args.n, (int)nodes.size()));
    std::vector<size_t> unreachable_indices;
    unreachable_indices.reserve(nodes.size());

    // Walk the FPS order; keep only reachables until we hit N.
    int next_commuter_id = 0;
    for (size_t rank = 0; rank < order.size() && (int)reachable.size() < args.n; ++rank) {
        const size_t idx = order[rank];
        const auto& row = nodes[idx];
        std::vector<int> path;
        int dist = query_path(row.node_id, args.dest_node, path);
        if (dist > 0 && !path.empty()) {
            reachable.push_back({next_commuter_id++, row.node_id, args.dest_node});
        } else {
            unreachable_indices.push_back(idx);
            std::cerr << u8"⚠️  Node " << row.node_id
                      << " is unreachable from station " << args.dest_node << "\n";
        }
    }

    // If still short, try the remaining (in case some were skipped due to rank loop ending early, though we used full order)
    // But at this point we've exhausted all candidates in 'order'.
    if ((int)reachable.size() < args.n) {
        std::cerr << "Only " << reachable.size() << " reachable origins found out of "
                  << nodes.size() << " candidates.\n";
        // We still write what we have (or you can `return 6` if you want to hard-require N exactly).
        // Uncomment next line to REQUIRE exactly N reachable commuters:
        // return 6;
    }

    // Write commuters CSV
    std::ofstream fout(args.out_path);
    if (!fout) {
        std::cerr << "Failed to open output path: " << args.out_path << "\n";
        return 7;
    }
    fout << "id,origin_node,destination_node,pickup_earliest,drop_off_latest\n";
    for (const auto& c : reachable) {
        fout << c.id << "," << c.origin << "," << c.dest << ","
             << PICKUP_EARLIEST_DEFAULT << "," << DROP_OFF_LATEST_DEFAULT << "\n";
    }
    fout.close();

    std::cerr << "Wrote commuters CSV with " << reachable.size()
              << " reachable commuters: " << args.out_path << "\n";
    return 0;
}