#include "ortools_solver.h"
#include "av_metrics.h"
#include <edge_attrs.h>

#include <cmath>
#include <fstream>
#include <sstream>
#include <limits>
#include <iostream>
#include <algorithm>
#include <map>

using operations_research::RoutingIndexManager;
using operations_research::RoutingModel;
using operations_research::RoutingSearchParameters;
using operations_research::FirstSolutionStrategy;

// ─────────────────────────────────────────────────────────────────────────────
// small utils
static std::string join_ints(const std::vector<int>& v)
{
    std::ostringstream oss;
    for (size_t i = 0; i < v.size(); ++i)
    {
        if (i) oss << ' ';
        oss << v[i];
    }
    return oss.str();
}

static inline const EdgeAttr* find_edge_attr(
    int u, int v, const std::unordered_map<EdgeKey, EdgeAttr>& tbl)
{
    auto it = tbl.find(edge_key(u, v));
    return (it == tbl.end()) ? nullptr : &it->second;
}

// Concatenate, de-dup shared endpoint.
static void append_leg(std::vector<int>& route, const std::vector<int>& leg)
{
    if (leg.empty()) return;
    if (route.empty())
    {
        route = leg;
        return;
    }
    if (route.back() == leg.front()) route.insert(route.end(), leg.begin() + 1, leg.end());
    else route.insert(route.end(), leg.begin(), leg.end());
}

// Compute time(ms) for a path by summing per-edge length/speed with AV cap.
static int time_ms_along_path(const std::vector<int>& path,
                              const std::unordered_map<EdgeKey, EdgeAttr>& edge_tbl,
                              double max_kph_cap)
{
    if (path.size() < 2) return 0;
    long long sum_ms = 0;
    for (size_t i = 1; i < path.size(); ++i)
    {
        const int u = path[i - 1], v = path[i];
        const EdgeAttr* ea = find_edge_attr(u, v, edge_tbl);
        if (!ea)
        {
            sum_ms += 3'600'000;
            continue;
        }
        const double eff_kph = std::min(ea->speed_kph, max_kph_cap);
        const double mps = std::max(0.1, eff_kph) * (1000.0 / 3600.0);
        const auto e_ms = static_cast<long long>(std::ceil((ea->length_m / mps) * 1000.0));
        sum_ms += e_ms;
        if (sum_ms >= std::numeric_limits<int>::max()) return std::numeric_limits<int>::max();
    }
    return static_cast<int>(sum_ms);
}

// VEHICLE-TYPE PENALTY FUNCTION
static double calculate_vehicle_distance_penalty(
    const std::string& vehicle_type,
    double distance_km)
{
    if (vehicle_type == "Scooter") {
        if (distance_km > 5.0)       return 50.0;
        else if (distance_km > 3.0)  return 20.0;
        else if (distance_km > 2.0)  return 5.0;
        else if (distance_km > 1.0)  return 1.5;
        return 1.0;
    }
    else if (vehicle_type == "Moped") {
        if (distance_km > 12.0)      return 30.0;
        else if (distance_km > 8.0)  return 15.0;
        else if (distance_km > 6.0)  return 5.0;
        else if (distance_km < 0.5)  return 3.0;
        return 1.0;
    }
    else if (vehicle_type == "Car") {
        if (distance_km > 20.0)      return 10.0;
        else if (distance_km < 0.5)  return 3.0;
        else if (distance_km < 1.5)  return 1.5;
        return 1.0;
    }
    else if (vehicle_type == "Bus") {
        // VERY HEAVY penalties for buses on short trips
        if (distance_km < 3.0)       return 100.0;
        else if (distance_km < 5.0)  return 50.0;
        else if (distance_km < 7.0)  return 20.0;
        else if (distance_km < 9.0)  return 10.0;
        return 1.0;
    }

    return 1.0;
}

// ═══════════════════════════════════════════════════════════════════════════
// HELPER FUNCTIONS FOR MODULARIZATION
// ═══════════════════════════════════════════════════════════════════════════

