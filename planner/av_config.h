//
// Created by Md Mushfiq on 13/8/2025.
//

#ifndef AV_CONFIG_H
#define AV_CONFIG_H
#include "av_types.h"
#include <vector>

inline std::vector<AVType> default_av_types() {
    return {
        // name, max_speed_kmph, capacity, fleet_size
            {"Bus",     60.0, 12, 27.8, 2.68, 10},   // Large shuttle for high demand
            {"Car",     80.0, 4, 11.1, 2.31, 20},   // Standard vehicle
            {"Moped",   45.0, 2, 3.5, 2.31, 30},   // Small 2-seater
            {"Scooter", 30.0, 1,  2.5, 2.31, 40}    // Single passenger (or small 2-wheeler)
    };
}

#endif //AV_CONFIG_H
