#include "av_assignment.h"
#include <limits>
#include "../src/labels.h"
#include "../src/graph.h"
#include "station.h"
#include "commuter.h"
#include "coverage_ordering_path.h"

#include <iostream>

FirstMileResult assign_first_mile(
    const Commuter& commuter,
    const std::vector<Station>& stations,
    const DPLabel& label,
    const std::vector<NodeID>& rank,
    const std::vector<NodeID>& inv
) {
    int min_cost = std::numeric_limits<int>::max();
    int best_station = -1;
    std::vector<NodeID> best_path;

    for (const auto& station : stations) {
        std::vector<NodeID> path;
        int cost = label.query_path(commuter.origin_node, station.node_id, rank, inv, path);
        if (cost < min_cost && cost >= 0) {
            min_cost = cost;
            best_station = station.node_id;
            best_path = path;
        }
    }

    FirstMileResult result;
    result.success = (best_station != -1);
    result.cost = min_cost;
    result.station_node = best_station;
    result.path = best_path;

    return result;
}