// Setup vehicle-specific arc costs
static void setup_vehicle_costs(
    RoutingModel& routing,
    RoutingIndexManager& manager,
    const std::vector<OrToolsVehicle>& vehicles,
    const QueryPathFn& query_path,
    int station_node,
    const std::vector<int>& commuter_nodes,
    int depot_m)
{
    std::cerr << "[cvrp] Setting up vehicle-type-specific arc costs...\n";

    for (int v = 0; v < routing.vehicles(); ++v)
    {
        const std::string veh_type = vehicles[v].type; // COPY, not reference

        const int veh_cb = routing.RegisterTransitCallback(
            [&query_path, &manager, station_node, &commuter_nodes, depot_m, veh_type]
            (int64_t from_index, int64_t to_index) -> int64_t
            {
                const int from_m = manager.IndexToNode(from_index).value();
                const int to_m = manager.IndexToNode(to_index).value();

                // Map manager index to real node
                const int u = (from_m == depot_m) ? station_node : commuter_nodes[from_m - 1];
                const int v_node = (to_m == depot_m) ? station_node : commuter_nodes[to_m - 1];

                std::vector<int> leg;
                const int d_mm = query_path(u, v_node, leg);

                if (d_mm <= 0) return int64_t{1'000'000'000};

                double d_km = d_mm / 1e6;
                double penalty = calculate_vehicle_distance_penalty(veh_type, d_km);

                return static_cast<int64_t>(d_mm * penalty);
            }
        );

        routing.SetArcCostEvaluatorOfVehicle(veh_cb, v);
    }

    // Set fixed costs
    for (int v = 0; v < routing.vehicles(); ++v)
    {
        int64_t fixed_cost = 0;

        if (vehicles[v].type == "Bus")
            fixed_cost = 1000000;
        else if (vehicles[v].type == "Car")
            fixed_cost = 500000;
        else if (vehicles[v].type == "Moped")
            fixed_cost = 200000;
        else if (vehicles[v].type == "Scooter")
            fixed_cost = 100000;

        routing.SetFixedCostOfVehicle(fixed_cost, v);
    }

    std::cerr << "[cvrp] ✓ Vehicle-specific costs applied\n";
}

// Add capacity dimension
static void add_capacity_dimension(
    RoutingModel& routing,
    RoutingIndexManager& manager,
    const std::vector<OrToolsVehicle>& vehicles,
    int depot_m)
{
    const int demand_cb_index =
        routing.RegisterUnaryTransitCallback(
            [&manager, depot_m](int64_t from_index) -> int64_t
            {
                const int m = manager.IndexToNode(from_index).value();
                return (m == depot_m) ? int64_t{0} : int64_t{1};
            });

    std::vector<int64_t> caps;
    caps.reserve(vehicles.size());
    for (const auto& v : vehicles) caps.push_back(std::max(1, v.capacity));

    routing.AddDimensionWithVehicleCapacity(
        demand_cb_index,
        /*slack*/0,
        caps,
        /*fix_start_cumul_to_zero*/true,
        "Capacity");
}

// Add time dimension
static void add_time_dimension(
    RoutingModel& routing,
    RoutingIndexManager& manager,
    const QueryPathFn& query_path,
    const std::unordered_map<EdgeKey, EdgeAttr>& edge_tbl,
    const std::vector<OrToolsVehicle>& vehicles,
    int station_node,
    const std::vector<int>& commuter_nodes,
    int depot_m)
{
    // Calculate max speed cap
    double max_speed_cap = 0.0;
    for (const auto& veh : vehicles)
    {
        double tcap = veh.max_speed_kmph;
        max_speed_cap = std::max(max_speed_cap, tcap);
    }

    const int time_cb_index =
        routing.RegisterTransitCallback(
            [&query_path, &manager, &edge_tbl, station_node, &commuter_nodes, depot_m, max_speed_cap]
            (int64_t from_index, int64_t to_index) -> int64_t
            {
                const int from_m = manager.IndexToNode(from_index).value();
                const int to_m = manager.IndexToNode(to_index).value();

                const int u = (from_m == depot_m) ? station_node : commuter_nodes[from_m - 1];
                const int v = (to_m == depot_m) ? station_node : commuter_nodes[to_m - 1];

                std::vector<int> leg;
                query_path(u, v, leg);

                return static_cast<int64_t>(time_ms_along_path(leg, edge_tbl, max_speed_cap));
            });

    const int64_t horizon_ms = 12LL * 60 * 60 * 1000;
    routing.AddDimension(
        time_cb_index,
        /*slack*/0,
        /*capacity*/horizon_ms,
        /*fix_start_cumul_to_zero*/false,
        "Time");
}

// Set time windows for commuters
static std::vector<int64_t> setup_time_windows(
    RoutingModel& routing,
    RoutingIndexManager& manager,
    const QueryPathFn& query_path,
    const std::unordered_map<EdgeKey, EdgeAttr>& edge_tbl,
    const std::vector<OrToolsVehicle>& vehicles,
    int station_node,
    const std::vector<int>& commuter_nodes,
    const std::vector<int64_t>& pickup_earliest_ms,
    const std::vector<int64_t>& dropoff_latest_ms)
{
    const int N = static_cast<int>(commuter_nodes.size());
    const auto& time_dim = routing.GetDimensionOrDie("Time");

    // Calculate max speed cap
    double max_speed_cap = 0.0;
    for (const auto& veh : vehicles)
    {
        double tcap = veh.max_speed_kmph;
        max_speed_cap = std::max(max_speed_cap, tcap);
    }

    // Calculate travel times to station
    std::vector<int64_t> travel_to_station_ms(N, 0);
    for (int i = 0; i < N; ++i)
    {
        std::vector<int> leg;
        query_path(commuter_nodes[i], station_node, leg);
        travel_to_station_ms[i] = static_cast<int64_t>(
            time_ms_along_path(leg, edge_tbl, max_speed_cap)
        );
    }

    std::cerr << "[cvrp] Setting time windows for " << N << " commuters:\n";

    const int64_t horizon_ms = 12LL * 60 * 60 * 1000;

    for (int i = 0; i < N; ++i)
    {
        const int64_t node_idx = manager.NodeToIndex(
            RoutingIndexManager::NodeIndex(i + 1)
        );

        int64_t earliest_pickup = 0;
        if (!pickup_earliest_ms.empty() && pickup_earliest_ms.size() == static_cast<size_t>(N))
        {
            earliest_pickup = std::max<int64_t>(0, pickup_earliest_ms[i]);
        }

        int64_t latest_pickup = horizon_ms;
        if (!dropoff_latest_ms.empty() && dropoff_latest_ms.size() == static_cast<size_t>(N))
        {
            latest_pickup = dropoff_latest_ms[i] - travel_to_station_ms[i];
            latest_pickup = std::max(earliest_pickup, std::min(horizon_ms, latest_pickup));
        }

        std::cerr << "  Commuter " << (i + 1) << " (node=" << commuter_nodes[i] << "): "
            << "pickup window [" << earliest_pickup << ", " << latest_pickup << "] ms, "
            << "travel to station = " << travel_to_station_ms[i] << " ms\n";

        time_dim.CumulVar(node_idx)->SetRange(earliest_pickup, latest_pickup);
    }

    // Set depot time windows
    for (int v = 0; v < routing.vehicles(); ++v)
    {
        time_dim.CumulVar(routing.Start(v))->SetRange(0, horizon_ms);
        time_dim.CumulVar(routing.End(v))->SetRange(0, horizon_ms);
    }

    return travel_to_station_ms;
}

int64_t compute_disjunction_penalty(
    const std::vector<int>& commuter_nodes,
    int station_node,
    const QueryPathFn& query_path)
{
    int64_t sum_distances = 0;
    for (size_t i = 0; i < commuter_nodes.size(); ++i)
    {
        std::vector<int> leg;
        int d_mm = query_path(commuter_nodes[i], station_node, leg);
        if (d_mm > 0) sum_distances += d_mm;
    }

    return (sum_distances > 0) ? sum_distances : 10000000000LL;
}


// Add disjunctions for partial solutions
static void add_disjunctions(
    RoutingModel& routing,
    RoutingIndexManager& manager,
    const QueryPathFn& query_path,
    int station_node,
    const std::vector<int>& commuter_nodes,
    const OrToolsConfig& cfg)
{
    const int N = static_cast<int>(commuter_nodes.size());

    if (cfg.allow_partial_solution)
    {
        int64_t sum_distances = 0;
        for (int i = 0; i < N; ++i)
        {
            std::vector<int> leg;
            int d_mm = query_path(commuter_nodes[i], station_node, leg);
            if (d_mm > 0) sum_distances += d_mm;
        }

        const int64_t penalty = compute_disjunction_penalty(
            commuter_nodes, station_node, query_path
        );

        std::cerr << "[cvrp] PARTIAL SOLUTIONS ENABLED - customers optional with penalty="
            << penalty << " mm\n";

        for (int i = 0; i < N; ++i)
        {
            const int64_t node_idx = manager.NodeToIndex(
                RoutingIndexManager::NodeIndex(i + 1)
            );
            routing.AddDisjunction({node_idx}, penalty);
        }
    }
    else
    {
        std::cerr << "[cvrp] PARTIAL SOLUTIONS DISABLED - all customers MANDATORY\n";
    }
}

// Analyze which commuters were served
static std::vector<bool> analyze_service_coverage(
    const RoutingModel& routing,
    const operations_research::Assignment* solution,
    RoutingIndexManager& manager,
    int N)
{
    std::vector<bool> served(N, false);

    for (int v = 0; v < routing.vehicles(); ++v)
    {
        int64_t idx = routing.Start(v);
        while (!routing.IsEnd(idx))
        {
            int m = manager.IndexToNode(idx).value();
            if (m >= 1 && m <= N)
            {
                served[m - 1] = true;
            }
            idx = solution->Value(routing.NextVar(idx));
        }
    }

    int served_count = 0;
    int unserved_count = 0;
    std::cerr << "[cvrp] Service report:\n";
    for (int i = 0; i < N; ++i)
    {
        if (served[i])
        {
            served_count++;
        }
        else
        {
            unserved_count++;
            std::cerr << "  ❌ Commuter " << (i + 1) << " NOT SERVED\n";
        }
    }
    std::cerr << "[cvrp] Served: " << served_count << "/" << N
        << ", Unserved: " << unserved_count << "\n";

    return served;
}

// Print vehicle type usage diagnostics
static void print_vehicle_usage(
    const RoutingModel& routing,
    const operations_research::Assignment* solution,
    RoutingIndexManager& manager,
    const std::vector<OrToolsVehicle>& vehicles,
    int N)
{
    std::map<std::string, int> vehicle_type_usage;
    std::map<std::string, int> vehicle_type_passengers;

    for (int v = 0; v < routing.vehicles(); ++v)
    {
        int64_t idx = routing.Start(v);
        int pax_count = 0;

        while (!routing.IsEnd(idx))
        {
            int m = manager.IndexToNode(idx).value();
            if (m >= 1 && m <= N) pax_count++;
            idx = solution->Value(routing.NextVar(idx));
        }

        if (pax_count > 0)
        {
            vehicle_type_usage[vehicles[v].type]++;
            vehicle_type_passengers[vehicles[v].type] += pax_count;
        }
    }

    std::cerr << "\n[cvrp] Vehicle Type Usage:\n";
    for (const auto& [type, count] : vehicle_type_usage)
    {
        int pax = vehicle_type_passengers[type];
        std::cerr << "  " << type << ": " << count << " vehicles used, "
                  << pax << " passengers carried (avg: "
                  << (double)pax / count << " per vehicle)\n";
    }
}

// Print detailed route diagnostics
static void print_route_diagnostics(
    const RoutingModel& routing,
    const operations_research::Assignment* solution,
    RoutingIndexManager& manager,
    const std::vector<OrToolsVehicle>& vehicles,
    int station_node,
    const std::vector<int>& commuter_nodes,
    int depot_m)
{
    const auto& cap_dim = routing.GetDimensionOrDie("Capacity");
    const auto& time_dim = routing.GetDimensionOrDie("Time");

    for (int v = 0; v < routing.vehicles(); ++v)
    {
        std::cerr << "[diag] Vehicle " << v << " (" << vehicles[v].type
            << ", cap=" << vehicles[v].capacity << ") route:\n";
        int64_t idx = routing.Start(v);
        bool has_customers = false;

        while (!routing.IsEnd(idx))
        {
            int m = manager.IndexToNode(idx).value();
            int64_t load = solution->Value(cap_dim.CumulVar(idx));
            int64_t time = solution->Value(time_dim.CumulVar(idx));

            if (m == depot_m)
            {
                std::cerr << "  -> DEPOT (load=" << load << ", time=" << time << " ms)\n";
            }
            else
            {
                has_customers = true;
                int node_id = commuter_nodes[m - 1];
                std::cerr << "  -> C" << m << " (node=" << node_id
                    << ", load=" << load << ", time=" << time << " ms)\n";
            }
            idx = solution->Value(routing.NextVar(idx));
        }

        int64_t end_load = solution->Value(cap_dim.CumulVar(routing.End(v)));
        int64_t end_time = solution->Value(time_dim.CumulVar(routing.End(v)));
        std::cerr << "  -> DEPOT (load=" << end_load << ", time=" << end_time
            << " ms) [END]\n";

        if (!has_customers)
        {
            std::cerr << "  (empty route - vehicle not used)\n";
        }
    }
}

// Write output CSV files
static void write_output_files(
    const RoutingModel& routing,
    const operations_research::Assignment* solution,
    RoutingIndexManager& manager,
    const std::vector<OrToolsVehicle>& vehicles,
    const QueryPathFn& query_path,
    int station_node,
    const std::vector<int>& commuter_nodes,
    const std::vector<bool>& served,
    const std::string& assignments_csv,
    const std::string& av_routes_csv,
    int depot_m)
{
    const int N = static_cast<int>(commuter_nodes.size());

    std::ofstream aout(assignments_csv);
    aout << "commuter_id,av_type,av_id,cost,station_node,path,shared_with,status\n";

    std::ofstream rvout(av_routes_csv);
    rvout << "av_type,av_id,station_node,pickup_order_commuters,pickup_nodes,route_nodes\n";

    for (int v = 0; v < routing.vehicles(); ++v)
    {
        int64_t idx = routing.Start(v);
        std::vector<int> visit_m;
        std::vector<int> pickup_nodes_seq;
        std::vector<int> route_nodes;

        while (!routing.IsEnd(idx))
        {
            const int m = manager.IndexToNode(idx).value();
            visit_m.push_back(m);
            int64_t next = solution->Value(routing.NextVar(idx));
            if (routing.IsEnd(next)) visit_m.push_back(depot_m);
            idx = next;
        }

        for (size_t i = 0; i + 1 < visit_m.size(); ++i)
        {
            const int a_m = visit_m[i];
            const int b_m = visit_m[i + 1];
            const int a = (a_m == depot_m) ? station_node : commuter_nodes[a_m - 1];
            const int b = (b_m == depot_m) ? station_node : commuter_nodes[b_m - 1];

            if (a_m != depot_m) pickup_nodes_seq.push_back(a);

            std::vector<int> leg;
            (void)query_path(a, b, leg);
            append_leg(route_nodes, leg);
        }

        if (pickup_nodes_seq.empty()) continue;

        rvout << vehicles[v].type << "," << v << "," << station_node << ",\""
            << join_ints(pickup_nodes_seq) << "\",\""
            << join_ints(pickup_nodes_seq) << "\",\""
            << join_ints(route_nodes) << "\"\n";

        for (int orig_node : pickup_nodes_seq)
        {
            std::vector<int> leg;
            const int dmm = query_path(orig_node, station_node, leg);
            aout << orig_node << "," << vehicles[v].type << "," << v << "," << dmm
                << "," << station_node << ",\"" << join_ints(leg) << "\",\""
                << "" << "\",ASSIGNED\n";
        }
    }

    // Add unserved commuters
    for (int i = 0; i < N; ++i)
    {
        if (!served[i])
        {
            aout << commuter_nodes[i] << ",,,," << station_node
                << ",\"\",\"\",UNSERVED\n";
        }
    }

    aout.close();
    rvout.close();
}

// ═══════════════════════════════════════════════════════════════════════════
// MAIN FUNCTION: CVRP with Time Windows (MODULARIZED - FIXED)
// ═══════════════════════════════════════════════════════════════════════════

CVRPSolution solve_cvrp_distance_with_metrics(
    const std::vector<int>& commuter_nodes,
    int station_node,
    const std::vector<OrToolsVehicle>& vehicles,
    const QueryPathFn& query_path,
    const std::unordered_map<EdgeKey, EdgeAttr>& edge_tbl,
    const std::vector<int64_t>& pickup_earliest_ms,
    const std::vector<int64_t>& dropoff_latest_ms,
    const std::string& assignments_csv,
    const std::string& av_routes_csv,
    const OrToolsConfig& cfg)
{
    using operations_research::LocalSearchMetaheuristic;

    CVRPSolution result;
    result.success = false;
    result.solution = nullptr;
    result.routing = nullptr;
    result.manager = nullptr;

    const int N = static_cast<int>(commuter_nodes.size());
    if (N == 0 || vehicles.empty())
    {
        std::cerr << "[cvrp] nothing to solve (no customers or no vehicles)\n";
        return result;
    }

    // ═══════════════════════════════════════════════════════════════════════
    // 1. Initialize routing model
    // ═══════════════════════════════════════════════════════════════════════

    const int depot_m = 0;
    const int num_nodes = 1 + N;

    RoutingIndexManager::NodeIndex depot_idx(depot_m);
    std::vector<RoutingIndexManager::NodeIndex> starts(vehicles.size(), depot_idx);
    std::vector<RoutingIndexManager::NodeIndex> ends(vehicles.size(), depot_idx);

    RoutingIndexManager manager(num_nodes,
                                static_cast<int>(vehicles.size()),
                                starts, ends);
    RoutingModel routing(manager);

    // ═══════════════════════════════════════════════════════════════════════
    // 2. Setup model components
    // ═══════════════════════════════════════════════════════════════════════

    setup_vehicle_costs(routing, manager, vehicles, query_path, station_node, commuter_nodes, depot_m);
    add_capacity_dimension(routing, manager, vehicles, depot_m);
    add_time_dimension(routing, manager, query_path, edge_tbl, vehicles, station_node, commuter_nodes, depot_m);

    std::vector<int64_t> travel_to_station_ms = setup_time_windows(
        routing, manager, query_path, edge_tbl, vehicles,
        station_node, commuter_nodes, pickup_earliest_ms, dropoff_latest_ms
    );

    add_disjunctions(routing, manager, query_path, station_node, commuter_nodes, cfg);

    // ═══════════════════════════════════════════════════════════════════════
    // 3. Solve
    // ═══════════════════════════════════════════════════════════════════════

    RoutingSearchParameters params = operations_research::DefaultRoutingSearchParameters();
    params.set_first_solution_strategy(FirstSolutionStrategy::PARALLEL_CHEAPEST_INSERTION);
    params.set_local_search_metaheuristic(LocalSearchMetaheuristic::GUIDED_LOCAL_SEARCH);
    params.mutable_time_limit()->set_seconds(cfg.time_limit_seconds);
    params.set_log_search(cfg.log_search);

    const auto* solution = routing.SolveWithParameters(params);
    if (!solution)
    {
        std::cerr << "[cvrp] no solution found.\n";
        return result;
    }

    std::cerr << "[cvrp] Solution found! Total distance: "
          << solution->ObjectiveValue() << " mm\n";

    // ═══════════════════════════════════════════════════════════════════════
    // 4. Analyze and report results
    // ═══════════════════════════════════════════════════════════════════════

    print_vehicle_usage(routing, solution, manager, vehicles, N);
    std::vector<bool> served = analyze_service_coverage(routing, solution, manager, N);
    print_route_diagnostics(routing, solution, manager, vehicles, station_node, commuter_nodes, depot_m);

    // ═══════════════════════════════════════════════════════════════════════
    // 5. Calculate metrics (return to caller, don't write here)
    // ═══════════════════════════════════════════════════════════════════════

    result.metrics = calculate_av_metrics(
        commuter_nodes, station_node, vehicles,
        query_path, edge_tbl, routing, solution, manager, pickup_earliest_ms
    );

    // ═══════════════════════════════════════════════════════════════════════
    // 6. Write output files
    // ═══════════════════════════════════════════════════════════════════════

    write_output_files(
        routing, solution, manager, vehicles, query_path,
        station_node, commuter_nodes, served, assignments_csv, av_routes_csv, depot_m
    );

    result.success = true;
    result.solution = solution;
    result.routing = &routing;
    result.manager = &manager;

    return result;
}

// Backward-compatible wrapper - writes metrics internally
bool solve_cvrp_distance(
    const std::vector<int>& commuter_nodes,
    int station_node,
    const std::vector<OrToolsVehicle>& vehicles,
    const QueryPathFn& query_path,
    const std::unordered_map<EdgeKey, EdgeAttr>& edge_tbl,
    const std::vector<int64_t>& pickup_earliest_ms,
    const std::vector<int64_t>& dropoff_latest_ms,
    const std::string& assignments_csv,
    const std::string& av_routes_csv,
    const OrToolsConfig& cfg)
{
    auto result = solve_cvrp_distance_with_metrics(
        commuter_nodes, station_node, vehicles, query_path, edge_tbl,
        pickup_earliest_ms, dropoff_latest_ms, assignments_csv, av_routes_csv, cfg
    );

    if (result.success)
    {
        // Write metrics for backward compatibility
        std::string metrics_file = assignments_csv + ".metrics.json";
        write_metrics_json(result.metrics, metrics_file);
        print_metrics_summary(result.metrics);
        std::cerr << "[cvrp] Metrics written to: " << metrics_file << "\n";
    }

    return result.success;
}