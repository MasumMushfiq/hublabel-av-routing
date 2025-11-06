// planner/av_metrics.cpp
#include "av_metrics.h"
#include "ortools_solver.h"
#include "time_cost.h"
#include "ortools/constraint_solver/routing.h"
#include "ortools/constraint_solver/routing_index_manager.h"
#include <fstream>
#include <iostream>
#include <algorithm>
#include <iomanip>
#include <unordered_map>

AVServiceMetrics calculate_av_metrics(
    const std::vector<int>& commuter_nodes,
    int station_node,
    const std::vector<OrToolsVehicle>& vehicles,
    const QueryPathFn& query_path,
    const std::unordered_map<EdgeKey, EdgeAttr>& edge_tbl,
    const operations_research::RoutingModel& routing,
    const operations_research::Assignment* solution,
    const operations_research::RoutingIndexManager& manager,
    const std::vector<int64_t>& pickup_earliest_ms)
{
    AVServiceMetrics m;
    const int N = static_cast<int>(commuter_nodes.size());
    m.total_commuters = N;

    // Helper: manager index -> graph node ID
    auto node_for = [&](int m_index) -> int {
        if (m_index == 0) return station_node;
        return commuter_nodes[m_index - 1];
    };

    // Build lookup: graph node -> commuter index (for O(1) lookups)
    std::unordered_map<int, int> node_to_commuter_idx;
    for (int i = 0; i < N; ++i) {
        node_to_commuter_idx[commuter_nodes[i]] = i;
    }

    const auto& time_dim = routing.GetDimensionOrDie("Time");

    // Track which commuters are served
    std::vector<bool> served(N, false);

    // Accumulators for per-passenger metrics
    double total_wait = 0;
    double total_in_vehicle = 0;
    double total_detour_ratio = 0;
    int detour_count = 0;

    // Per-vehicle loop
    for (int v = 0; v < routing.vehicles(); ++v)
    {
        // ========== Step 1: Extract route ==========
        int64_t idx = routing.Start(v);
        std::vector<int> visit_m;              // Manager indices
        std::vector<int> visit_nodes;          // Graph node IDs

        while (!routing.IsEnd(idx))
        {
            int m = manager.IndexToNode(idx).value();
            visit_m.push_back(m);
            visit_nodes.push_back(node_for(m));
            idx = solution->Value(routing.NextVar(idx));
        }

        // Add final return to depot
        visit_m.push_back(0);
        visit_nodes.push_back(station_node);

        // ========== Step 2: Identify pickups ==========
        std::vector<int> passenger_commuter_indices;  // Which commuters are picked up
        std::vector<size_t> passenger_positions;      // At which position in route

        for (size_t pos = 0; pos < visit_m.size(); ++pos)
        {
            int m = visit_m[pos];
            if (m >= 1 && m <= N)  // It's a customer pickup
            {
                int commuter_idx = m - 1;
                passenger_commuter_indices.push_back(commuter_idx);
                passenger_positions.push_back(pos);
                served[commuter_idx] = true;
            }
        }

        // ========== Step 3: Handle empty vehicles ==========
        if (passenger_commuter_indices.empty())
        {
            m.vehicles_idle++;
            continue;
        }

        m.vehicles_used++;
        m.total_vehicle_trips++;

        // ========== Step 4: Sharing metrics ==========
        int pax_count = static_cast<int>(passenger_commuter_indices.size());
        m.avg_passengers_per_trip += pax_count;

        if (pax_count == 1)
            m.solo_trips++;
        else
            m.shared_trips++;

        // ========== Step 5: Calculate segment distances and occupancy ==========
        std::vector<double> segment_distances_km;  // Distance of each segment
        std::vector<int> segment_occupancy;        // Occupancy during each segment

        int current_occ = 0;
        double route_total_km = 0;

        for (size_t i = 0; i + 1 < visit_nodes.size(); ++i)
        {
            // Check if we pick up someone at position i
            for (size_t p = 0; p < passenger_positions.size(); ++p)
            {
                if (passenger_positions[p] == i)
                {
                    current_occ++;  // Pickup increases occupancy
                }
            }

            // Calculate segment distance
            std::vector<int> leg;
            int d_mm = query_path(visit_nodes[i], visit_nodes[i + 1], leg);
            double seg_km = d_mm / 1e6;

            segment_distances_km.push_back(seg_km);
            segment_occupancy.push_back(current_occ);
            route_total_km += seg_km;

            // Classify as loaded or empty
            if (current_occ > 0)
                m.loaded_vmt_km += seg_km;
            else
                m.empty_vmt_km += seg_km;

            // Note: In CVRP, all passengers drop off at final depot
            // So occupancy only increases, never decreases until end
        }

        m.total_vmt_km += route_total_km;

        // ========== Step 6: Calculate distance-weighted occupancy ==========
        if (m.loaded_vmt_km > 0)
        {
            double weighted_occ_sum = 0;
            double loaded_dist_sum = 0;

            for (size_t i = 0; i < segment_distances_km.size(); ++i)
            {
                if (segment_occupancy[i] > 0)
                {
                    weighted_occ_sum += segment_occupancy[i] * segment_distances_km[i];
                    loaded_dist_sum += segment_distances_km[i];
                }
            }

            if (loaded_dist_sum > 0)
            {
                // This gives average occupancy weighted by distance
                m.avg_vehicle_occupancy += weighted_occ_sum / loaded_dist_sum;
            }
        }

        // ========== Step 7: Build routing index lookup for this vehicle ==========
        // Map: commuter_idx -> routing index (for time queries)
        std::unordered_map<int, int64_t> commuter_to_routing_idx;
        idx = routing.Start(v);
        while (!routing.IsEnd(idx))
        {
            int m = manager.IndexToNode(idx).value();
            if (m >= 1 && m <= N)
            {
                commuter_to_routing_idx[m - 1] = idx;
            }
            idx = solution->Value(routing.NextVar(idx));
        }

        // ========== Step 8: Per-passenger metrics ==========
        for (size_t p = 0; p < passenger_commuter_indices.size(); ++p)
        {
            int commuter_idx = passenger_commuter_indices[p];
            size_t pickup_pos = passenger_positions[p];

            // --- Time Metrics ---
            int64_t pickup_routing_idx = commuter_to_routing_idx[commuter_idx];
            int64_t pickup_time_ms = solution->Value(time_dim.CumulVar(pickup_routing_idx));
            int64_t dropoff_time_ms = solution->Value(time_dim.CumulVar(routing.End(v)));

            // Wait time (can be 0 if vehicle arrives exactly at earliest time)
            double wait_min = std::max(0.0,
                (pickup_time_ms - pickup_earliest_ms[commuter_idx]) / 60000.0);

            // In-vehicle time
            double in_vehicle_min = (dropoff_time_ms - pickup_time_ms) / 60000.0;

            total_wait += wait_min;
            total_in_vehicle += in_vehicle_min;
            m.max_wait_time_min = std::max(m.max_wait_time_min, wait_min);

            // --- Distance Metrics ---
            // Direct distance (if passenger drove alone)
            std::vector<int> direct_leg;
            int direct_mm = query_path(visit_nodes[pickup_pos], station_node, direct_leg);
            double direct_km = direct_mm / 1e6;
            m.total_passenger_km += direct_km;

            // Actual distance traveled in shared vehicle
            // Sum from pickup position to end (station)
            double actual_km = 0;
            for (size_t seg = pickup_pos; seg < segment_distances_km.size(); ++seg)
            {
                actual_km += segment_distances_km[seg];
            }

            // Detour ratio (1.0 = no detour, 1.5 = 50% longer route)
            if (direct_km > 0.001)  // Avoid division by zero
            {
                double detour_ratio = actual_km / direct_km;
                total_detour_ratio += detour_ratio;
                detour_count++;
            }
        }
    } // End of vehicle loop

    // ========== Step 9: Aggregate metrics ==========

    // Service coverage
    m.served_commuters = 0;
    for (bool s : served)
        if (s) m.served_commuters++;

    m.unserved_commuters = N - m.served_commuters;

    if (N > 0)
        m.service_rate = static_cast<double>(m.served_commuters) / N;

    // Time averages
    if (m.served_commuters > 0)
    {
        m.avg_wait_time_min = total_wait / m.served_commuters;
        m.avg_in_vehicle_time_min = total_in_vehicle / m.served_commuters;
        m.avg_total_trip_time_min = m.avg_wait_time_min + m.avg_in_vehicle_time_min;
    }

    // Vehicle trip averages
    if (m.total_vehicle_trips > 0)
    {
        m.avg_passengers_per_trip /= m.total_vehicle_trips;
        m.avg_vehicle_occupancy /= m.total_vehicle_trips;
        m.pooling_rate = static_cast<double>(m.shared_trips) / m.total_vehicle_trips;
        m.avg_distance_per_trip_km = m.total_vmt_km / m.total_vehicle_trips;
    }

    // Detour average
    if (detour_count > 0)
    {
        m.avg_detour_ratio = total_detour_ratio / detour_count;
    }

    // Empty ratio
    if (m.total_vmt_km > 0.001)
    {
        m.empty_ratio = m.empty_vmt_km / m.total_vmt_km;
    }

    return m;
}

