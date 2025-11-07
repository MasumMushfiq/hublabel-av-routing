//
// Created by Md Mushfiq on 7/11/2025.
//

#ifndef ROUTINGKIT_CONFIG_LOADER_H
#define ROUTINGKIT_CONFIG_LOADER_H

#include <string>
#include <vector>
#include <map>

#include "av_types.h"

// Vehicle configuration
struct VehicleConfig {
    std::string name;
    int capacity;
    double max_speed_kmph;
    double fuel_l_per_100km;
    double co2_kg_per_liter;
    int fleet_size;

    // Distance band [lower_km, upper_km]
    double lower_km;
    double upper_km;

    // Fixed cost (in km-equivalent)
    double fixed_cost_km_equiv;
};

// Penalty parameters
struct PenaltyConfig {
    double alpha;  // Penalty when distance < lower_km
    double beta;   // Penalty when distance > upper_km
};

// Solver configuration
struct SolverConfig {
    int time_limit_seconds;
    bool log_search;
    bool allow_partial_solution;
    std::string first_solution_strategy;
    std::string local_search_metaheuristic;
};

// Baseline parameters
struct BaselineConfig {
    double private_car_fuel_l_per_100km;
    double private_car_co2_kg_per_liter;
    double private_car_speed_kmph;
    std::string source_fuel;
    std::string source_co2;
};

// Complete experiment configuration
struct ExperimentConfig {
    std::string experiment_name;
    std::string description;

    std::vector<VehicleConfig> vehicle_types;
    PenaltyConfig penalty;
    SolverConfig solver;
    BaselineConfig baseline;
};

// Load configuration from JSON file
ExperimentConfig load_experiment_config(const std::string& config_path);


// Helper: Calculate smooth distance penalty
double calculate_smooth_penalty(
    double distance_km,
    double lower_km,
    double upper_km,
    double alpha,
    double beta
);

#endif //ROUTINGKIT_CONFIG_LOADER_H