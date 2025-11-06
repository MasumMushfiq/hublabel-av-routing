//
// Created by Md Mushfiq on 29/10/2025.
//

#ifndef ROUTINGKIT_AV_METRICS_H
#define ROUTINGKIT_AV_METRICS_H

#include <string>
#include <vector>
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
};

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