void write_metrics_json(const AVServiceMetrics& m, const std::string& filename)
{
    std::ofstream out(filename);
    out << std::fixed << std::setprecision(2);

    out << "{\n";
    out << "  \"coverage\": {\n";
    out << "    \"total_commuters\": " << m.total_commuters << ",\n";
    out << "    \"served_commuters\": " << m.served_commuters << ",\n";
    out << "    \"unserved_commuters\": " << m.unserved_commuters << ",\n";
    out << "    \"service_rate\": " << m.service_rate << "\n";
    out << "  },\n";
    out << "  \"time_performance_minutes\": {\n";
    out << "    \"avg_wait_time\": " << m.avg_wait_time_min << ",\n";
    out << "    \"max_wait_time\": " << m.max_wait_time_min << ",\n";
    out << "    \"avg_in_vehicle_time\": " << m.avg_in_vehicle_time_min << ",\n";
    out << "    \"avg_total_trip_time\": " << m.avg_total_trip_time_min << "\n";
    out << "  },\n";
    out << "  \"distance_km\": {\n";
    out << "    \"total_vmt\": " << m.total_vmt_km << ",\n";
    out << "    \"avg_distance_per_trip\": " << m.avg_distance_per_trip_km << ",\n";
    out << "    \"total_passenger_km\": " << m.total_passenger_km << ",\n";
    out << "    \"avg_detour_ratio\": " << m.avg_detour_ratio << "\n";
    out << "  },\n";
    out << "  \"sharing_occupancy\": {\n";
    out << "    \"total_vehicle_trips\": " << m.total_vehicle_trips << ",\n";
    out << "    \"avg_passengers_per_trip\": " << m.avg_passengers_per_trip << ",\n";
    out << "    \"solo_trips\": " << m.solo_trips << ",\n";
    out << "    \"shared_trips\": " << m.shared_trips << ",\n";
    out << "    \"pooling_rate\": " << m.pooling_rate << ",\n";
    out << "    \"avg_vehicle_occupancy\": " << m.avg_vehicle_occupancy << "\n";
    out << "  },\n";
    out << "  \"vehicle_utilization\": {\n";
    out << "    \"vehicles_used\": " << m.vehicles_used << ",\n";
    out << "    \"vehicles_idle\": " << m.vehicles_idle << ",\n";
    out << "    \"loaded_vmt_km\": " << m.loaded_vmt_km << ",\n";
    out << "    \"empty_vmt_km\": " << m.empty_vmt_km << ",\n";
    out << "    \"empty_ratio\": " << m.empty_ratio << "\n";
    out << "  }\n";
    out << "}\n";

    out.close();

    std::cout << "[metrics] Written to: " << filename << "\n";
}

