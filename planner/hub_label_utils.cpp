#include "hub_label_utils.h"

#include <fstream>
#include <stdexcept>
#include <iostream>

// Include heavy headers ONLY here, in one TU.
// This prevents multiple definitions of globals from labels/graph headers.
#include "../src/graph.h"   // NodeID typedef
#include "../src/labels.h"  // DPLabel

struct LabelPack {
    DPLabel label;
    std::vector<NodeID> rank;  // node_id -> rank
    std::vector<NodeID> inv;   // rank -> node_id
};

static LabelPack g_dist;   // distance labels (mm)
static LabelPack g_time;   // time labels (ms)
static bool g_dist_loaded = false;
static bool g_time_loaded = false;

static void load_ordering(const std::string& order_file_path,
                          std::vector<NodeID>& rank,
                          std::vector<NodeID>& inv)
{
    std::ifstream in(order_file_path);
    if (!in.is_open()) {
        throw std::runtime_error("Could not open order file: " + order_file_path);
    }

    std::vector<NodeID> order;
    NodeID x;
    while (in >> x) order.push_back(x);

    rank.assign(order.size(), 0);
    inv.assign(order.size(), 0);

    for (size_t i = 0; i < order.size(); ++i) {
        rank[order[i]] = static_cast<NodeID>(i);
        inv[i] = order[i];
    }
}

static void load_pack(const std::string& prefix, LabelPack& P)
{
    const std::string order_file = prefix + ".dorder";
    const std::string label_file = prefix + ".dlabel";

    load_ordering(order_file, P.rank, P.inv);
    P.label.load_labels(label_file.c_str()); // returns void in your codebase
}

// Always call the const 5-arg overload:
//   query_path(s, t, const rank, const inv, path) const
static int query_cost(const LabelPack& P, int u, int v, std::vector<int>* path_out)
{
    const NodeID su = static_cast<NodeID>(u);
    const NodeID sv = static_cast<NodeID>(v);

    if (path_out) {
        path_out->clear();
        return P.label.query_path(su, sv, P.rank, P.inv, *path_out);
    } else {
        std::vector<int> tmp;
        return P.label.query_path(su, sv, P.rank, P.inv, tmp);
    }
}


bool init_labels(const std::string& dist_prefix, const std::string& time_prefix)
{
    g_dist_loaded = g_time_loaded = false;

    try {
        load_pack(dist_prefix, g_dist);
        g_dist_loaded = true;
        std::cerr << "[labels] loaded distance pack: " << dist_prefix << "\n";
    } catch (const std::exception& e) {
        std::cerr << "[labels] distance load failed: " << e.what() << "\n";
    }

    try {
        load_pack(time_prefix, g_time);
        g_time_loaded = true;
        std::cerr << "[labels] loaded time pack: " << time_prefix << "\n";
    } catch (const std::exception& e) {
        std::cerr << "[labels] time load failed: " << e.what() << "\n";
    }

    return g_dist_loaded && g_time_loaded;
}


bool init_distance_labels(const std::string& dist_prefix) {
    g_dist_loaded = false;

    try {
        load_pack(dist_prefix, g_dist);
        g_dist_loaded = true;
        std::cerr << "[labels] loaded distance pack: " << dist_prefix << "\n";
    } catch (const std::exception& e) {
        std::cerr << "[labels] distance load failed: " << e.what() << "\n";
    }
    return g_dist_loaded;
}

int distance_mm(int u, int v, std::vector<int>* path_out)
{
    if (!g_dist_loaded) {
        std::cerr << "[labels] distance labels not loaded\n";
        return -1;
    }
    return query_cost(g_dist, u, v, path_out); // mm
}

int time_ms(int u, int v, std::vector<int>* path_out)
{
    if (!g_time_loaded) {
        std::cerr << "[labels] time labels not loaded\n";
        return -1;
    }
    return query_cost(g_time, u, v, path_out); // ms
}