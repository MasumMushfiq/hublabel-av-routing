//
// Created by Md Mushfiq on 10/9/2025.
//

#ifndef ROUTINGKIT_ORTOOLS_SOLVER_H
#define ROUTINGKIT_ORTOOLS_SOLVER_H
#pragma once
#include <string>
#include <vector>
#include <unordered_map>
#include <functional>

// OR-Tools (9.14) headers
#include "ortools/constraint_solver/routing.h"
#include "ortools/constraint_solver/routing_index_manager.h"
#include "ortools/constraint_solver/routing_parameters.h"

#include "edge_attrs.h"
#include "av_selection.h"

// QueryPathFn signature you already use elsewhere:
//   int query_path(int s, int t, std::vector<int>& out_path);
using QueryPathFn = std::function<int(int,int,std::vector<int>&)>;

struct OrToolsConfig {
    int time_limit_seconds = 10;     // wall time cap
    bool log_search = false;         // OR-Tools solver logs
    bool allow_partial_solution = true;  // ADD THIS - make customers optional
};

// Minimal vehicle info for PDPTW (capacity in people)
struct OrToolsVehicle {
    std::string type;  // "Bike"/"Scooter"/"Moped"/"Car"
    int capacity = 1;
    double max_speed_kmph = 60.0; // default
};


bool solve_cvrp_distance(
    const std::vector<int>& commuter_nodes,
    int station_node,
    const std::vector<OrToolsVehicle>& vehicles,
    const QueryPathFn& query_path,
    const std::unordered_map<EdgeKey, EdgeAttr>& /*edge_tbl*/, // kept for signature parity
    const std::string& assignments_csv,
    const std::string& av_routes_csv,
    const OrToolsConfig& cfg);

// Add this overload with time windows
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
    const OrToolsConfig& cfg);

#endif //ROUTINGKIT_ORTOOLS_SOLVER_H