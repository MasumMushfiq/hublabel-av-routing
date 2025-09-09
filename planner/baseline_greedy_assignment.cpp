#include "baseline_greedy_assignment.h"
#include <unordered_map>
#include <fstream>
#include <limits>
#include <sstream>
#include <algorithm>

#include "av_selection.h"
#include "edge_attrs.h"
#include "time_cost.h"   // <-- for distance_mm_along_path / time_ms_along_path

// --- tiny helpers ---
static std::string join_ints(const std::vector<int>& v){
    std::ostringstream oss;
    for(size_t i=0;i<v.size();++i){ if(i) oss << ' '; oss << v[i]; }
    return oss.str();
}

// Concatenate leg path onto route, dedup shared endpoint.
static void append_leg(std::vector<int>& route, const std::vector<int>& leg){
    if(leg.empty()) return;
    if(route.empty()){ route = leg; return; }
    if(!route.empty() && !leg.empty() && route.back()==leg.front()){
        route.insert(route.end(), leg.begin()+1, leg.end());
    }else{
        route.insert(route.end(), leg.begin(), leg.end());
    }
}

// Build pickup order: start = farthest from station (by callback cost),
// then nearest-neighbor among remaining; finally append station.
static void build_pickup_order(
    const std::vector<int>& pickup_nodes,
    int station_node,
    const QueryPathFn& query_path,
    std::vector<int>& ordered_pickups  // nodes, no station
){
    if(pickup_nodes.empty()){ ordered_pickups.clear(); return; }

    // 1) choose farthest from station
    int start_idx = 0;
    int best_cost = -1;
    for(size_t i=0;i<pickup_nodes.size();++i){
        std::vector<int> tmp;
        int c = query_path(pickup_nodes[i], station_node, tmp);
        if(c > best_cost){ best_cost = c; start_idx = (int)i; }
    }

    std::vector<bool> used(pickup_nodes.size(), false);
    ordered_pickups.reserve(pickup_nodes.size());
    int curr_idx = start_idx;
    used[curr_idx] = true;
    ordered_pickups.push_back(pickup_nodes[curr_idx]);

    // 2) nearest neighbor among remaining
    for(size_t k=1;k<pickup_nodes.size();++k){
        int next_idx = -1;
        int best = std::numeric_limits<int>::max();
        for(size_t j=0;j<pickup_nodes.size();++j){
            if(used[j]) continue;
            std::vector<int> tmp;
            int c = query_path(pickup_nodes[curr_idx], pickup_nodes[j], tmp);
            if(c > 0 && c < best){ best = c; next_idx = (int)j; }
        }
        if(next_idx == -1){
            // no reachable remaining; stop early
            break;
        }
        used[next_idx] = true;
        ordered_pickups.push_back(pickup_nodes[next_idx]);
        curr_idx = next_idx;
    }
}

// Build full AV route polyline by concatenating leg paths:
// pickup_0 -> pickup_1 -> ... -> pickup_n-1 -> station
static void build_vehicle_polyline(
    const std::vector<int>& ordered_pickups, // nodes
    int station_node,
    const QueryPathFn& query_path,
    std::vector<int>& route_nodes           // output nodes
){
    route_nodes.clear();
    if(ordered_pickups.empty()){
        // edge-case: no pickups; nothing to draw
        return;
    }
    // chain pickups
    for(size_t i=0;i+1<ordered_pickups.size();++i){
        std::vector<int> leg;
        int c = query_path(ordered_pickups[i], ordered_pickups[i+1], leg);
        (void)c;
        append_leg(route_nodes, leg);
    }
    // last pickup -> station
    std::vector<int> last_leg;
    int c = query_path(ordered_pickups.back(), station_node, last_leg);
    (void)c;
    append_leg(route_nodes, last_leg);
}

// helper: lookup max_kph for an AV type name
static double type_max_kph(const std::string& type_name, const std::vector<AVType>& av_types) {
    for (const auto& t : av_types) {
        if (t.name == type_name) return t.max_speed_kmph;
    }
    return 1e9; // fallback: effectively no cap
}

// Wrapper: default selector
void run_greedy_baseline_assignment(
    const std::vector<Commuter>& commuters,
    const std::vector<Station>& stations,
    const QueryPathFn& query_path,
    const std::vector<AVType>& av_types,
    const std::string& assignments_csv,
    const std::string& av_routes_csv,
    const std::unordered_map<EdgeKey, EdgeAttr>& edge_tbl
){
    run_greedy_baseline_assignment(
        commuters, stations, query_path, av_types,
        default_distance_selector,  // <-- default strategy
        assignments_csv, av_routes_csv, edge_tbl
    );
}

