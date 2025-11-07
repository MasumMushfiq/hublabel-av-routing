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

            // FIX: Validate path exists (skip invalid segments from unreachable nodes)
            if (d_mm <= 0 || leg.empty())
            {
                std::cerr << "[metrics] WARNING: Invalid path from node "
                          << visit_nodes[i] << " to " << visit_nodes[i + 1]
                          << ", returned distance: " << d_mm << " mm. Skipping segment.\n";
                continue;  // Skip this invalid segment
            }

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

        // ========== Step 6: Calculate distance-weighted occupancy AND passenger-km ==========
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

                    // FIX: Accumulate actual passenger-km (occupancy × distance)
                    m.total_passenger_km += segment_occupancy[i] * segment_distances_km[i];
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
                int commuter_idx = m - 1;
                commuter_to_routing_idx[commuter_idx] = idx;
            }
            idx = solution->Value(routing.NextVar(idx));
        }

        // ========== Step 8: Per-passenger wait/travel times & detour ==========
        for (int commuter_idx : passenger_commuter_indices)
        {
            int64_t routing_idx = commuter_to_routing_idx[commuter_idx];

            // Pickup time
            int64_t pickup_time_ms = solution->Value(time_dim.CumulVar(routing_idx));

            // Earliest allowed pickup (time window start)
            int64_t earliest_ms = pickup_earliest_ms[commuter_idx];

            // Wait time = pickup_time - earliest
            double wait_min = (pickup_time_ms - earliest_ms) / (60.0 * 1000.0);
            if (wait_min < 0) wait_min = 0;

            total_wait += wait_min;
            m.max_wait_time_min = std::max(m.max_wait_time_min, wait_min);

            // Dropoff time (at depot after all pickups)
            int64_t dropoff_idx = routing.End(v);
            int64_t dropoff_time_ms = solution->Value(time_dim.CumulVar(dropoff_idx));

            // In-vehicle time
            double in_vehicle_min = (dropoff_time_ms - pickup_time_ms) / (60.0 * 1000.0);
            total_in_vehicle += in_vehicle_min;

            // Detour ratio = actual in-vehicle distance / direct distance
            int home_node = commuter_nodes[commuter_idx];
            std::vector<int> direct_path;
            int direct_mm = query_path(home_node, station_node, direct_path);
            double direct_km = (direct_mm > 0) ? (direct_mm / 1e6) : 0.0;

            if (direct_km > 0.001)
            {
                // Find actual distance traveled by this passenger
                double actual_km = 0;
                size_t pickup_pos = 0;
                for (size_t p = 0; p < passenger_positions.size(); ++p)
                {
                    if (passenger_commuter_indices[p] == commuter_idx)
                    {
                        pickup_pos = passenger_positions[p];
                        break;
                    }
                }

                // Sum segments from pickup to depot
                for (size_t i = pickup_pos; i < segment_distances_km.size(); ++i)
                {
                    actual_km += segment_distances_km[i];
                }

                double detour = actual_km / direct_km;
                total_detour_ratio += detour;
                detour_count++;
            }
        }
    }

    // ========== Finalize metrics ==========
    m.served_commuters = 0;
    for (bool s : served) if (s) m.served_commuters++;
    m.unserved_commuters = N - m.served_commuters;
    m.service_rate = (N > 0) ? (static_cast<double>(m.served_commuters) / N) : 0.0;

    // Time averages
    if (m.served_commuters > 0)
    {
        m.avg_wait_time_min = total_wait / m.served_commuters;
        m.avg_in_vehicle_time_min = total_in_vehicle / m.served_commuters;
        m.avg_total_trip_time_min = m.avg_wait_time_min + m.avg_in_vehicle_time_min;
    }

    // Distance efficiency
    if (m.total_vehicle_trips > 0)
    {
        m.avg_passengers_per_trip /= m.total_vehicle_trips;
    }

    if (m.total_vmt_km > 0)
    {
        m.avg_distance_per_trip_km = m.total_vmt_km / m.total_vehicle_trips;
        m.empty_ratio = (m.empty_vmt_km / m.total_vmt_km) * 100.0;
    }

    if (m.vehicles_used > 0)
    {
        m.avg_vehicle_occupancy /= m.vehicles_used;
    }

    if (detour_count > 0)
    {
        m.avg_detour_ratio = total_detour_ratio / detour_count;
    }

    if (m.total_vehicle_trips > 0)
    {
        m.pooling_rate = (static_cast<double>(m.shared_trips) / m.total_vehicle_trips) * 100.0;
    }

    // ========== Fuel & Emissions (PER VEHICLE TYPE) ==========
    m.total_fuel_liters = 0.0;
    m.total_co2_kg = 0.0;

    for (auto& [vtype, vmetrics] : type_metrics_acc)
    {
        if (vmetrics.total_vmt_km > 0)
        {
            // Get fuel parameters for this vehicle type
            FuelParameters fuel_params = get_fuel_parameters(vtype);

            // Calculate fuel and CO₂ for this vehicle type
            double type_fuel_liters = (vmetrics.total_vmt_km * fuel_params.liters_per_100km) / 100.0;
            double type_co2_kg = type_fuel_liters * fuel_params.co2_kg_per_liter;

            // Accumulate totals
            m.total_fuel_liters += type_fuel_liters;
            m.total_co2_kg += type_co2_kg;

            // Calculate per-type empty ratio
            if (vmetrics.total_vmt_km > 0)
            {
                vmetrics.empty_ratio = (vmetrics.empty_vmt_km / vmetrics.total_vmt_km) * 100.0;
            }

            // Normalize per-type occupancy
            if (vmetrics.vehicles_used > 0)
            {
                vmetrics.avg_occupancy /= vmetrics.vehicles_used;
            }
        }
    }

    // Fleet average fuel efficiency
    if (m.total_vmt_km > 0)
    {
        m.fuel_per_km = (m.total_fuel_liters / m.total_vmt_km) * 100.0;  // L/100km
    }

    // CO₂ intensity
    if (m.total_passenger_km > 0)
    {
        m.co2_per_passenger_km = (m.total_co2_kg * 1000.0) / m.total_passenger_km;  // g/pax-km
    }

    // Store per-vehicle-type metrics
    m.per_vehicle_type = type_metrics_acc;

    return m;
}

