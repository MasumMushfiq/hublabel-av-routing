// analysis/baseline_calculator.cpp
#include "baseline_calculator.h"
#include "time_cost.h"
#include <iostream>
#include <fstream>
#include <iomanip>
#include <cmath>
#include <numeric>

// Private car fuel parameters (Australian standards)
constexpr double PRIVATE_CAR_FUEL_L_PER_100KM = 11.1;  // ABS Survey 2020
constexpr double PRIVATE_CAR_CO2_KG_PER_LITER = 2.31;  // DCCEEW 2023 (petrol)

PrivateVehicleBaseline calculate_private_vehicle_baseline(
    const std::vector<int>& commuter_nodes,
    int station_node,
    const QueryPathFn& query_path,
    const std::unordered_map<EdgeKey, EdgeAttr>& edge_tbl,
    int original_total_count,
    double private_car_speed_kmph)
{
    PrivateVehicleBaseline baseline;

    // Use provided original count, or default to commuter_nodes size
    baseline.total_commuters = (original_total_count > 0)
        ? original_total_count
        : static_cast<int>(commuter_nodes.size());

    // Reserve space for per-commuter data
    baseline.individual_distances_km.reserve(commuter_nodes.size());
    baseline.individual_trip_times_min.reserve(commuter_nodes.size());

    double total_distance_mm = 0.0;
    double total_time_ms = 0.0;

    // All commuters in the list should be reachable (pre-filtered)
    // Calculate metrics for each commuter
    for (size_t i = 0; i < commuter_nodes.size(); ++i)
    {
        int home_node = commuter_nodes[i];

        // Query shortest path from home to station
        std::vector<int> path;
        int distance_mm = query_path(home_node, station_node, path);

        if (distance_mm <= 0 || path.empty())
        {
            std::cerr << "Warning: No valid path found for commuter " << i
                      << " (node " << home_node << " → " << station_node << ")\n";
            continue;  // Should not happen if pre-filtered
        }

        // Convert distance to km
        double distance_km = distance_mm / 1e6;
        baseline.individual_distances_km.push_back(distance_km);
        total_distance_mm += distance_mm;

        // Calculate travel time using edge_tbl
        int64_t trip_time_ms = 0;

        if (!edge_tbl.empty() && path.size() >= 2)
        {
            // Calculate time using actual edge attributes
            for (size_t j = 0; j + 1 < path.size(); ++j)
            {
                int from_node = path[j];
                int to_node = path[j + 1];
                EdgeKey key = edge_key(from_node, to_node);

                auto it = edge_tbl.find(key);
                if (it != edge_tbl.end())
                {
                    // Calculate time from length and speed
                    double length_km = it->second.length_m / 1000.0;
                    double speed_kph = it->second.speed_kph;
                    if (speed_kph > 0)
                    {
                        trip_time_ms += static_cast<int64_t>(
                            (length_km / speed_kph) * 3600.0 * 1000.0
                        );
                    }
                    else
                    {
                        trip_time_ms += static_cast<int64_t>(
                            (length_km / private_car_speed_kmph) * 3600.0 * 1000.0
                        );
                    }
                }
                else
                {
                    // Fallback: estimate using average speed
                    std::vector<int> segment_path;
                    int segment_dist_mm = query_path(from_node, to_node, segment_path);
                    double segment_km = segment_dist_mm / 1e6;
                    trip_time_ms += static_cast<int64_t>(
                        (segment_km / private_car_speed_kmph) * 3600.0 * 1000.0
                    );
                }
            }
        }
        else
        {
            // Fallback: use average speed for entire trip
            trip_time_ms = static_cast<int64_t>(
                (distance_km / private_car_speed_kmph) * 3600.0 * 1000.0
            );
        }

        double trip_time_min = trip_time_ms / (60.0 * 1000.0);
        baseline.individual_trip_times_min.push_back(trip_time_min);
        total_time_ms += trip_time_ms;
    }

    int valid_commuters = baseline.individual_distances_km.size();

    // Calculate aggregate metrics
    if (valid_commuters > 0)
    {
        // Distance metrics
        baseline.total_vmt_km = total_distance_mm / 1e6;
        baseline.avg_distance_per_trip_km = baseline.total_vmt_km / valid_commuters;

        // Time metrics
        baseline.total_trip_time_min = total_time_ms / (60.0 * 1000.0);
        baseline.avg_trip_time_min = baseline.total_trip_time_min / valid_commuters;

        // Fuel calculation
        baseline.total_fuel_liters = (baseline.total_vmt_km * PRIVATE_CAR_FUEL_L_PER_100KM) / 100.0;
        baseline.fuel_per_100km = PRIVATE_CAR_FUEL_L_PER_100KM;

        // CO₂ calculation
        baseline.total_co2_kg = baseline.total_fuel_liters * PRIVATE_CAR_CO2_KG_PER_LITER;
        baseline.co2_per_100km = PRIVATE_CAR_FUEL_L_PER_100KM * PRIVATE_CAR_CO2_KG_PER_LITER;
    }

    baseline.empty_miles_ratio = 0.0;
    baseline.avg_occupancy = 1.0;

    // Report if any were unreachable
    int unreachable = baseline.total_commuters - valid_commuters;
    if (unreachable > 0) {
        std::cout << "\n📊 Baseline Summary:\n";
        std::cout << "   Total commuters:      " << baseline.total_commuters << "\n";
        std::cout << "   Reachable:            " << valid_commuters << "\n";
        std::cout << "   Unreachable:          " << unreachable << " (excluded from analysis)\n\n";
    }

    return baseline;
}

