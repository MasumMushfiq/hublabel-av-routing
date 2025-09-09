//
// Created by Md Mushfiq on 9/9/2025.
//

#ifndef ROUTINGKIT_TIME_COST_H
#define ROUTINGKIT_TIME_COST_H
#include <vector>
#include <unordered_map>
#include "edge_attrs.h"

// Sum time (ms) along a node path using per-edge min(road_speed, vehicle_max_kph)
int time_ms_along_path(const std::vector<int>& path,
                       const std::unordered_map<EdgeKey, EdgeAttr>& tbl,
                       double vehicle_max_kph);

// (optional) also get distance in mm along that same path
long long distance_mm_along_path(const std::vector<int>& path,
                                 const std::unordered_map<EdgeKey, EdgeAttr>& tbl);
#endif //ROUTINGKIT_TIME_COST_H