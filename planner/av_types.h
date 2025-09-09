//
// Created by Md Mushfiq on 13/8/2025.
//

#ifndef AV_TYPES_H
#define AV_TYPES_H

#include <string>

struct AVType {
    std::string name;       // e.g., "Car"
    double max_speed_kmph;  // simple speed model for now
    int capacity;           // seats (1 for scooter/bike, etc.)
    int fleet_size;         // how many vehicles of this type available
};

#endif //AV_TYPES_H
