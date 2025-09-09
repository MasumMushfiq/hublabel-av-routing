//
// Created by Md Mushfiq on 9/9/2025.
//

#ifndef ROUTINGKIT_EDGE_ATTRS_H
#define ROUTINGKIT_EDGE_ATTRS_H
#include <unordered_map>
#include <string>
#include <cstdint>

struct EdgeAttr {
    double length_m;
    double speed_kph; // road limit parsed from OSM
};

using EdgeKey = uint64_t; // pack (u,v) into 64 bits
inline EdgeKey edge_key(int u, int v) {
    return (static_cast<uint64_t>(static_cast<uint32_t>(u)) << 32) |
           static_cast<uint32_t>(v);
}

// Load text file with lines: "u v length_m speed_kph"
std::unordered_map<EdgeKey, EdgeAttr> load_edge_attrs(const std::string& path);
#endif //ROUTINGKIT_EDGE_ATTRS_H