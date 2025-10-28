#include "ortools_solver.h"
#include <edge_attrs.h>

#include <cmath>
#include <fstream>
#include <sstream>
#include <limits>
#include <iostream>
#include <algorithm>

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
        } // +1h penalty for missing edge
        const double eff_kph = std::min(ea->speed_kph, max_kph_cap);
        const double mps = std::max(0.1, eff_kph) * (1000.0 / 3600.0);
        const auto e_ms = static_cast<long long>(std::ceil((ea->length_m / mps) * 1000.0));
        sum_ms += e_ms;
        if (sum_ms >= std::numeric_limits<int>::max()) return std::numeric_limits<int>::max();
    }
    return static_cast<int>(sum_ms);
}


// Distance-only CVRP (no time windows, no pickup-delivery pairs).
// Minimizes total distance and respects per-vehicle capacity.
// Outputs the same CSVs as your PDPTW solver.
bool solve_cvrp_distance1(
    const std::vector<int>& commuter_nodes,
    int station_node,
    const std::vector<OrToolsVehicle>& vehicles,
    const QueryPathFn& query_path,
    const std::unordered_map<EdgeKey, EdgeAttr>& /*edge_tbl*/, // kept for signature parity
    const std::string& assignments_csv,
    const std::string& av_routes_csv,
    const OrToolsConfig& cfg)
{
    using operations_research::RoutingIndexManager;
    using operations_research::RoutingModel;
    using operations_research::RoutingSearchParameters;
    using operations_research::FirstSolutionStrategy;
    using operations_research::LocalSearchMetaheuristic;

    const int N = static_cast<int>(commuter_nodes.size());
    if (N == 0 || vehicles.empty())
    {
        std::cerr << "[cvrp] nothing to solve (no customers or no vehicles)\n";
        return false;
    }

    // Manager nodes: 0 = depot(station), 1..N = commuters
    const int depot_m = 0;
    const int num_nodes = 1 + N;

    RoutingIndexManager::NodeIndex depot_idx(depot_m);
    std::vector<RoutingIndexManager::NodeIndex> starts(vehicles.size(), depot_idx);
    std::vector<RoutingIndexManager::NodeIndex> ends(vehicles.size(), depot_idx);

    RoutingIndexManager manager(num_nodes,
                                static_cast<int>(vehicles.size()),
                                starts, ends);
    RoutingModel routing(manager);

    // Map manager index -> real graph node id
    auto node_for = [&](int m_index)-> int
    {
        if (m_index == depot_m) return station_node;
        return commuter_nodes[m_index - 1];
    };

    // ---- Distance-based transit (millimeters from your labels) ----
    const int dist_cb_index =
        routing.RegisterTransitCallback([&](int64_t from_index, int64_t to_index)-> int64_t
        {
            const int from_m = manager.IndexToNode(from_index).value();
            const int to_m = manager.IndexToNode(to_index).value();
            const int u = node_for(from_m);
            const int v = node_for(to_m);

            std::vector<int> leg;
            const int d_mm = query_path(u, v, leg);
            // Penalize unreachable with a big number so solver avoids it.
            return (d_mm > 0) ? static_cast<int64_t>(d_mm) : int64_t{1'000'000'000};
        });

    routing.SetArcCostEvaluatorOfAllVehicles(dist_cb_index);

    // ---- Capacity: demand=1 for each customer, 0 for depot ----
    const int demand_cb_index =
        routing.RegisterUnaryTransitCallback([&](int64_t from_index)-> int64_t
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
        /*vehicle caps*/caps,
        /*fix_start_cumul_to_zero*/true,
        "Capacity");


    // ---- Search parameters: Savings + GLS to encourage pooling ----
    RoutingSearchParameters params = operations_research::DefaultRoutingSearchParameters();
    params.set_first_solution_strategy(FirstSolutionStrategy::SAVINGS);
    params.set_local_search_metaheuristic(LocalSearchMetaheuristic::GUIDED_LOCAL_SEARCH);
    params.mutable_time_limit()->set_seconds(cfg.time_limit_seconds);
    params.set_log_search(cfg.log_search);

    const auto* solution = routing.SolveWithParameters(params);
    if (!solution)
    {
        std::cerr << "[cvrp] no solution found.\n";
        return false;
    }

    // ---- Emit outputs (same schema as your PDPTW writer) ----
    std::ofstream aout(assignments_csv);
    aout << "commuter_id,av_type,av_id,cost,station_node,path,shared_with,status\n";

    std::ofstream rvout(av_routes_csv);
    rvout << "av_type,av_id,station_node,pickup_order_commuters,pickup_nodes,route_nodes\n";

    for (int v = 0; v < routing.vehicles(); ++v)
    {
        int64_t idx = routing.Start(v);
        std::vector<int> visit_m; // manager node sequence
        std::vector<int> pickup_nodes_seq; // actual graph node ids for commuters (in visit order)
        std::vector<int> route_nodes; // concatenated polyline (graph node ids)

        while (!routing.IsEnd(idx))
        {
            const int m = manager.IndexToNode(idx).value();
            visit_m.push_back(m);
            int64_t next = solution->Value(routing.NextVar(idx));
            if (routing.IsEnd(next)) visit_m.push_back(depot_m);
            idx = next;
        }

        // Build geometry and collect pickups (ignore depot)
        for (size_t i = 0; i + 1 < visit_m.size(); ++i)
        {
            const int a_m = visit_m[i];
            const int b_m = visit_m[i + 1];
            const int a = node_for(a_m);
            const int b = node_for(b_m);

            if (a_m != depot_m) pickup_nodes_seq.push_back(a);

            std::vector<int> leg;
            (void)query_path(a, b, leg);
            append_leg(route_nodes, leg); // uses your helper
        }

        // Per-vehicle route row
        rvout << vehicles[v].type << "," << v << "," << station_node << ",\""
            << join_ints(pickup_nodes_seq) << "\",\""
            << join_ints(pickup_nodes_seq) << "\",\""
            << join_ints(route_nodes) << "\"\n";

        // Per-commuter assignment rows
        for (int orig_node : pickup_nodes_seq)
        {
            std::vector<int> leg;
            const int dmm = query_path(orig_node, station_node, leg);
            aout << orig_node << "," << vehicles[v].type << "," << v << "," << dmm
                << "," << station_node << ",\"" << join_ints(leg) << "\",\""
                << "" << "\",ASSIGNED\n";
        }
    }

    aout.close();
    rvout.close();
    return true;
}

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
    using operations_research::RoutingIndexManager;
    using operations_research::RoutingModel;
    using operations_research::RoutingSearchParameters;
    using operations_research::FirstSolutionStrategy;
    using operations_research::LocalSearchMetaheuristic;

    const int N = static_cast<int>(commuter_nodes.size());
    if (N == 0 || vehicles.empty())
    {
        std::cerr << "[cvrp] nothing to solve (no customers or no vehicles)\n";
        return false;
    }

    // Manager nodes: 0 = depot(station), 1..N = commuters
    const int depot_m = 0;
    const int num_nodes = 1 + N;

    RoutingIndexManager::NodeIndex depot_idx(depot_m);
    std::vector<RoutingIndexManager::NodeIndex> starts(vehicles.size(), depot_idx);
    std::vector<RoutingIndexManager::NodeIndex> ends(vehicles.size(), depot_idx);

    RoutingIndexManager manager(num_nodes,
                                static_cast<int>(vehicles.size()),
                                starts, ends);
    RoutingModel routing(manager);

    // Map manager index -> real graph node id
    auto node_for = [&](int m_index)-> int
    {
        if (m_index == depot_m) return station_node;
        return commuter_nodes[m_index - 1];
    };

    // ---- Distance-based transit (millimeters from your labels) ----
    const int dist_cb_index =
        routing.RegisterTransitCallback([&](int64_t from_index, int64_t to_index)-> int64_t
        {
            const int from_m = manager.IndexToNode(from_index).value();
            const int to_m = manager.IndexToNode(to_index).value();
            const int u = node_for(from_m);
            const int v = node_for(to_m);

            std::vector<int> leg;
            const int d_mm = query_path(u, v, leg);
            // Penalize unreachable with a big number so solver avoids it.
            return (d_mm > 0) ? static_cast<int64_t>(d_mm) : int64_t{1'000'000'000};
        });

    routing.SetArcCostEvaluatorOfAllVehicles(dist_cb_index);

    // ---- Capacity: demand=1 for each customer, 0 for depot ----
    const int demand_cb_index =
        routing.RegisterUnaryTransitCallback([&](int64_t from_index)-> int64_t
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
        /*vehicle caps*/caps,
        /*fix_start_cumul_to_zero*/true,
        "Capacity");

    // ---- Time dimension with time windows ----

    // Calculate max speed cap across all vehicles
    double max_speed_cap = 0.0;
    for (const auto& veh : vehicles)
    {
        double tcap = (veh.type == "Bike" ? 20.0 : veh.type == "Scooter" ? 30.0 : veh.type == "Moped" ? 45.0 : 60.0);
        max_speed_cap = std::max(max_speed_cap, tcap);
    }

    const int time_cb_index =
        routing.RegisterTransitCallback([&](int64_t from_index, int64_t to_index)-> int64_t
        {
            const int from_m = manager.IndexToNode(from_index).value();
            const int to_m = manager.IndexToNode(to_index).value();
            const int u = node_for(from_m);
            const int v = node_for(to_m);

            std::vector<int> leg;
            query_path(u, v, leg);

            return static_cast<int64_t>(time_ms_along_path(leg, edge_tbl, max_speed_cap));
        });

    const int64_t horizon_ms = 12LL * 60 * 60 * 1000; // 12 hour horizon
    routing.AddDimension(
        time_cb_index,
        /*slack*/0,
        /*capacity*/horizon_ms,
        /*fix_start_cumul_to_zero*/false,
        "Time");

    const auto& time_dim = routing.GetDimensionOrDie("Time");

    // ---- Set time windows for each commuter ----
    // Calculate travel time from each commuter to station for adjusting windows
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

    for (int i = 0; i < N; ++i)
    {
        const int64_t node_idx = manager.NodeToIndex(
            RoutingIndexManager::NodeIndex(i + 1) // commuter nodes are 1..N
        );

        // Earliest pickup time
        int64_t earliest_pickup = 0;
        if (!pickup_earliest_ms.empty() && pickup_earliest_ms.size() == static_cast<size_t>(N))
        {
            earliest_pickup = std::max<int64_t>(0, pickup_earliest_ms[i]);
        }

        // Latest pickup time = latest dropoff at station - travel time to station
        int64_t latest_pickup = horizon_ms;
        if (!dropoff_latest_ms.empty() && dropoff_latest_ms.size() == static_cast<size_t>(N))
        {
            latest_pickup = dropoff_latest_ms[i] - travel_to_station_ms[i];
            latest_pickup = std::max(earliest_pickup, std::min(horizon_ms, latest_pickup));
        }

        std::cerr << "  Commuter " << (i + 1) << " (node=" << commuter_nodes[i] << "): "
            << "pickup window [" << earliest_pickup << ", " << latest_pickup << "] ms, "
            << "travel to station = " << travel_to_station_ms[i] << " ms\n";

        // Set the time window for this commuter node
        time_dim.CumulVar(node_idx)->SetRange(earliest_pickup, latest_pickup);
    }

    // ---- Depot (station) time windows - wide open ----
    for (int v = 0; v < routing.vehicles(); ++v)
    {
        time_dim.CumulVar(routing.Start(v))->SetRange(0, horizon_ms);
        time_dim.CumulVar(routing.End(v))->SetRange(0, horizon_ms);
    }

    // In planner/ortools_solver.cpp
    // Add this after setting time windows, before search parameters

    // In planner/ortools_solver.cpp
    // Replace the entire disjunction section with this:

    // ---- Customer visit requirements ----
    if (cfg.allow_partial_solution)
    {
        // Calculate penalty based on sum of all distances
        int64_t sum_distances = 0;
        for (int i = 0; i < N; ++i)
        {
            std::vector<int> leg;
            int d_mm = query_path(commuter_nodes[i], station_node, leg);
            if (d_mm > 0) sum_distances += d_mm;
        }

        // Penalty = sum of all distances (so skipping one customer costs as much as serving all)
        const int64_t penalty = (sum_distances > 0) ? sum_distances : 10000000000LL;

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
        // DO NOT add any disjunctions - let OR-Tools handle all nodes as required
        // The default VRP behavior without disjunctions is to visit all nodes
    }

    // ---- Search parameters: Savings + GLS to encourage pooling ----
    RoutingSearchParameters params = operations_research::DefaultRoutingSearchParameters();
    params.set_first_solution_strategy(FirstSolutionStrategy::PARALLEL_CHEAPEST_INSERTION);
    params.set_local_search_metaheuristic(LocalSearchMetaheuristic::GUIDED_LOCAL_SEARCH);
    params.mutable_time_limit()->set_seconds(cfg.time_limit_seconds);
    params.set_log_search(cfg.log_search);

    const auto* solution = routing.SolveWithParameters(params);
    if (!solution)
    {
        std::cerr << "[cvrp] no solution found.\n";
        return false;
    }

    std::cerr << "[cvrp] Solution found! Total distance: "
        << solution->ObjectiveValue() << " mm\n";

    // ---- Check which commuters were served ----
    std::vector<bool> served(N, false);
    for (int v = 0; v < routing.vehicles(); ++v)
    {
        int64_t idx = routing.Start(v);
        while (!routing.IsEnd(idx))
        {
            int m = manager.IndexToNode(idx).value();
            if (m >= 1 && m <= N) // It's a commuter node (1..N)
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
            std::cerr << "  ❌ Commuter " << (i + 1) << " (node=" << commuter_nodes[i]
                << ") NOT SERVED - window [" << pickup_earliest_ms[i]
                << ", " << dropoff_latest_ms[i] - travel_to_station_ms[i]
                << "] ms too tight\n";
        }
    }
    std::cerr << "[cvrp] Served: " << served_count << "/" << N
        << ", Unserved: " << unserved_count << "\n";

    // ---- Diagnostic: print per-vehicle loads and times ----
    const auto& cap_dim = routing.GetDimensionOrDie("Capacity");
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

            if (m == 0)
            {
                std::cerr << "  -> DEPOT (load=" << load << ", time=" << time << " ms)\n";
            }
            else
            {
                has_customers = true;
                std::cerr << "  -> C" << m << " (node=" << node_for(m)
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

    // ---- Emit outputs (same schema as before) ----
    std::ofstream aout(assignments_csv);
    aout << "commuter_id,av_type,av_id,cost,station_node,path,shared_with,status\n";

    std::ofstream rvout(av_routes_csv);
    rvout << "av_type,av_id,station_node,pickup_order_commuters,pickup_nodes,route_nodes\n";

    for (int v = 0; v < routing.vehicles(); ++v)
    {
        int64_t idx = routing.Start(v);
        std::vector<int> visit_m; // manager node sequence
        std::vector<int> pickup_nodes_seq; // actual graph node ids for commuters (in visit order)
        std::vector<int> route_nodes; // concatenated polyline (graph node ids)

        while (!routing.IsEnd(idx))
        {
            const int m = manager.IndexToNode(idx).value();
            visit_m.push_back(m);
            int64_t next = solution->Value(routing.NextVar(idx));
            if (routing.IsEnd(next)) visit_m.push_back(depot_m);
            idx = next;
        }

        // Build geometry and collect pickups (ignore depot)
        for (size_t i = 0; i + 1 < visit_m.size(); ++i)
        {
            const int a_m = visit_m[i];
            const int b_m = visit_m[i + 1];
            const int a = node_for(a_m);
            const int b = node_for(b_m);

            if (a_m != depot_m) pickup_nodes_seq.push_back(a);

            std::vector<int> leg;
            (void)query_path(a, b, leg);
            append_leg(route_nodes, leg);
        }

        // Skip empty routes
        if (pickup_nodes_seq.empty()) continue;

        // Per-vehicle route row
        rvout << vehicles[v].type << "," << v << "," << station_node << ",\""
            << join_ints(pickup_nodes_seq) << "\",\""
            << join_ints(pickup_nodes_seq) << "\",\""
            << join_ints(route_nodes) << "\"\n";

        // Per-commuter assignment rows
        for (int orig_node : pickup_nodes_seq)
        {
            std::vector<int> leg;
            const int dmm = query_path(orig_node, station_node, leg);
            aout << orig_node << "," << vehicles[v].type << "," << v << "," << dmm
                << "," << station_node << ",\"" << join_ints(leg) << "\",\""
                << "" << "\",ASSIGNED\n";
        }
    }
    // Add unserved commuters to assignments file
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
    return true;
}

// Backward-compatible wrapper without time windows
bool solve_cvrp_distance(
    const std::vector<int>& commuter_nodes,
    int station_node,
    const std::vector<OrToolsVehicle>& vehicles,
    const QueryPathFn& query_path,
    const std::unordered_map<EdgeKey, EdgeAttr>& edge_tbl,
    const std::string& assignments_csv,
    const std::string& av_routes_csv,
    const OrToolsConfig& cfg)
{
    // Call the full version with empty time windows (no constraints)
    std::vector<int64_t> empty_earliest, empty_latest;
    return solve_cvrp_distance(commuter_nodes, station_node, vehicles,
                               query_path, edge_tbl,
                               empty_earliest, empty_latest,
                               assignments_csv, av_routes_csv, cfg);
}
