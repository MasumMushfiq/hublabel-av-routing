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
#include <map>

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

    // Initialize per-vehicle-type metrics
    std::map<std::string, VehicleTypeMetrics> type_metrics_acc;

    // Per-vehicle loop
    for (int v = 0; v < routing.vehicles(); ++v)
    {
        const std::string& veh_type = vehicles[v].type;

        // Initialize this vehicle type if first time seeing it
        if (type_metrics_acc.find(veh_type) == type_metrics_acc.end()) {
            type_metrics_acc[veh_type].vehicle_type = veh_type;
        }

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

        // Per-type tracking
        type_metrics_acc[veh_type].vehicles_used++;
        type_metrics_acc[veh_type].total_trips++;

        // ========== Step 4: Sharing metrics ==========
        int pax_count = static_cast<int>(passenger_commuter_indices.size());
        m.avg_passengers_per_trip += pax_count;

        type_metrics_acc[veh_type].passengers_carried += pax_count;

        if (pax_count == 1)
            m.solo_trips++;
        else
            m.shared_trips++;

        // ========== Step 5: Calculate segment distances and occupancy ==========
        std::vector<double> segment_distances_km;  // Distance of each segment
        std::vector<int> segment_occupancy;        // Occupancy during each segment

        int current_occ = 0;
        double route_total_km = 0;
        double route_loaded_km = 0;
        double route_empty_km = 0;

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
            if (current_occ > 0) {
                m.loaded_vmt_km += seg_km;
                route_loaded_km += seg_km;
            } else {
                m.empty_vmt_km += seg_km;
                route_empty_km += seg_km;
            }
        }

        m.total_vmt_km += route_total_km;

        // Per-type VMT tracking
        type_metrics_acc[veh_type].total_vmt_km += route_total_km;
        type_metrics_acc[veh_type].loaded_vmt_km += route_loaded_km;
        type_metrics_acc[veh_type].empty_vmt_km += route_empty_km;

        // ========== Step 6: Calculate distance-weighted occupancy ==========
        if (route_loaded_km > 0)
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
                // Overall average occupancy
                m.avg_vehicle_occupancy += weighted_occ_sum / loaded_dist_sum;

                // Per-type average occupancy
                type_metrics_acc[veh_type].avg_occupancy += weighted_occ_sum / loaded_dist_sum;
            }
        }

        // ========== Step 7: Build routing index lookup for this vehicle ==========
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

            double wait_min = std::max(0.0,
                (pickup_time_ms - pickup_earliest_ms[commuter_idx]) / 60000.0);
            double in_vehicle_min = (dropoff_time_ms - pickup_time_ms) / 60000.0;

            total_wait += wait_min;
            total_in_vehicle += in_vehicle_min;
            m.max_wait_time_min = std::max(m.max_wait_time_min, wait_min);

            // --- Distance Metrics ---
            std::vector<int> direct_leg;
            int direct_mm = query_path(visit_nodes[pickup_pos], station_node, direct_leg);
            double direct_km = direct_mm / 1e6;
            m.total_passenger_km += direct_km;

            double actual_km = 0;
            for (size_t seg = pickup_pos; seg < segment_distances_km.size(); ++seg)
            {
                actual_km += segment_distances_km[seg];
            }

            if (direct_km > 0.001)
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

    // ========== Step 10: Finalize per-vehicle-type metrics ==========
    for (auto& [type, vtm] : type_metrics_acc)
    {
        if (vtm.total_trips > 0)
        {
            vtm.avg_occupancy /= vtm.total_trips;
        }

        if (vtm.total_vmt_km > 0.001)
        {
            vtm.empty_ratio = vtm.empty_vmt_km / vtm.total_vmt_km;
        }

        m.per_vehicle_type[type] = vtm;
    }

    // ========== Step 11: Calculate Fuel & Emissions ==========

    // Calculate total fuel consumed and CO₂ emitted
    m.total_fuel_liters = 0.0;
    m.total_co2_kg = 0.0;

    for (const auto& [type, vtm] : m.per_vehicle_type)
    {
        if (vtm.total_vmt_km > 0.001)
        {
            FuelParameters fuel = get_fuel_parameters(type);

            // Fuel = (VMT in km) / 100 * (L/100km)
            double fuel_liters = (vtm.total_vmt_km / 100.0) * fuel.liters_per_100km;

            // CO₂ = Fuel (L) * CO₂ factor (kg/L)
            double co2_kg = fuel_liters * fuel.co2_kg_per_liter;

            m.total_fuel_liters += fuel_liters;
            m.total_co2_kg += co2_kg;
        }
    }

    // Calculate derived metrics
    if (m.total_vmt_km > 0.001)
    {
        m.fuel_per_km = m.total_fuel_liters / m.total_vmt_km;
    }

    if (m.total_passenger_km > 0.001)
    {
        m.co2_per_passenger_km = m.total_co2_kg / m.total_passenger_km;
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
    out << "  },\n";

    // NEW: Per-vehicle-type breakdown
    out << "  \"per_vehicle_type\": {\n";
    bool first_type = true;
    for (const auto& [type, vtm] : m.per_vehicle_type)
    {
        if (!first_type) out << ",\n";
        first_type = false;

        out << "    \"" << type << "\": {\n";
        out << "      \"vehicles_used\": " << vtm.vehicles_used << ",\n";
        out << "      \"total_trips\": " << vtm.total_trips << ",\n";
        out << "      \"passengers_carried\": " << vtm.passengers_carried << ",\n";
        out << "      \"avg_occupancy\": " << vtm.avg_occupancy << ",\n";
        out << "      \"total_vmt_km\": " << vtm.total_vmt_km << ",\n";
        out << "      \"loaded_vmt_km\": " << vtm.loaded_vmt_km << ",\n";
        out << "      \"empty_vmt_km\": " << vtm.empty_vmt_km << ",\n";
        out << "      \"empty_ratio\": " << vtm.empty_ratio << "\n";
        out << "    }";
    }
    out << "\n  },\n";

    // NEW: Fuel & Emissions (placeholder for now)
    out << "  \"fuel_emissions\": {\n";
    out << "    \"total_fuel_liters\": " << m.total_fuel_liters << ",\n";
    out << "    \"fuel_per_km\": " << m.fuel_per_km << ",\n";
    out << "    \"total_co2_kg\": " << m.total_co2_kg << ",\n";
    out << "    \"co2_per_passenger_km\": " << m.co2_per_passenger_km << "\n";
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

    // NEW: Fuel & Emissions
    std::cout << "⛽ FUEL & EMISSIONS\n";
    std::cout << "  Total Fuel:          " << m.total_fuel_liters << " L\n";
    std::cout << "  Fuel Efficiency:     " << (m.fuel_per_km * 100) << " L/100km\n";
    std::cout << "  Total CO₂:           " << m.total_co2_kg << " kg\n";
    std::cout << "  CO₂ per pax-km:      " << (m.co2_per_passenger_km * 1000) << " g/pax-km\n\n";

    // Per-vehicle-type breakdown
    if (!m.per_vehicle_type.empty())
    {
        std::cout << "🚕 PER-VEHICLE-TYPE BREAKDOWN\n";
        for (const auto& [type, vtm] : m.per_vehicle_type)
        {
            if (vtm.vehicles_used > 0)
            {
                std::cout << "  " << type << ":\n";
                std::cout << "    Vehicles Used:     " << vtm.vehicles_used << "\n";
                std::cout << "    Trips:             " << vtm.total_trips << "\n";
                std::cout << "    Passengers:        " << vtm.passengers_carried << "\n";
                std::cout << "    Avg Occupancy:     " << vtm.avg_occupancy << "\n";
                std::cout << "    VMT:               " << vtm.total_vmt_km << " km\n";
                std::cout << "    Empty Ratio:       " << (vtm.empty_ratio * 100) << "%\n\n";
            }
        }
    }
}