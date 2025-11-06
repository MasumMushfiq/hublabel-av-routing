// planner/av_metrics.h
#ifndef ROUTINGKIT_AV_METRICS_H
#define ROUTINGKIT_AV_METRICS_H

#include <string>
#include <vector>
#include <map>
#include <functional>
#include <unordered_map>

// Forward declarations for OR-Tools types
namespace operations_research {
    class RoutingModel;
    class Assignment;
    class RoutingIndexManager;
}

// Include your local types
#include "edge_attrs.h"

// QueryPathFn signature
using QueryPathFn = std::function<int(int, int, std::vector<int>&)>;

// Forward declare OrToolsVehicle
struct OrToolsVehicle;

// Per-vehicle-type metrics
struct VehicleTypeMetrics {
    std::string vehicle_type;
    int vehicles_used = 0;
    int total_trips = 0;
    int passengers_carried = 0;
    double avg_occupancy = 0.0;              // Distance-weighted
    double total_vmt_km = 0.0;
    double loaded_vmt_km = 0.0;
    double empty_vmt_km = 0.0;
    double empty_ratio = 0.0;
};

struct AVServiceMetrics {
    // Coverage
    int total_commuters = 0;
    int served_commuters = 0;
    int unserved_commuters = 0;
    double service_rate = 0.0;

    // Time Performance (minutes)
    double avg_wait_time_min = 0.0;
    double max_wait_time_min = 0.0;
    double avg_in_vehicle_time_min = 0.0;
    double avg_total_trip_time_min = 0.0;

    // Distance & Efficiency (km)
    double total_vmt_km = 0.0;
    double avg_distance_per_trip_km = 0.0;
    double total_passenger_km = 0.0;
    double avg_detour_ratio = 0.0;

    // Sharing & Occupancy
    int total_vehicle_trips = 0;
    double avg_passengers_per_trip = 0.0;
    int solo_trips = 0;
    int shared_trips = 0;
    double pooling_rate = 0.0;
    double avg_vehicle_occupancy = 0.0;

    // Vehicle Utilization
    int vehicles_used = 0;
    int vehicles_idle = 0;
    double loaded_vmt_km = 0.0;
    double empty_vmt_km = 0.0;
    double empty_ratio = 0.0;

    // NEW: Per-Vehicle-Type Breakdown
    std::map<std::string, VehicleTypeMetrics> per_vehicle_type;

    // NEW: Fuel & Emissions (to be implemented)
    double total_fuel_liters = 0.0;
    double fuel_per_km = 0.0;
    double total_co2_kg = 0.0;
    double co2_per_passenger_km = 0.0;
};

// Fuel parameters helper function
struct FuelParameters {
    double liters_per_100km;
    double co2_kg_per_liter;

    [[nodiscard]] double get_co2_per_100km() const {
        return liters_per_100km * co2_kg_per_liter;
    }
};

// Get fuel parameters for vehicle type
inline FuelParameters get_fuel_parameters(const std::string& vehicle_type) {
    if (vehicle_type == "Bus")
        return {27.8, 2.68};  // Diesel bus
    else if (vehicle_type == "Car")
        return {11.1, 2.31};  // Petrol car
    else if (vehicle_type == "Moped")
        return {3.5, 2.31};   // Petrol moped
    else if (vehicle_type == "Scooter")
        return {2.5, 2.31};   // Petrol scooter
    else
        return {11.1, 2.31};  // Default to car
}

// Calculate metrics from solution
AVServiceMetrics calculate_av_metrics(
    const std::vector<int>& commuter_nodes,
    int station_node,
    const std::vector<OrToolsVehicle>& vehicles,
    const QueryPathFn& query_path,
    const std::unordered_map<EdgeKey, EdgeAttr>& edge_tbl,
    const operations_research::RoutingModel& routing,
    const operations_research::Assignment* solution,
    const operations_research::RoutingIndexManager& manager,
    const std::vector<int64_t>& pickup_earliest_ms);

// Write metrics to JSON
void write_metrics_json(const AVServiceMetrics& metrics, const std::string& filename);

// Print summary to console
void print_metrics_summary(const AVServiceMetrics& metrics);

#endif //ROUTINGKIT_AV_METRICS_H