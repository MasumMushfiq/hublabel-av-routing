// analysis/comparison_utility.h
#ifndef ROUTINGKIT_COMPARISON_UTILITY_H
#define ROUTINGKIT_COMPARISON_UTILITY_H

#include "baseline_calculator.h"
#include "av_metrics.h"
#include <string>
#include <vector>
#include <map>

/**
 * Comparison metrics between AV system and private vehicle baseline
 */
struct ComparisonMetrics {
    // Identifiers
    std::string experiment_name;
    std::string scenario_description;
    
    // Raw metrics
    PrivateVehicleBaseline baseline;
    AVServiceMetrics av_system;
    
    // Percentage changes (positive = AV better than baseline)
    struct Changes {
        double vmt_change_pct = 0.0;           // Negative = AV uses more VMT
        double fuel_change_pct = 0.0;          // Negative = AV uses more fuel
        double co2_change_pct = 0.0;           // Negative = AV emits more CO₂
        double trip_time_change_pct = 0.0;     // Negative = AV takes longer
        
        // Additional metrics
        double occupancy_improvement = 0.0;     // AV occupancy - baseline occupancy
        double empty_miles_penalty = 0.0;       // AV empty ratio (baseline always 0)
        double detour_penalty = 0.0;            // AV detour ratio - 1.0
        
        // Service quality
        double service_rate_pct = 0.0;          // AV service rate (baseline always 100%)
        double pooling_rate_pct = 0.0;          // AV pooling rate (baseline always 0%)
    } changes;
    
    // Absolute differences
    struct AbsoluteDiffs {
        double vmt_diff_km = 0.0;
        double fuel_diff_L = 0.0;
        double co2_diff_kg = 0.0;
        double trip_time_diff_min = 0.0;
    } diffs;
    
    // Overall assessment
    enum class Verdict {
        AV_BETTER,        // AV system clearly better (fuel/CO₂ < baseline)
        BASELINE_BETTER,  // Private vehicles better (fuel/CO₂ < AV)
        MIXED,            // Some metrics better, some worse
        INSUFFICIENT_DATA // Not enough data to compare
    } verdict = Verdict::INSUFFICIENT_DATA;
    
    std::string verdict_reason;
};

/**
 * Compare AV system against private vehicle baseline
 */
ComparisonMetrics compare_av_vs_baseline(
    const std::string& experiment_name,
    const PrivateVehicleBaseline& baseline,
    const AVServiceMetrics& av_system
);

/**
 * Print comparison summary to console
 */
void print_comparison_summary(const ComparisonMetrics& comp);

/**
 * Write comparison to JSON
 */
void write_comparison_json(const ComparisonMetrics& comp, const std::string& filename);

/**
 * Write comparison to CSV (for batch experiments)
 */
void write_comparison_csv(
    const std::vector<ComparisonMetrics>& comparisons,
    const std::string& filename
);

/**
 * Generate LaTeX table for Overleaf
 */
void write_comparison_latex(
    const std::vector<ComparisonMetrics>& comparisons,
    const std::string& filename
);

#endif //ROUTINGKIT_COMPARISON_UTILITY_H