void print_metrics_summary(const AVServiceMetrics& m)
{
    std::cout << "\n╔════════════════════════════════════════════╗\n";
    std::cout << "║     AV FIRST-MILE SERVICE METRICS          ║\n";
    std::cout << "╚════════════════════════════════════════════╝\n\n";

    std::cout << std::fixed << std::setprecision(2);

    std::cout << "📊 COVERAGE\n";
    std::cout << "  Total Requests:      " << m.total_commuters << "\n";
    std::cout << "  Served:              " << m.served_commuters << "\n";
    std::cout << "  Unserved:            " << m.unserved_commuters << "\n";
    std::cout << "  Service Rate:        " << (m.service_rate * 100) << "%\n\n";

    std::cout << "⏱️  TIME PERFORMANCE\n";
    std::cout << "  Avg Wait Time:       " << m.avg_wait_time_min << " min\n";
    std::cout << "  Max Wait Time:       " << m.max_wait_time_min << " min\n";
    std::cout << "  Avg In-Vehicle:      " << m.avg_in_vehicle_time_min << " min\n";
    std::cout << "  Avg Total Trip:      " << m.avg_total_trip_time_min << " min\n\n";

    std::cout << "🚗 DISTANCE & EFFICIENCY\n";
    std::cout << "  Total VMT:           " << m.total_vmt_km << " km\n";
    std::cout << "  Loaded VMT:          " << m.loaded_vmt_km << " km ("
              << ((1.0 - m.empty_ratio) * 100) << "%)\n";
    std::cout << "  Empty VMT:           " << m.empty_vmt_km << " km ("
              << (m.empty_ratio * 100) << "%)\n";
    std::cout << "  Avg Detour Ratio:    " << m.avg_detour_ratio << "x\n";
    std::cout << "  Passenger-km:        " << m.total_passenger_km << " km\n\n";

    std::cout << "👥 SHARING & OCCUPANCY\n";
    std::cout << "  Vehicle Trips:       " << m.total_vehicle_trips << "\n";
    std::cout << "  Avg Passengers/Trip: " << m.avg_passengers_per_trip << "\n";
    std::cout << "  Solo Trips:          " << m.solo_trips << " ("
              << ((1.0 - m.pooling_rate) * 100) << "%)\n";
    std::cout << "  Shared Trips:        " << m.shared_trips << " ("
              << (m.pooling_rate * 100) << "%)\n";
    std::cout << "  Avg Occupancy:       " << m.avg_vehicle_occupancy << " (distance-weighted)\n\n";

    std::cout << "🚙 FLEET UTILIZATION\n";
    std::cout << "  Vehicles Used:       " << m.vehicles_used << "\n";
    std::cout << "  Vehicles Idle:       " << m.vehicles_idle << "\n\n";
}