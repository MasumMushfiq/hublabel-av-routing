//
// Created by Md Mushfiq on 14/8/2025.
//

#include "av_selection.h"
#include <unordered_set>
#include <algorithm>

static std::vector<std::string> intersect_order(
    const std::vector<std::string>& pref,
    const std::vector<AVType>& types
){
    std::unordered_set<std::string> have;
    for(const auto& t : types) have.insert(t.name);
    std::vector<std::string> out;
    out.reserve(pref.size());
    for(const auto& n : pref){
        if(have.count(n)) out.push_back(n);
    }
    // Append any remaining types not listed in pref (stable)
    for(const auto& t : types){
        if(std::find(out.begin(), out.end(), t.name) == out.end())
            out.push_back(t.name);
    }
    return out;
}

std::vector<std::string> default_distance_selector(
    const AVSelectionContext& ctx,
    const std::vector<AVType>& types
){
    const double d = ctx.distance_km;

    // You can tweak these thresholds later or load from config.
    if(d <= 2.0){
        return intersect_order({"Bike","Scooter","Moped","Car"}, types);
    }else if(d <= 5.0){
        return intersect_order({"Moped","Scooter","Car","Bike"}, types);
    }else{
        return intersect_order({"Car","Moped","Scooter","Bike"}, types);
    }
}
