#ifndef AV_ASSIGNMENT_H
#define AV_ASSIGNMENT_H

#include "commuter.h"
#include "station.h"
#include "../src/labels.h"
#include "../src/graph.h"  // for NodeID
#include <vector>

struct FirstMileResult {
    bool success;
    int cost;
    int station_node;
    std::vector<NodeID> path;
};

/**
 * @brief Assign the nearest feasible station to a commuter using AV and hub label.
 *
 * @param commuter The commuter with origin node and time window
 * @param stations List of candidate train stations
 * @param label Preloaded hub label structure
 * @param rank node_id → rank
 * @param inv  rank → node_id
 * @return FirstMileResult object with status, cost, station, and path
 */
FirstMileResult assign_first_mile(
    const Commuter& commuter,
    const std::vector<Station>& stations,
    const DPLabel& label,
    const std::vector<NodeID>& rank,
    const std::vector<NodeID>& inv
);

#endif
