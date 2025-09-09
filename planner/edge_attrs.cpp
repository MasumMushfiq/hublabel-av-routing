//
// Created by Md Mushfiq on 9/9/2025.
//
#include "edge_attrs.h"
#include <fstream>
#include <sstream>
#include <stdexcept>

std::unordered_map<EdgeKey, EdgeAttr> load_edge_attrs(const std::string& path) {
    std::unordered_map<EdgeKey, EdgeAttr> tbl;
    tbl.reserve(1<<20);
    std::ifstream in(path);
    if (!in.is_open()) throw std::runtime_error("open failed: " + path);

    int u, v;
    double len, sp;
    while (in >> u >> v >> len >> sp) {
        tbl.emplace(edge_key(u, v), EdgeAttr{len, sp});
    }
    return tbl;
}