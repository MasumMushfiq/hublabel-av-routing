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
#include "planner/config_loader.h"


// Convert to legacy AVType
std::vector<AVType> to_av_types(const std::vector<VehicleConfig>& configs)
{
    std::vector<AVType> av_types;
    for (const auto& vc : configs)
    {
        AVType av;
        av.name = vc.name;
        av.max_speed_kmph = vc.max_speed_kmph;
        av.capacity = vc.capacity;
        av.liters_per_100km = vc.fuel_l_per_100km;
        av.co2_kg_per_liter = vc.co2_kg_per_liter;
        av.fleet_size = vc.fleet_size;
        av_types.push_back(av);
    }
    return av_types;
}

// Convert to OrToolsVehicle instances
std::vector<OrToolsVehicle> to_ortools_vehicles(const std::vector<VehicleConfig>& configs)
{
    std::vector<OrToolsVehicle> vehicles;
    for (const auto& vc : configs)
    {
        for (int i = 0; i < vc.fleet_size; ++i)
        {
            OrToolsVehicle v;
            v.type = vc.name;
            v.capacity = vc.capacity;
            v.max_speed_kmph = vc.max_speed_kmph;
            vehicles.push_back(v);
        }
    }
    return vehicles;
}

// Get fuel parameters from config
FuelParameters get_fuel_parameters_from_config(
    const std::string& vehicle_type,
    const std::vector<VehicleConfig>& configs)
{
    for (const auto& vc : configs)
    {
        if (vc.name == vehicle_type)
        {
            return FuelParameters{
                vc.fuel_l_per_100km,
                vc.co2_kg_per_liter
            };
        }
    }

    // Default fallback
    return FuelParameters{11.1, 2.31};
}