void write_metrics_json(const AVServiceMetrics& metrics, const std::string& filename)
{
    std::ofstream out(filename);
    if (!out.is_open())
    {
        std::cerr << "Error: Could not open " << filename << " for writing\n";
        return;
    }

    out << std::fixed << std::setprecision(2);
    out << "{\n";

    // Coverage
    out << "  \"coverage\": {\n";
    out << "    \"total_commuters\": " << metrics.total_commuters << ",\n";
    out << "    \"served\": " << metrics.served_commuters << ",\n";
    out << "    \"unserved\": " << metrics.unserved_commuters << ",\n";
    out << "    \"service_rate\": " << (metrics.service_rate * 100.0) << "\n";
    out << "  },\n";

    // Time performance
    out << "  \"time_minutes\": {\n";
    out << "    \"avg_wait\": " << metrics.avg_wait_time_min << ",\n";
    out << "    \"max_wait\": " << metrics.max_wait_time_min << ",\n";
    out << "    \"avg_in_vehicle\": " << metrics.avg_in_vehicle_time_min << ",\n";
    out << "    \"avg_total_trip\": " << metrics.avg_total_trip_time_min << "\n";
    out << "  },\n";

    // Distance & efficiency
    out << "  \"distance_km\": {\n";
    out << "    \"total_vmt\": " << metrics.total_vmt_km << ",\n";
    out << "    \"loaded_vmt\": " << metrics.loaded_vmt_km << ",\n";
    out << "    \"empty_vmt\": " << metrics.empty_vmt_km << ",\n";
    out << "    \"empty_ratio_pct\": " << metrics.empty_ratio << ",\n";
    out << "    \"avg_per_trip\": " << metrics.avg_distance_per_trip_km << ",\n";
    out << "    \"passenger_km\": " << metrics.total_passenger_km << ",\n";
    out << "    \"avg_detour_ratio\": " << metrics.avg_detour_ratio << "\n";
    out << "  },\n";

    // Sharing & occupancy
    out << "  \"sharing\": {\n";
    out << "    \"total_trips\": " << metrics.total_vehicle_trips << ",\n";
    out << "    \"avg_passengers_per_trip\": " << metrics.avg_passengers_per_trip << ",\n";
    out << "    \"solo_trips\": " << metrics.solo_trips << ",\n";
    out << "    \"shared_trips\": " << metrics.shared_trips << ",\n";
    out << "    \"pooling_rate_pct\": " << metrics.pooling_rate << ",\n";
    out << "    \"avg_occupancy\": " << metrics.avg_vehicle_occupancy << "\n";
    out << "  },\n";

    // Fleet utilization
    out << "  \"fleet\": {\n";
    out << "    \"vehicles_used\": " << metrics.vehicles_used << ",\n";
    out << "    \"vehicles_idle\": " << metrics.vehicles_idle << "\n";
    out << "  },\n";

    // Fuel & emissions
    out << "  \"fuel_emissions\": {\n";
    out << "    \"total_fuel_liters\": " << metrics.total_fuel_liters << ",\n";
    out << "    \"fuel_per_100km\": " << metrics.fuel_per_km << ",\n";
    out << "    \"total_co2_kg\": " << metrics.total_co2_kg << ",\n";
    out << "    \"co2_g_per_pax_km\": " << metrics.co2_per_passenger_km << "\n";
    out << "  },\n";

    // Per-vehicle-type breakdown
    out << "  \"per_vehicle_type\": {\n";
    bool first_type = true;
    for (const auto& [vtype, vmetrics] : metrics.per_vehicle_type)
    {
        if (!first_type) out << ",\n";
        first_type = false;

        out << "    \"" << vtype << "\": {\n";
        out << "      \"vehicles_used\": " << vmetrics.vehicles_used << ",\n";
        out << "      \"total_trips\": " << vmetrics.total_trips << ",\n";
        out << "      \"passengers_carried\": " << vmetrics.passengers_carried << ",\n";
        out << "      \"avg_occupancy\": " << vmetrics.avg_occupancy << ",\n";
        out << "      \"total_vmt_km\": " << vmetrics.total_vmt_km << ",\n";
        out << "      \"loaded_vmt_km\": " << vmetrics.loaded_vmt_km << ",\n";
        out << "      \"empty_vmt_km\": " << vmetrics.empty_vmt_km << ",\n";
        out << "      \"empty_ratio_pct\": " << vmetrics.empty_ratio << "\n";
        out << "    }";
    }
    out << "\n  }\n";

    out << "}\n";
    out.close();
}

