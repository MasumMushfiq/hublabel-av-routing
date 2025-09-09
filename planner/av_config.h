//
// Created by Md Mushfiq on 13/8/2025.
//

#ifndef AV_CONFIG_H
#define AV_CONFIG_H
#include "av_types.h"
#include <vector>

inline std::vector<AVType> default_av_types() {
    return {
            {"Car",     60.0, 4, 5},
            {"Moped",   45.0, 2, 4},
            {"Scooter", 30.0, 1, 3},
            {"Bike",    20.0, 1, 2}
    };
}

#endif //AV_CONFIG_H
