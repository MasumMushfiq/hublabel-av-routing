// planner/commuter.h
#ifndef COMMUTER_H
#define COMMUTER_H
#pragma once
#include <string>
#include <vector>

// Minutes since midnight [0..1440)
struct TimeWindow {
    int pickup_earliest_min = 0;   // e.g., "08:30" -> 510
    int drop_off_latest_min = 24 * 60; // e.g., "09:00" -> 540
};

struct Commuter {
    int id = -1;
    int origin_node = -1;
    int destination_node = -1;  // kept for future use (may differ from station)
    TimeWindow tw;
};

// Load commuters from a CSV with exact header:
// id,origin_node,destination_node,pickup_earliest,drop_off_latest
// Times are HH:MM (24h). Throws std::runtime_error on any parsing error.
std::vector<Commuter> load_commuters(const std::string& path);
#endif // COMMUTER_H
