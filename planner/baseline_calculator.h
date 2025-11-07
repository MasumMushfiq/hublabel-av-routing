// analysis/baseline_calculator.h
#ifndef ROUTINGKIT_BASELINE_CALCULATOR_H
#define ROUTINGKIT_BASELINE_CALCULATOR_H

#include <vector>
#include <functional>
#include <unordered_map>
#include <string>
#include "edge_attrs.h"

// QueryPathFn signature (same as in ortools_solver.h)
using QueryPathFn = std::function<int(int, int, std::vector<int>&)>;

/**
 * Baseline metrics for private vehicle scenario
 * Assumes: Each commuter drives their own private car from home to station
 */
struct PrivateVehicleBaseline {
    int total_commuters = 0;
    
    // Distance metrics (km)
    double total_vmt_km = 0.0;           // Sum of all direct home→station distances
    double avg_distance_per_trip_km = 0.0;
    double empty_miles_ratio = 0.0;      // Always 0 (no empty miles for private vehicles)
    
    // Occupancy
    double avg_occupancy = 1.0;          // Always 1.0 (solo driving)
    
    // Fuel & Emissions
    double total_fuel_liters = 0.0;
    double fuel_per_100km = 0.0;         // Fleet average fuel efficiency
    double total_co2_kg = 0.0;
    double co2_per_100km = 0.0;
    
    // Time (minutes)
    double avg_trip_time_min = 0.0;
    double total_trip_time_min = 0.0;
    
    // Per-commuter breakdown (optional for detailed analysis)
    std::vector<double> individual_distances_km;
    std::vector<double> individual_trip_times_min;
};

/**
 * Calculate baseline metrics for private vehicle scenario
 * 
 * @param commuter_nodes Vector of graph node IDs for commuter locations
 * @param station_node Graph node ID for the train station
 * @param query_path Function to query shortest path: query_path(from, to, out_path) returns distance in mm
 * @param edge_tbl Edge attributes table for calculating travel times
 * @param private_car_speed_kmph Average speed for private cars (default: 60.0 km/h)
 * @return PrivateVehicleBaseline struct with all calculated metrics
 * 
 * Assumptions:
 * - Private Car Fuel Efficiency: 11.1 L/100km (Australian average, ABS 2020)
 * - CO₂ Emissions: 2.31 kg/L (petrol, DCCEEW 2023)
 * - Route: Direct shortest path from home to station
 * - No detours, no empty miles, no waiting time
 */
PrivateVehicleBaseline calculate_private_vehicle_baseline(
    const std::vector<int>& commuter_nodes,
    int station_node,
    const QueryPathFn& query_path,
    const std::unordered_map<EdgeKey, EdgeAttr>& edge_tbl,
    int original_total_count = -1,  // ADD THIS: optional, for reporting
    double private_car_speed_kmph = 60.0
);

/**
 * Print baseline summary to console
 */
void print_baseline_summary(const PrivateVehicleBaseline& baseline);

/**
 * Write baseline metrics to JSON file
 */
void write_baseline_json(const PrivateVehicleBaseline& baseline, const std::string& filename);

#endif //ROUTINGKIT_BASELINE_CALCULATOR_H