void print_baseline_summary(const PrivateVehicleBaseline& baseline)
{
    int reachable = baseline.individual_distances_km.size();
    int unreachable = baseline.total_commuters - reachable;

    std::cout << "\n";
    std::cout << "╔════════════════════════════════════════════════════════════════╗\n";
    std::cout << "║          PRIVATE VEHICLE BASELINE METRICS                      ║\n";
    std::cout << "╠════════════════════════════════════════════════════════════════╣\n";

    // Coverage
    std::cout << "║ COVERAGE                                                       ║\n";
    std::cout << "║   Total Commuters:              " << std::setw(6) << baseline.total_commuters
              << "                        ║\n";

    if (unreachable > 0) {
        std::cout << "║   Reachable:                    " << std::setw(6) << reachable
                  << "                        ║\n";
        std::cout << "║   Unreachable:                  " << std::setw(6) << unreachable
                  << " (excluded)             ║\n";
    }

    std::cout << "║   Service Rate (reachable):     " << std::setw(6) << std::fixed << std::setprecision(1)
              << 100.0 << "%                       ║\n";

    // Distance & Efficiency
    std::cout << "║ DISTANCE & EFFICIENCY                                          ║\n";
    std::cout << "║   Total Vehicle-km (VMT):       " << std::setw(6) << std::fixed << std::setprecision(2)
              << baseline.total_vmt_km << " km                    ║\n";
    std::cout << "║   Avg Distance per Trip:        " << std::setw(6) << std::fixed << std::setprecision(2)
              << baseline.avg_distance_per_trip_km << " km                    ║\n";
    std::cout << "║   Empty Miles Ratio:            " << std::setw(6) << std::fixed << std::setprecision(1)
              << baseline.empty_miles_ratio << "%                       ║\n";
    std::cout << "╠════════════════════════════════════════════════════════════════╣\n";

    // Occupancy
    std::cout << "║ OCCUPANCY                                                      ║\n";
    std::cout << "║   Avg Vehicle Occupancy:        " << std::setw(6) << std::fixed << std::setprecision(2)
              << baseline.avg_occupancy << "                          ║\n";
    std::cout << "║   Pooling Rate:                 " << std::setw(6) << std::fixed << std::setprecision(1)
              << 0.0 << "%                       ║\n";
    std::cout << "╠════════════════════════════════════════════════════════════════╣\n";

    // Time Performance
    std::cout << "║ TIME PERFORMANCE                                               ║\n";
    std::cout << "║   Avg Trip Time:                " << std::setw(6) << std::fixed << std::setprecision(2)
              << baseline.avg_trip_time_min << " min                   ║\n";
    std::cout << "║   Total Trip Time:              " << std::setw(6) << std::fixed << std::setprecision(2)
              << baseline.total_trip_time_min << " min                   ║\n";
    std::cout << "╠════════════════════════════════════════════════════════════════╣\n";

    // Fuel & Emissions
    std::cout << "║ FUEL & EMISSIONS                                               ║\n";
    std::cout << "║   Total Fuel:                   " << std::setw(6) << std::fixed << std::setprecision(2)
              << baseline.total_fuel_liters << " L                     ║\n";
    std::cout << "║   Fuel Efficiency:              " << std::setw(6) << std::fixed << std::setprecision(2)
              << baseline.fuel_per_100km << " L/100km               ║\n";
    std::cout << "║   Total CO₂:                    " << std::setw(6) << std::fixed << std::setprecision(2)
              << baseline.total_co2_kg << " kg                    ║\n";
    std::cout << "║   CO₂ per 100km:                " << std::setw(6) << std::fixed << std::setprecision(2)
              << baseline.co2_per_100km << " kg                    ║\n";

    // Calculate per-passenger CO₂
    if (baseline.total_commuters > 0)
    {
        double co2_per_passenger = baseline.total_co2_kg / baseline.total_commuters;
        std::cout << "║   CO₂ per Passenger:            " << std::setw(6) << std::fixed << std::setprecision(2)
                  << co2_per_passenger << " kg                    ║\n";
    }

    // Calculate CO₂ intensity (g/passenger-km)
    if (baseline.total_vmt_km > 0)
    {
        double co2_g_per_pax_km = (baseline.total_co2_kg * 1000.0) / baseline.total_vmt_km;
        std::cout << "║   CO₂ Intensity:                " << std::setw(6) << std::fixed << std::setprecision(0)
                  << co2_g_per_pax_km << " g/pax-km              ║\n";
    }

    std::cout << "╚════════════════════════════════════════════════════════════════╝\n";
    std::cout << "\n";

    // Additional notes
    std::cout << "Notes:\n";
    std::cout << "  • Assumes each commuter drives their own private car\n";
    std::cout << "  • Fuel efficiency: " << std::fixed << std::setprecision(2) << PRIVATE_CAR_FUEL_L_PER_100KM << " L/100km (Australian average, ABS 2020)\n";
    std::cout << "  • CO₂ factor: " << std::fixed << std::setprecision(2) << PRIVATE_CAR_CO2_KG_PER_LITER << " kg/L (petrol, DCCEEW 2023)\n";
    std::cout << "  • No empty miles (everyone drives directly home→station)\n";
    std::cout << "  • No detours, no waiting time, no ride sharing\n";
    std::cout << "\n";
}

