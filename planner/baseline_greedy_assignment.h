#ifndef BASELINE_GREEDY_ASSIGNMENT_H
#define BASELINE_GREEDY_ASSIGNMENT_H

#include "commuter.h"
#include "station.h"
#include "av_types.h"
#include "av_selection.h"   // <-- add
#include "edge_attrs.h"  // EdgeKey, EdgeAttr
#include <unordered_map>
#include <string>
#include <vector>
#include <functional>

// Simple record for an active AV
struct AV {
    int id;
    int capacity;
    int remaining;
    int station_node;
    std::string type;
    std::vector<int> assigned_commuters; // commuter ids
};

// Path query callback to decouple from labels.h
// Returns cost (int) and fills out_path with node ids.
using QueryPathFn = std::function<int(int /*s*/, int /*t*/, std::vector<int>& /*out_path*/)>;


// Overload A: simple (no custom selector, no edge table)
void run_greedy_baseline_assignment(
    const std::vector<Commuter>& commuters,
    const std::vector<Station>&  stations,
    const QueryPathFn&           query_path,
    const std::vector<AVType>&   av_types,
    const std::string&           assignments_csv,  // e.g., files/assignments.csv
    const std::string&           av_routes_csv     // e.g., files/av_routes.csv
);

// Overload B: custom selector (no edge table)
void run_greedy_baseline_assignment(
    const std::vector<Commuter>& commuters,
    const std::vector<Station>&  stations,
    const QueryPathFn&           query_path,
    const std::vector<AVType>&   av_types,
    const AVSelectFn&            select_av_type,
    const std::string&           assignments_csv,
    const std::string&           av_routes_csv
);

// Overload C: simple (no custom selector) + edge table (for time/length along path)
void run_greedy_baseline_assignment(
    const std::vector<Commuter>&                           commuters,
    const std::vector<Station>&                            stations,
    const QueryPathFn&                                     query_path,
    const std::vector<AVType>&                             av_types,
    const std::string&                                     assignments_csv,
    const std::string&                                     av_routes_csv,
    const std::unordered_map<EdgeKey, EdgeAttr>&           edge_tbl
);

// Overload D: custom selector + edge table  <<< the one your .cpp wrapper calls
void run_greedy_baseline_assignment(
    const std::vector<Commuter>&                           commuters,
    const std::vector<Station>&                            stations,
    const QueryPathFn&                                     query_path,
    const std::vector<AVType>&                             av_types,
    const AVSelectFn&                                      select_av_type,
    const std::string&                                     assignments_csv,
    const std::string&                                     av_routes_csv,
    const std::unordered_map<EdgeKey, EdgeAttr>&           edge_tbl
);

#endif // BASELINE_GREEDY_ASSIGNMENT_H
