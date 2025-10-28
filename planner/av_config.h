//
// Created by Md Mushfiq on 13/8/2025.
//

#ifndef AV_CONFIG_H
#define AV_CONFIG_H
#include "av_types.h"
#include <vector>

inline std::vector<AVType> default_av_types() {
    return {
            {"Car",     60.0, 4, 1},
            {"Moped",   45.0, 2, 0},
            {"Scooter", 30.0, 1, 0},
            {"Bike",    20.0, 1, 0}
    };
}

#endif //AV_CONFIG_H