void run_greedy_baseline_assignment(
    const std::vector<Commuter>& commuters,
    const std::vector<Station>& stations,
    const QueryPathFn& query_path,
    const std::vector<AVType>& av_types,
    const AVSelectFn& select_av_type,
    const std::string& assignments_csv,
    const std::string& av_routes_csv,
    const std::unordered_map<EdgeKey, EdgeAttr>& edge_tbl
){
    // map: commuter id -> origin node (for route building later)
    std::unordered_map<int,int> commuter_origin;
    commuter_origin.reserve(commuters.size());
    for(const auto& c: commuters) commuter_origin[c.id] = c.origin_node;

    // type -> active AVs
    std::unordered_map<std::string, std::vector<AV>> active_fleet;
    std::unordered_map<std::string, int> next_av_id;

    // --- per-commuter assignments CSV ---
    std::ofstream out(assignments_csv);
    out << "commuter_id,av_type,av_id,cost,station_node,path,path_distance_mm,travel_time_ms,shared_with,status\n";

    // Greedy assignment (distance-based)
    for (const auto& c : commuters) {
        int best_cost = std::numeric_limits<int>::max();
        int best_station = -1;
        std::vector<int> best_path;

        // nearest feasible station by callback distance-cost (mm)
        for (const auto& s : stations) {
            std::vector<int> path;
            int cost = query_path(c.origin_node, s.node_id, path);
            if (cost > 0 && cost < best_cost) {
                best_cost   = cost;
                best_station= s.node_id;
                best_path   = std::move(path);
            }
        }

        if (best_station == -1) {
            out << c.id << ",,,,-1,,,"
                << ",,FAILED\n"; // keep column count
            continue;
        }

        // distance (km) from hub-label cost, for AV selection policy
        constexpr double MM_PER_KM = 1'000'000.0;
        double distance_km = (best_cost > 0) ? (static_cast<double>(best_cost) / MM_PER_KM) : 0.0;

        // Ask selector for prioritized type names
        AVSelectionContext ctx{distance_km, best_station, c.id};
        std::vector<std::string> type_priority = select_av_type(ctx, av_types);

        // Iterate types in that priority order
        bool assigned = false;
        for (const auto& type_name : type_priority)
        {
            auto& fleet = active_fleet[type_name];

            // 1) try existing AVs to same station
            for (auto& av : fleet)
            {
                if (av.station_node == best_station && av.remaining > 0)
                {
                    av.assigned_commuters.push_back(c.id);
                    av.remaining--;
                    assigned = true;

                    // Compute path metrics for THIS assignment (same path, capped by this type)
                    const long long d_mm_path = distance_mm_along_path(best_path, edge_tbl);
                    const double vmax = type_max_kph(av.type, av_types);
                    const int    t_ms = time_ms_along_path(best_path, edge_tbl, vmax);

                    out << c.id << "," << av.type << "," << av.id << "," << best_cost
                        << "," << best_station << ",\"" << join_ints(best_path) << "\","
                        << d_mm_path << "," << t_ms << ",\""
                        << join_ints(av.assigned_commuters) << "\",ASSIGNED\n";
                    break;
                }
            }
            if (assigned) break;

            // 2) launch new AV if fleet allows
            // capacity / fleet size of this type
            int cap = 1, fleet_size_limit = 0;
            for (const auto& t : av_types) if (t.name == type_name) { cap = t.capacity; fleet_size_limit = t.fleet_size; break; }

            if (static_cast<int>(fleet.size()) < fleet_size_limit)
            {
                AV new_av{
                    .id = next_av_id[type_name]++,
                    .capacity = cap,
                    .remaining = cap - 1,
                    .station_node = best_station,
                    .type = type_name,
                    .assigned_commuters = {c.id}
                };
                fleet.push_back(new_av);

                // Compute path metrics for THIS assignment (same path, capped by this type)
                const long long d_mm_path = distance_mm_along_path(best_path, edge_tbl);
                const double vmax = type_max_kph(new_av.type, av_types);
                const int    t_ms = time_ms_along_path(best_path, edge_tbl, vmax);

                out << c.id << "," << new_av.type << "," << new_av.id << "," << best_cost
                    << "," << best_station << ",\"" << join_ints(best_path) << "\","
                    << d_mm_path << "," << t_ms << ",\""
                    << join_ints(new_av.assigned_commuters) << "\",ASSIGNED\n";

                assigned = true;
                break;
            }
        }

        if (!assigned)
        {
            out << c.id << ",,,," << best_station << ",,,," << "FALLBACK\n";
        }
    }
    out.close();

    // --- per-AV route CSV (pickup tour + concatenated polyline) ---
    std::ofstream avout(av_routes_csv);
    avout << "av_type,av_id,station_node,pickup_order_commuters,pickup_nodes,route_nodes\n";

    for (auto& kv : active_fleet) {
        const std::string& type = kv.first;
        auto& fleet = kv.second;
        for (auto& av : fleet) {
            if (av.assigned_commuters.empty()) continue;

            // pickups -> node list
            std::vector<int> pickups_nodes;
            pickups_nodes.reserve(av.assigned_commuters.size());
            for(int cid : av.assigned_commuters){
                auto it = commuter_origin.find(cid);
                if(it != commuter_origin.end())
                    pickups_nodes.push_back(it->second);
            }
            if (pickups_nodes.empty()) continue;

            // order pickups (by nodes), then map back to commuter ids in that order
            std::vector<int> ordered_pickup_nodes;
            build_pickup_order(pickups_nodes, av.station_node, query_path, ordered_pickup_nodes);

            // derive ordered commuter ids by matching node->id (stable: first match, remove)
            std::vector<int> ordered_commuters;
            {
                std::vector<std::pair<int,int>> cid_node; // (cid, node)
                cid_node.reserve(av.assigned_commuters.size());
                for(int cid : av.assigned_commuters) cid_node.emplace_back(cid, commuter_origin[cid]);

                for(int n : ordered_pickup_nodes){
                    for(size_t i=0;i<cid_node.size();++i){
                        if(cid_node[i].second == n){
                            ordered_commuters.push_back(cid_node[i].first);
                            cid_node.erase(cid_node.begin()+i);
                            break;
                        }
                    }
                }
                // if any left unmatched (duplicate nodes), append remaining
                for(auto& p : cid_node) ordered_commuters.push_back(p.first);
            }

            // build concatenated polyline
            std::vector<int> route_nodes;
            build_vehicle_polyline(ordered_pickup_nodes, av.station_node, query_path, route_nodes);

            // write row
            avout << type << "," << av.id << "," << av.station_node << ",\""
                  << join_ints(ordered_commuters) << "\",\""
                  << join_ints(ordered_pickup_nodes) << "\",\""
                  << join_ints(route_nodes) << "\"\n";
        }
    }
    avout.close();
}