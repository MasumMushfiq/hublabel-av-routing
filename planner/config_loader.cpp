// planner/config_loader.cpp
#include "config_loader.h"
#include "json.hpp"
#include <fstream>
#include <iostream>

using json = nlohmann::json;

ExperimentConfig load_experiment_config(const std::string& config_path)
{
    ExperimentConfig config;

    std::ifstream file(config_path);
    if (!file.is_open()) {
        std::cerr << "❌ Failed to open config file: " << config_path << "\n";
        std::cerr << "Using default configuration...\n";
        return config;
    }

    try {
        json j;
        file >> j;

        // Load experiment info
        config.experiment_name = j.value("experiment_name", "unnamed");
        config.description = j.value("description", "");

        // Load vehicle types
        if (j.contains("fleet") && j["fleet"].contains("vehicle_types")) {
            for (const auto& v : j["fleet"]["vehicle_types"]) {
                VehicleConfig vc;
                vc.name = v.value("name", "Unknown");
                vc.capacity = v.value("capacity", 1);
                vc.max_speed_kmph = v.value("max_speed_kmph", 60.0);
                vc.fuel_l_per_100km = v.value("fuel_l_per_100km", 10.0);
                vc.co2_kg_per_liter = v.value("co2_kg_per_liter", 2.31);
                vc.fleet_size = v.value("fleet_size", 1);

                if (v.contains("distance_band")) {
                    vc.lower_km = v["distance_band"].value("lower_km", 0.0);
                    vc.upper_km = v["distance_band"].value("upper_km", 10.0);
                }

                vc.fixed_cost_km_equiv = v.value("fixed_cost_km_equiv", 1.0);

                config.vehicle_types.push_back(vc);
            }
        }

        // Load penalty parameters
        if (j.contains("penalty_parameters")) {
            config.penalty.alpha = j["penalty_parameters"].value("alpha", 0.8);
            config.penalty.beta = j["penalty_parameters"].value("beta", 2.0);
        }

        // Load solver config
        if (j.contains("solver_config")) {
            config.solver.time_limit_seconds = j["solver_config"].value("time_limit_seconds", 30);
            config.solver.log_search = j["solver_config"].value("log_search", false);
            config.solver.allow_partial_solution = j["solver_config"].value("allow_partial_solution", true);
            config.solver.first_solution_strategy = j["solver_config"].value("first_solution_strategy", "PARALLEL_CHEAPEST_INSERTION");
            config.solver.local_search_metaheuristic = j["solver_config"].value("local_search_metaheuristic", "GUIDED_LOCAL_SEARCH");
        }

        // Load baseline parameters
        if (j.contains("baseline_parameters")) {
            config.baseline.private_car_fuel_l_per_100km = j["baseline_parameters"].value("private_car_fuel_l_per_100km", 11.1);
            config.baseline.private_car_co2_kg_per_liter = j["baseline_parameters"].value("private_car_co2_kg_per_liter", 2.31);
            config.baseline.private_car_speed_kmph = j["baseline_parameters"].value("private_car_speed_kmph", 60.0);
            config.baseline.source_fuel = j["baseline_parameters"].value("source_fuel", "");
            config.baseline.source_co2 = j["baseline_parameters"].value("source_co2", "");
        }

        std::cout << "✓ Loaded configuration: " << config.experiment_name << "\n";
        std::cout << "  - " << config.vehicle_types.size() << " vehicle types\n";
        std::cout << "  - Penalty: α=" << config.penalty.alpha << ", β=" << config.penalty.beta << "\n";

    } catch (const json::exception& e) {
        std::cerr << "❌ JSON parsing error: " << e.what() << "\n";
    }

    return config;
}

// Smooth penalty function
double calculate_smooth_penalty(
    double distance_km,
    double lower_km,
    double upper_km,
    double alpha,
    double beta)
{
    if (distance_km >= lower_km && distance_km <= upper_km) {
        return 1.0;
    }

    if (distance_km < lower_km) {
        if (lower_km <= 0.0) return 1.0;
        return 1.0 + alpha * (lower_km - distance_km) / lower_km;
    }

    if (distance_km > upper_km) {
        if (upper_km <= 0.0) return 1.0 + beta * distance_km;
        return 1.0 + beta * (distance_km - upper_km) / upper_km;
    }

    return 1.0;
}