void print_metrics_summary(const AVServiceMetrics& metrics)
{
    std::cout << "\n";
    std::cout << "╔════════════════════════════════════════════╗\n";
    std::cout << "║     AV FIRST-MILE SERVICE METRICS          ║\n";
    std::cout << "╚════════════════════════════════════════════╝\n";
    std::cout << "\n";

    // Coverage
    std::cout << "📊 COVERAGE\n";
    std::cout << "  Total Requests:      " << metrics.total_commuters << "\n";
    std::cout << "  Served:              " << metrics.served_commuters << "\n";
    std::cout << "  Unserved:            " << metrics.unserved_commuters << "\n";
    std::cout << "  Service Rate:        " << std::fixed << std::setprecision(2)
              << (metrics.service_rate * 100.0) << "%\n\n";

    // Time performance
    std::cout << "⏱️  TIME PERFORMANCE\n";
    std::cout << "  Avg Wait Time:       " << std::fixed << std::setprecision(2)
              << metrics.avg_wait_time_min << " min\n";
    std::cout << "  Max Wait Time:       " << metrics.max_wait_time_min << " min\n";
    std::cout << "  Avg In-Vehicle:      " << metrics.avg_in_vehicle_time_min << " min\n";
    std::cout << "  Avg Total Trip:      " << metrics.avg_total_trip_time_min << " min\n\n";

    // Distance & efficiency
    std::cout << "🚗 DISTANCE & EFFICIENCY\n";
    std::cout << "  Total VMT:           " << metrics.total_vmt_km << " km\n";
    std::cout << "  Loaded VMT:          " << metrics.loaded_vmt_km << " km ("
              << std::setprecision(2) << ((metrics.total_vmt_km > 0) ? (metrics.loaded_vmt_km / metrics.total_vmt_km * 100.0) : 0.0)
              << "%)\n";
    std::cout << "  Empty VMT:           " << metrics.empty_vmt_km << " km ("
              << std::setprecision(2) << metrics.empty_ratio << "%)\n";
    std::cout << "  Avg Detour Ratio:    " << std::setprecision(2) << metrics.avg_detour_ratio << "x\n";
    std::cout << "  Passenger-km:        " << metrics.total_passenger_km << " km\n\n";

    // Sharing & occupancy
    std::cout << "👥 SHARING & OCCUPANCY\n";
    std::cout << "  Vehicle Trips:       " << metrics.total_vehicle_trips << "\n";
    std::cout << "  Avg Passengers/Trip: " << std::fixed << std::setprecision(2)
              << metrics.avg_passengers_per_trip << "\n";
    std::cout << "  Solo Trips:          " << metrics.solo_trips << " ("
              << std::setprecision(2) << ((metrics.total_vehicle_trips > 0) ? (metrics.solo_trips * 100.0 / metrics.total_vehicle_trips) : 0.0)
              << "%)\n";
    std::cout << "  Shared Trips:        " << metrics.shared_trips << " ("
              << std::setprecision(2) << metrics.pooling_rate << "%)\n";
    std::cout << "  Avg Occupancy:       " << std::setprecision(2)
              << metrics.avg_vehicle_occupancy << " (distance-weighted)\n\n";

    // Fleet utilization
    std::cout << "🚙 FLEET UTILIZATION\n";
    std::cout << "  Vehicles Used:       " << metrics.vehicles_used << "\n";
    std::cout << "  Vehicles Idle:       " << metrics.vehicles_idle << "\n\n";

    // Fuel & emissions
    std::cout << "⛽ FUEL & EMISSIONS\n";
    std::cout << "  Total Fuel:          " << std::fixed << std::setprecision(2)
              << metrics.total_fuel_liters << " L\n";
    std::cout << "  Fuel Efficiency:     " << metrics.fuel_per_km << " L/100km\n";
    std::cout << "  Total CO₂:           " << metrics.total_co2_kg << " kg\n";
    std::cout << "  CO₂ per pax-km:      " << std::setprecision(2)
              << metrics.co2_per_passenger_km << " g/pax-km\n\n";

    // Per-vehicle-type breakdown
    std::cout << "🚕 PER-VEHICLE-TYPE BREAKDOWN\n";
    for (const auto& [vtype, vmetrics] : metrics.per_vehicle_type)
    {
        if (vmetrics.vehicles_used == 0) continue;

        std::cout << "  " << vtype << ":\n";
        std::cout << "    Vehicles Used:     " << vmetrics.vehicles_used << "\n";
        std::cout << "    Trips:             " << vmetrics.total_trips << "\n";
        std::cout << "    Passengers:        " << vmetrics.passengers_carried << "\n";
        std::cout << "    Avg Occupancy:     " << std::fixed << std::setprecision(2)
                  << vmetrics.avg_occupancy << "\n";
        std::cout << "    VMT:               " << vmetrics.total_vmt_km << " km\n";
        std::cout << "    Empty Ratio:       " << std::setprecision(2)
                  << vmetrics.empty_ratio << "%\n";
        std::cout << "\n";
    }

    std::cout << "[metrics] Written to: console " << "\n";
}