int main(int argc, char* argv[])
{
    if (argc != 11) // NOW 10 ARGUMENTS + PROGRAM NAME = 11
    {
        std::cerr << "Usage: " << argv[0] << "\n"
            << "  commuters.csv stations.csv dist_label_prefix speed_table.txt\n"
            << "  assignments.csv av_routes.csv config.json\n"
            << "  baseline.json metrics.json comparison.json\n";
        return 1;
    }

    const std::string commuters_csv = argv[1];
    const std::string stations_csv = argv[2];
    const std::string dist_prefix = argv[3];
    const std::string speed_table = argv[4];
    const std::string assignments = argv[5];
    const std::string av_routes_out = argv[6];
    const std::string config_file = argv[7];
    const std::string baseline_json = argv[8]; // NEW
    const std::string metrics_json = argv[9]; // NEW
    const std::string comparison_json = argv[10]; // NEW

    // ═══════════════════════════════════════════════════════════════════════
    // 1. Load inputs
    // ═══════════════════════════════════════════════════════════════════════

    // Load configuration
    ExperimentConfig exp_config = load_experiment_config(config_file);

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

    for (size_t i = 0; i < commuters.size(); ++i)
    {
        std::vector<int> path;
        int dist = query_path(commuters[i].origin_node, station_node, path);

        if (dist > 0 && !path.empty())
        {
            reachable_commuters.push_back(commuters[i]);
        }
        else
        {
            unreachable_indices.push_back(i);
            std::cerr << "⚠️  Commuter " << i << " (node " << commuters[i].origin_node
                << ") is unreachable from station " << station_node << "\n";
        }
    }

    if (!unreachable_indices.empty())
    {
        std::cout << "\n🚫 Filtered out " << unreachable_indices.size()
            << " unreachable commuter(s)\n";
        std::cout << "✓ Proceeding with " << reachable_commuters.size()
            << " reachable commuter(s)\n\n";
    }
    else
    {
        std::cout << "✓ All " << original_count << " commuters are reachable\n\n";
    }

    // Replace commuters with filtered list
    commuters = reachable_commuters;

    if (commuters.empty())
    {
        std::cerr << "❌ No reachable commuters remaining. Exiting.\n";
        return 5;
    }

    // std::vector<OrToolsVehicle> vehicles = to_ortools_vehicles(exp_config.vehicle_types);



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

    // Estimate max trips needed
    int max_trips = estimate_max_trips_per_vehicle(
        pickup_earliest_ms,
        dropoff_latest_ms,
        20.0  // Assume 20 min average trip time (adjust based on your scenario)
    );

    // Create multi-trip virtual vehicles
    std::vector<OrToolsVehicle> vehicles = create_multi_trip_vehicles(
        exp_config.vehicle_types,
        max_trips
    );

    OrToolsConfig cfg;
    cfg.time_limit_seconds = exp_config.solver.time_limit_seconds;
    cfg.log_search = exp_config.solver.log_search;
    cfg.allow_partial_solution = exp_config.solver.allow_partial_solution;


std::cout << "\n";
std::cout << "╔════════════════════════════════════════════════════════════════╗\n";
std::cout << "║           VALIDATING TIME WINDOW FEASIBILITY                   ║\n";
std::cout << "╚════════════════════════════════════════════════════════════════╝\n";

// Calculate max vehicle speed
double max_speed_kmph = 0.0;
for (const auto& v : vehicles) {
    max_speed_kmph = std::max(max_speed_kmph, static_cast<double>(v.max_speed_kmph));
}

std::vector<bool> time_feasible(commuters.size(), true);
int time_infeasible_count = 0;

for (size_t i = 0; i < commuters.size(); ++i) {
    std::vector<int> path;
    int dist_mm = query_path(commuters[i].origin_node, station_node, path);

    if (dist_mm <= 0 || path.empty()) {
        // Already filtered out in reachability check, shouldn't happen
        time_feasible[i] = false;
        time_infeasible_count++;
        continue;
    }

    // Calculate travel time (simplified - you can use time_ms_along_path for accuracy)
    double dist_km = dist_mm / 1e6;
    int64_t travel_time_ms = static_cast<int64_t>((dist_km / max_speed_kmph) * 3600.0 * 1000.0);

    // Check if time window is feasible
    int64_t earliest_pickup_ms = commuters[i].tw.pickup_earliest_min * 60LL * 1000LL;
    int64_t latest_dropoff_ms = commuters[i].tw.drop_off_latest_min * 60LL * 1000LL;
    int64_t latest_pickup_ms = latest_dropoff_ms - travel_time_ms;

    if (latest_pickup_ms < earliest_pickup_ms) {
        time_feasible[i] = false;
        time_infeasible_count++;

        std::cerr << "⚠️  Commuter " << i << " (node " << commuters[i].origin_node
                  << ") has INFEASIBLE time window:\n";
        std::cerr << "    Pickup earliest: " << commuters[i].tw.pickup_earliest_min << " min\n";
        std::cerr << "    Dropoff latest:  " << commuters[i].tw.drop_off_latest_min << " min\n";
        std::cerr << "    Travel time:     " << (travel_time_ms / 60000.0) << " min\n";
        std::cerr << "    Window duration: " << ((latest_dropoff_ms - earliest_pickup_ms) / 60000.0) << " min\n";
        std::cerr << "    Shortfall:       " << ((earliest_pickup_ms - latest_pickup_ms) / 60000.0) << " min\n";
    }
}

// Store counts before filtering
int original_count_all = original_count; // This already includes unreachable from earlier
int reachable_before_time_check = commuters.size();

if (time_infeasible_count > 0) {
    std::cout << "\n🚫 Filtered out " << time_infeasible_count
              << " time-infeasible commuter(s)\n";
    std::cout << "✓ Proceeding with " << (commuters.size() - time_infeasible_count)
              << " time-feasible commuter(s)\n\n";

    // Filter in-place (same pattern as reachability check)
    std::vector<Commuter> time_feasible_commuters;
    std::vector<int> time_feasible_nodes;
    std::vector<int64_t> time_feasible_pickup_earliest;
    std::vector<int64_t> time_feasible_dropoff_latest;

    for (size_t i = 0; i < commuters.size(); ++i) {
        if (time_feasible[i]) {
            time_feasible_commuters.push_back(commuters[i]);
            time_feasible_nodes.push_back(commuter_nodes[i]);
            time_feasible_pickup_earliest.push_back(pickup_earliest_ms[i]);
            time_feasible_dropoff_latest.push_back(dropoff_latest_ms[i]);
        }
    }

    // Replace with filtered lists
    commuters = time_feasible_commuters;
    commuter_nodes = time_feasible_nodes;
    pickup_earliest_ms = time_feasible_pickup_earliest;
    dropoff_latest_ms = time_feasible_dropoff_latest;
} else {
    std::cout << "✓ All " << commuters.size()
              << " commuters have feasible time windows\n\n";
}

if (commuters.empty()) {
    std::cerr << "❌ No time-feasible commuters remaining. Exiting.\n";
    return 5;
}

// ═══════════════════════════════════════════════════════════════════════
// 3. CALCULATE BASELINE (only for time-feasible commuters)
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
    original_count_all  // Pass original count (includes unreachable + time-infeasible)
);
print_baseline_summary(baseline);
write_baseline_json(baseline, baseline_json);

    // ═══════════════════════════════════════════════════════════════════════
    // 4. RUN AV OPTIMIZATION (Two-stage on time-feasible commuters)
    // ═══════════════════════════════════════════════════════════════════════

    std::cout << "\n";
    std::cout << "╔════════════════════════════════════════════════════════════════╗\n";
    std::cout << "║                RUNNING AV OPTIMIZATION                         ║\n";
    std::cout << "╚════════════════════════════════════════════════════════════════╝\n";

    // ═══════════════════════════════════════════════════════════════════════
    // STAGE 1: Attempt full coverage on time-feasible commuters
    // ═══════════════════════════════════════════════════════════════════════

    std::cout << "\n[STAGE 1] Attempting full service coverage on "
        << commuters.size() << " time-feasible commuters...\n";

    ExperimentConfig stage1_config = exp_config;
    stage1_config.solver.allow_partial_solution = false;
    stage1_config.solver.time_limit_seconds = 10;

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
        stage1_config
    );

    // ═══════════════════════════════════════════════════════════════════════
    // STAGE 2: If full coverage failed, try partial on time-feasible commuters
    // ═══════════════════════════════════════════════════════════════════════

    if (!av_result.success)
    {
        std::cout << "\n⚠️  Full coverage not found in "
            << stage1_config.solver.time_limit_seconds << "s\n";
        std::cout << "[STAGE 2] Trying partial service on time-feasible commuters...\n";

        ExperimentConfig stage2_config = exp_config;
        stage2_config.solver.allow_partial_solution = true;
        stage2_config.solver.time_limit_seconds = 30;

        av_result = solve_cvrp_distance_with_metrics(
            commuter_nodes,
            station_node,
            vehicles,
            query_path,
            edge_tbl,
            pickup_earliest_ms,
            dropoff_latest_ms,
            assignments,
            av_routes_out,
            stage2_config
        );

        if (av_result.success)
        {
            int served = av_result.metrics.served_commuters;
            int attempted = commuters.size();

            std::cout << "\n✓ Partial solution found:\n";
            std::cout << "  Served: " << served << "/" << attempted
                << " time-feasible commuters\n";
            std::cout << "  Unserved: " << (attempted - served)
                << " (infeasible due to other constraints)\n";
        }
    }
    else
    {
        std::cout << "\n✓ Full coverage achieved! All " << commuters.size()
            << " time-feasible commuters served.\n";
    }

    if (!av_result.success)
    {
        std::cerr << "\n❌ No feasible solution found (even with partial service).\n";
        return 6;
    }

    std::cout << "✓ AV solution written to:\n";
    std::cout << "  - " << assignments << "\n";
    std::cout << "  - " << av_routes_out << "\n";


    // ═══════════════════════════════════════════════════════════════════════
    // 5. PRINT AV METRICS
    // ═══════════════════════════════════════════════════════════════════════

    std::cout << "\n";
    std::cout << "╔════════════════════════════════════════════════════════════════╗\n";
    std::cout << "║                     AV SYSTEM METRICS                          ║\n";
    std::cout << "╚════════════════════════════════════════════════════════════════╝\n";

    print_metrics_summary(av_result.metrics);

    write_metrics_json(av_result.metrics, metrics_json);
    std::cout << "✓ AV metrics written to: " << metrics_json << "\n";

    // ═══════════════════════════════════════════════════════════════════════
    // 6. COMPARE AV vs BASELINE
    // ═══════════════════════════════════════════════════════════════════════

    std::cout << "\n";
    std::cout << "╔════════════════════════════════════════════════════════════════╗\n";
    std::cout << "║              COMPARING AV vs BASELINE                          ║\n";
    std::cout << "╚════════════════════════════════════════════════════════════════╝\n";

    ComparisonMetrics comparison = compare_av_vs_baseline(
        exp_config.experiment_name, // Use experiment name from config
        baseline,
        av_result.metrics
    );

    print_comparison_summary(comparison);
    write_comparison_json(comparison, comparison_json);

    std::cout << "\n";
    std::cout << "╔════════════════════════════════════════════════════════════════╗\n";
    std::cout << "║                    SIMULATION COMPLETE                         ║\n";
    std::cout << "╚════════════════════════════════════════════════════════════════╝\n";
    std::cout << "\nAll outputs:\n";
    std::cout << "  1. Baseline:    " << baseline_json << "\n";
    std::cout << "  2. AV Metrics:  " << metrics_json << "\n";
    std::cout << "  3. Comparison:  " << comparison_json << "\n";
    std::cout << "  4. Routes:      " << av_routes_out << "\n";
    std::cout << "  5. Assignments: " << assignments << "\n";

    // Report filtering summary
    std::cout << "\n";
    std::cout << "╔════════════════════════════════════════════════════════════════╗\n";
    std::cout << "║                    SIMULATION COMPLETE                         ║\n";
    std::cout << "╚════════════════════════════════════════════════════════════════╝\n";
    std::cout << "\nAll outputs:\n";
    std::cout << "  1. Baseline:    " << baseline_json << "\n";
    std::cout << "  2. AV Metrics:  " << metrics_json << "\n";
    std::cout << "  3. Comparison:  " << comparison_json << "\n";
    std::cout << "  4. Routes:      " << av_routes_out << "\n";
    std::cout << "  5. Assignments: " << assignments << "\n";

    // Report filtering summary
    int unreachable_count = original_count_all - reachable_before_time_check;
    int total_filtered = unreachable_count + time_infeasible_count;

    if (total_filtered > 0) {
        std::cout << "\n📊 Filtering Summary:\n";
        std::cout << "  - Original commuters:      " << original_count_all << "\n";
        std::cout << "  - Unreachable:             " << unreachable_count << "\n";
        std::cout << "  - Time-infeasible:         " << time_infeasible_count << "\n";
        std::cout << "  - Analyzed (feasible):     " << commuters.size() << "\n";
    }


    return 0;
}
