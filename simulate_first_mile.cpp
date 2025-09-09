//
// simulate_first_mile.cpp
// First-mile greedy baseline (nearest station + shared AV with capacity)
//

#include "planner/commuter.h"
#include "planner/station.h"
#include "planner/hub_label_utils.h"
#include "planner/av_config.h"
#include "planner/baseline_greedy_assignment.h"
#include "planner/id_types.h"
#include "planner/edge_attrs.h"
#include "planner/time_cost.h"
#include <iostream>
#include <vector>
#include <fstream>
#include <string>

// Hub-label project types
// #include "../src/graph.h"     // NodeID
// #include "../src/labels.h"


int main(int argc, char* argv[]) {
    // New arg list: commuters.csv stations.csv dist_prefix time_prefix output_assignment.csv
    if (argc != 6) {
        std::cerr << "Usage: " << argv[0]
                  << " commuters.csv stations.csv dist_prefix time_prefix output_assignment.csv\n"
                  << "  Example:\n"
                  << "    " << argv[0] << " files/commuters.csv files/stations.csv"
                  << " files/melton_dist files/melton_time files/assignments.csv\n";
        return 1;
    }

    const std::string commuters_file = argv[1];
    const std::string stations_file  = argv[2];
    const std::string dist_prefix    = argv[3];   // e.g., "files/melton_dist"  -> .dorder/.dlabel (distance in mm)
    const std::string time_prefix    = argv[4];   // e.g., "files/melton_time"  -> .dorder/.dlabel (time in ms)
    const std::string output_file    = argv[5];

    const std::string edge_dist_speed = "dataset/MELTON/melton_graph_speed.txt";

    // 1) Load domain inputs
    std::vector<Commuter> commuters = load_commuters(commuters_file);
    std::vector<Station>  stations  = load_stations(stations_file);

    if (commuters.empty()) {
        std::cerr << "Error: no commuters loaded from " << commuters_file << "\n";
        return 2;
    }
    if (stations.empty()) {
        std::cerr << "Error: no stations loaded from " << stations_file << "\n";
        return 3;
    }

    const auto edge_tbl = load_edge_attrs(edge_dist_speed);
    if (edge_tbl.empty())
    {
        std::cerr << "Error: no edge table loaded from " << edge_dist_speed << "\n";
        return 4;
    }

    std::cout << "Loaded " << commuters.size() << " commuters and "
              << stations.size() << " stations.\n";

    // 2) Load BOTH label packs (distance & time)
    if (!init_labels(dist_prefix, time_prefix)) {
        std::cerr << "Error: failed to load one or both label packs.\n"
                  << "  dist_prefix=" << dist_prefix << "\n"
                  << "  time_prefix=" << time_prefix << "\n";
        return 4;
    }

    // 3) Fleet configuration (unchanged)
    auto av_types = default_av_types();

    // 4) Query function expected by your baseline:
    //    signature: int(int s, int t, std::vector<int>& out_path)
    //    We use TIME (ms) as the cost metric and fill the path.
    auto query_path_time = [](int s, int t, std::vector<int>& out_path) -> int {
        // NOTE: time_ms returns milliseconds; baseline expects an int cost.
        return time_ms(static_cast<NodeID>(s), static_cast<NodeID>(t), &out_path);
    };

    // If you still want to compare/inspect distance occasionally:
    auto query_path_dist = [](int s, int t, std::vector<int>& out_path) -> int {
        return distance_mm(static_cast<NodeID>(s), static_cast<NodeID>(t), &out_path);
    };

    // 5) Run the (existing) greedy baseline but now with TIME as the cost.
    //    If you're pausing greedy for now, comment this block out.
    run_greedy_baseline_assignment(
        commuters,
        stations,
        query_path_dist,            // <<--- TIME-based cost
        av_types,
        output_file,                // assignments CSV
        "files/av_routes.csv"       // vehicle routes CSV
        , edge_tbl                  // edge attributes (for speed, etc.)
    );

    std::cout << "Baseline complete. Output: " << output_file << "\n";
    return 0;
}