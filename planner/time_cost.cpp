//
// Created by Md Mushfiq on 9/9/2025.
//

#include "time_cost.h"
#include <cmath>

static inline int ms_from_len_speed(double length_m, double speed_kph){
    if (speed_kph < 0.1) speed_kph = 0.1;
    const double mps = speed_kph * (1000.0/3600.0);
    return static_cast<int>(std::ceil((length_m / mps) * 1000.0));
}

int time_ms_along_path(const std::vector<int>& path,
                       const std::unordered_map<EdgeKey, EdgeAttr>& tbl,
                       double vehicle_max_kph) {
    if (path.size() < 2) return 0;
    long long total = 0;
    for (size_t i = 0; i + 1 < path.size(); ++i) {
        auto it = tbl.find(edge_key(path[i], path[i+1]));
        if (it == tbl.end()) continue; // or throw if you prefer strictness
        double road_kph = it->second.speed_kph;
        double use_kph  = std::min(road_kph, vehicle_max_kph);
        total += ms_from_len_speed(it->second.length_m, use_kph);
    }
    return static_cast<int>(total);
}

long long distance_mm_along_path(const std::vector<int>& path,
                                 const std::unordered_map<EdgeKey, EdgeAttr>& tbl) {
    if (path.size() < 2) return 0;
    long long total = 0;
    for (size_t i = 0; i + 1 < path.size(); ++i) {
        auto it = tbl.find(edge_key(path[i], path[i+1]));
        if (it == tbl.end()) continue;
        total += static_cast<long long>(std::llround(it->second.length_m * 1000.0));
    }
    return total;
}