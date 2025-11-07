#include <iostream>
#include <fstream>
#include <sstream>
#include <vector>
#include <string>
#include <unordered_map>

#include "planner/ortools_solver.h"
#include "planner/hub_label_utils.h"
#include "planner/edge_attrs.h"
#include "planner/av_selection.h"
#include "planner/id_types.h"
#include "planner/av_config.h"
#include "planner/commuter.h"
#include "planner/station.h"
#include "planner/baseline_calculator.h"
#include "planner/comparison_utility.h"
#include "planner/av_metrics.h"

int main(int argc, char* argv[])
{
    if (argc != 7)
    {
        std::cerr << "Usage: " << argv[0] << "\n"
            << "  commuters.csv stations.csv dist_label_prefix speed_table.txt assignments.csv av_routes.csv\n";
        return 1;
    }
    const std::string commuters_csv = argv[1];
    const std::string stations_csv = argv[2];
    const std::string dist_prefix = argv[3];
    const std::string speed_table = argv[4];
    const std::string assignments = argv[5];
    const std::string av_routes_out = argv[6];

    // ═══════════════════════════════════════════════════════════════════════
    // 1. Load inputs
    // ═══════════════════════════════════════════════════════════════════════

    auto commuters = load_commuters(commuters_csv);
    auto stations = load_stations(stations_csv);
    if (stations.empty())
    {
        std::cerr << "No station rows.\n";
        return 2;
    }
    const int station_node = stations.front().node_id;

    if (!init_distance_labels(dist_prefix))
    {
        std::cerr << "Failed to load distance labels: " << dist_prefix << "\n";
        return 3;
    }

    std::unordered_map<EdgeKey, EdgeAttr> edge_tbl = load_edge_attrs(speed_table);
    if (edge_tbl.empty())
    {
        std::cerr << "Failed to load speed table: " << speed_table << "\n";
        return 4;
    }

    auto query_path = [](int s, int t, std::vector<int>& out)-> int
    {
        return distance_mm(static_cast<NodeID>(s), static_cast<NodeID>(t), &out);
    };

    // ═══════════════════════════════════════════════════════════════════════
    // 2. PRE-FILTER: Remove unreachable commuters
    // ═══════════════════════════════════════════════════════════════════════

    std::cout << "\n";
    std::cout << "╔════════════════════════════════════════════════════════════════╗\n";
    std::cout << "║              VALIDATING COMMUTER REACHABILITY                  ║\n";
    std::cout << "╚════════════════════════════════════════════════════════════════╝\n";

    int original_count = commuters.size();
    std::vector<Commuter> reachable_commuters;
    std::vector<int> unreachable_indices;

    for (size_t i = 0; i < commuters.size(); ++i) {
        std::vector<int> path;
        int dist = query_path(commuters[i].origin_node, station_node, path);

        if (dist > 0 && !path.empty()) {
            reachable_commuters.push_back(commuters[i]);
        } else {
            unreachable_indices.push_back(i);
            std::cerr << "⚠️  Commuter " << i << " (node " << commuters[i].origin_node
                      << ") is unreachable from station " << station_node << "\n";
        }
    }

    if (!unreachable_indices.empty()) {
        std::cout << "\n🚫 Filtered out " << unreachable_indices.size()
                  << " unreachable commuter(s)\n";
        std::cout << "✓ Proceeding with " << reachable_commuters.size()
                  << " reachable commuter(s)\n\n";
    } else {
        std::cout << "✓ All " << original_count << " commuters are reachable\n\n";
    }

    // Replace commuters with filtered list
    commuters = reachable_commuters;

    if (commuters.empty()) {
        std::cerr << "❌ No reachable commuters remaining. Exiting.\n";
        return 5;
    }

    // ═══════════════════════════════════════════════════════════════════════
    // 3. Setup vehicles and time windows (using filtered commuters)
    // ═══════════════════════════════════════════════════════════════════════

    std::vector<AVType> types = default_av_types();
    std::vector<OrToolsVehicle> vehicles;
    for (const auto& t : types)
    {
        for (int k = 0; k < t.fleet_size; ++k)
        {
            vehicles.push_back(OrToolsVehicle{t.name, t.capacity, t.max_speed_kmph});
        }
    }
    if (vehicles.empty())
    {
        vehicles.push_back(OrToolsVehicle{"Car", 4, 60.0});
    }

    std::vector<int> commuter_nodes;
    commuter_nodes.reserve(commuters.size());
    for (const auto& c : commuters) commuter_nodes.push_back(c.origin_node);

    std::vector<int64_t> pickup_earliest_ms;
    pickup_earliest_ms.reserve(commuters.size());
    for (const auto& c : commuters)
        pickup_earliest_ms.push_back(c.tw.pickup_earliest_min * 60LL * 1000LL);

    std::vector<int64_t> dropoff_latest_ms;
    dropoff_latest_ms.reserve(commuters.size());
    for (const auto& c : commuters)
        dropoff_latest_ms.push_back(c.tw.drop_off_latest_min * 60LL * 1000LL);

    OrToolsConfig cfg;
    cfg.time_limit_seconds = 30;
    cfg.log_search = false;
    cfg.allow_partial_solution = true;

    // ═══════════════════════════════════════════════════════════════════════
    // 4. CALCULATE BASELINE (only for reachable commuters)
    // ═══════════════════════════════════════════════════════════════════════

    std::cout << "\n";
    std::cout << "╔════════════════════════════════════════════════════════════════╗\n";
    std::cout << "║            CALCULATING PRIVATE VEHICLE BASELINE                ║\n";
    std::cout << "╚════════════════════════════════════════════════════════════════╝\n";

    PrivateVehicleBaseline baseline = calculate_private_vehicle_baseline(
        commuter_nodes,
        station_node,
        query_path,
        edge_tbl,
        original_count  // Pass original count for reporting
    );
    print_baseline_summary(baseline);
    write_baseline_json(baseline, "files/baseline.json");

    // ═══════════════════════════════════════════════════════════════════════
    // 5. RUN AV OPTIMIZATION
    // ═══════════════════════════════════════════════════════════════════════

    std::cout << "\n";
    std::cout << "╔════════════════════════════════════════════════════════════════╗\n";
    std::cout << "║                RUNNING AV OPTIMIZATION                         ║\n";
    std::cout << "╚════════════════════════════════════════════════════════════════╝\n";

    CVRPSolution av_result = solve_cvrp_distance_with_metrics(
        commuter_nodes,
        station_node,
        vehicles,
        query_path,
        edge_tbl,
        pickup_earliest_ms,
        dropoff_latest_ms,
        assignments,
        av_routes_out,
        cfg
    );

    if (!av_result.success)
    {
        std::cerr << "AV optimization failed.\n";
        return 6;
    }

    std::cout << "✓ AV solution written to:\n";
    std::cout << "  - " << assignments << "\n";
    std::cout << "  - " << av_routes_out << "\n";

    // ═══════════════════════════════════════════════════════════════════════
    // 6. PRINT AV METRICS
    // ═══════════════════════════════════════════════════════════════════════

    std::cout << "\n";
    std::cout << "╔════════════════════════════════════════════════════════════════╗\n";
    std::cout << "║                     AV SYSTEM METRICS                          ║\n";
    std::cout << "╚════════════════════════════════════════════════════════════════╝\n";

    print_metrics_summary(av_result.metrics);

    std::string metrics_file = assignments + ".metrics.json";
    write_metrics_json(av_result.metrics, metrics_file);
    std::cout << "✓ AV metrics written to: " << metrics_file << "\n";

    // ═══════════════════════════════════════════════════════════════════════
    // 7. COMPARE AV vs BASELINE
    // ═══════════════════════════════════════════════════════════════════════

    std::cout << "\n";
    std::cout << "╔════════════════════════════════════════════════════════════════╗\n";
    std::cout << "║              COMPARING AV vs BASELINE                          ║\n";
    std::cout << "╚════════════════════════════════════════════════════════════════╝\n";

    ComparisonMetrics comparison = compare_av_vs_baseline(
        "First_Mile_Test",
        baseline,
        av_result.metrics
    );

    print_comparison_summary(comparison);
    write_comparison_json(comparison, "files/comparison.json");

    std::cout << "\n";
    std::cout << "╔════════════════════════════════════════════════════════════════╗\n";
    std::cout << "║                    SIMULATION COMPLETE                         ║\n";
    std::cout << "╚════════════════════════════════════════════════════════════════╝\n";
    std::cout << "\nAll outputs:\n";
    std::cout << "  1. Baseline:    files/baseline.json\n";
    std::cout << "  2. AV Metrics:  " << metrics_file << "\n";
    std::cout << "  3. Comparison:  files/comparison.json\n";
    std::cout << "  4. Routes:      " << av_routes_out << "\n";
    std::cout << "  5. Assignments: " << assignments << "\n";

    // Report filtering summary
    if (original_count != (int)commuters.size()) {
        std::cout << "\n📊 Summary:\n";
        std::cout << "  - Original commuters:   " << original_count << "\n";
        std::cout << "  - Unreachable:          " << (original_count - commuters.size()) << "\n";
        std::cout << "  - Analyzed (reachable): " << commuters.size() << "\n";
    }

    return 0;
}