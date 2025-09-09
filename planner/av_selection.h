//
// Created by Md Mushfiq on 14/8/2025.
//

#ifndef PLANNER_AV_SELECTION_H
#define PLANNER_AV_SELECTION_H

#include "av_types.h"
#include <string>
#include <vector>
#include <functional>

struct AVSelectionContext {
    double distance_km;   // origin → station distance (km)
    int station_node;     // selected station node
    int commuter_id;      // current commuter
};

// Returns a prioritized list of AV type names to try (e.g., {"Bike","Scooter","Moped","Car"}).
using AVSelectFn = std::function<std::vector<std::string>(
    const AVSelectionContext&,
    const std::vector<AVType>& /*available types in system*/
)>;

// Default: simple distance thresholds (tunable).
// - <= 2.0 km: Bike → Scooter → Moped → Car
// - <= 5.0 km: Moped → Scooter → Car → Bike
// - >  5.0 km: Car → Moped → Scooter → Bike
std::vector<std::string> default_distance_selector(
    const AVSelectionContext& ctx,
    const std::vector<AVType>& types
);

#endif // PLANNER_AV_SELECTION_H