void write_baseline_json(const PrivateVehicleBaseline& baseline, const std::string& filename)
{
    std::ofstream out(filename);
    if (!out.is_open())
    {
        std::cerr << "Error: Could not open " << filename << " for writing\n";
        return;
    }

    out << std::fixed << std::setprecision(2);
    out << "{\n";
    out << "  \"scenario\": \"private_vehicle_baseline\",\n";
    out << "  \"description\": \"Each commuter drives their own private car from home to station\",\n";
    out << "  \"assumptions\": {\n";
    out << "    \"fuel_efficiency_L_per_100km\": " << std::setprecision(2) << PRIVATE_CAR_FUEL_L_PER_100KM << ",\n";
    out << "    \"co2_kg_per_liter\": " << std::setprecision(2) << PRIVATE_CAR_CO2_KG_PER_LITER << ",\n";
    out << "    \"source_fuel\": \"ABS Survey of Motor Vehicle Use (2020)\",\n";
    out << "    \"source_co2\": \"DCCEEW National Greenhouse Accounts Factors (2023)\"\n";
    out << "  },\n";

    out << "  \"coverage\": {\n";
    out << "    \"total_commuters\": " << baseline.total_commuters << ",\n";
    out << "    \"service_rate_percent\": 100.0\n";
    out << "  },\n";

    out << "  \"distance_km\": {\n";
    out << "    \"total_vmt\": " << baseline.total_vmt_km << ",\n";
    out << "    \"avg_per_trip\": " << baseline.avg_distance_per_trip_km << ",\n";
    out << "    \"empty_miles_ratio_percent\": " << baseline.empty_miles_ratio << "\n";
    out << "  },\n";

    out << "  \"occupancy\": {\n";
    out << "    \"avg_vehicle_occupancy\": " << baseline.avg_occupancy << ",\n";
    out << "    \"pooling_rate_percent\": 0.0\n";
    out << "  },\n";

    out << "  \"time_minutes\": {\n";
    out << "    \"avg_trip_time\": " << baseline.avg_trip_time_min << ",\n";
    out << "    \"total_trip_time\": " << baseline.total_trip_time_min << "\n";
    out << "  },\n";

    out << "  \"fuel_emissions\": {\n";
    out << "    \"total_fuel_liters\": " << baseline.total_fuel_liters << ",\n";
    out << "    \"fuel_per_100km\": " << baseline.fuel_per_100km << ",\n";
    out << "    \"total_co2_kg\": " << baseline.total_co2_kg << ",\n";
    out << "    \"co2_per_100km\": " << baseline.co2_per_100km << ",\n";

    if (baseline.total_commuters > 0)
    {
        out << "    \"co2_per_passenger_kg\": " << (baseline.total_co2_kg / baseline.total_commuters) << ",\n";
    }

    if (baseline.total_vmt_km > 0)
    {
        double co2_g_per_pax_km = (baseline.total_co2_kg * 1000.0) / baseline.total_vmt_km;
        out << "    \"co2_g_per_passenger_km\": " << co2_g_per_pax_km << "\n";
    }
    else
    {
        out << "    \"co2_g_per_passenger_km\": 0.0\n";
    }

    out << "  }";

    // Optional: Include per-commuter breakdown
    if (!baseline.individual_distances_km.empty())
    {
        out << ",\n  \"per_commuter\": [\n";
        for (size_t i = 0; i < baseline.individual_distances_km.size(); ++i)
        {
            out << "    {\n";
            out << "      \"commuter_id\": " << i << ",\n";
            out << "      \"distance_km\": " << baseline.individual_distances_km[i] << ",\n";
            out << "      \"trip_time_min\": " << baseline.individual_trip_times_min[i] << ",\n";

            double fuel_L = (baseline.individual_distances_km[i] * PRIVATE_CAR_FUEL_L_PER_100KM) / 100.0;
            double co2_kg = fuel_L * PRIVATE_CAR_CO2_KG_PER_LITER;

            out << "      \"fuel_liters\": " << fuel_L << ",\n";
            out << "      \"co2_kg\": " << co2_kg << "\n";
            out << "    }";

            if (i + 1 < baseline.individual_distances_km.size())
                out << ",";
            out << "\n";
        }
        out << "  ]\n";
    }
    else
    {
        out << "\n";
    }

    out << "}\n";
    out.close();

    std::cout << "✓ Baseline metrics written to: " << filename << "\n";
}