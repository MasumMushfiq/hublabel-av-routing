// analysis/comparison_utility.cpp
#include "comparison_utility.h"
#include <iostream>
#include <fstream>
#include <iomanip>
#include <cmath>

ComparisonMetrics compare_av_vs_baseline(
    const std::string& experiment_name,
    const PrivateVehicleBaseline& baseline,
    const AVServiceMetrics& av_system)
{
    ComparisonMetrics comp;
    comp.experiment_name = experiment_name;
    comp.baseline = baseline;
    comp.av_system = av_system;

    // Calculate percentage changes (positive = AV is better)
    if (baseline.total_vmt_km > 0) {
        comp.changes.vmt_change_pct =
            ((baseline.total_vmt_km - av_system.total_vmt_km) / baseline.total_vmt_km) * 100.0;
    }

    if (baseline.total_fuel_liters > 0) {
        comp.changes.fuel_change_pct =
            ((baseline.total_fuel_liters - av_system.total_fuel_liters) / baseline.total_fuel_liters) * 100.0;
    }

    if (baseline.total_co2_kg > 0) {
        comp.changes.co2_change_pct =
            ((baseline.total_co2_kg - av_system.total_co2_kg) / baseline.total_co2_kg) * 100.0;
    }

    if (baseline.avg_trip_time_min > 0) {
        comp.changes.trip_time_change_pct =
            ((baseline.avg_trip_time_min - av_system.avg_total_trip_time_min) / baseline.avg_trip_time_min) * 100.0;
    }

    // Additional metrics
    comp.changes.occupancy_improvement = av_system.avg_vehicle_occupancy - baseline.avg_occupancy;
    comp.changes.empty_miles_penalty = av_system.empty_ratio;
    comp.changes.detour_penalty = av_system.avg_detour_ratio - 1.0;
    comp.changes.service_rate_pct = av_system.service_rate * 100.0;
    comp.changes.pooling_rate_pct = av_system.pooling_rate;

    // Absolute differences
    comp.diffs.vmt_diff_km = av_system.total_vmt_km - baseline.total_vmt_km;
    comp.diffs.fuel_diff_L = av_system.total_fuel_liters - baseline.total_fuel_liters;
    comp.diffs.co2_diff_kg = av_system.total_co2_kg - baseline.total_co2_kg;
    comp.diffs.trip_time_diff_min = av_system.avg_total_trip_time_min - baseline.avg_trip_time_min;

    // Determine verdict
    if (av_system.total_commuters == 0 || baseline.total_commuters == 0) {
        comp.verdict = ComparisonMetrics::Verdict::INSUFFICIENT_DATA;
        comp.verdict_reason = "Insufficient data to compare";
    }
    else if (comp.changes.service_rate_pct < 95.0) {
        comp.verdict = ComparisonMetrics::Verdict::BASELINE_BETTER;
        comp.verdict_reason = "AV system failed to serve >95% of commuters";
    }
    else if (comp.changes.co2_change_pct > 10.0 && comp.changes.fuel_change_pct > 10.0) {
        // AV saves >10% CO₂ and fuel
        comp.verdict = ComparisonMetrics::Verdict::AV_BETTER;
        comp.verdict_reason = "AV system reduces fuel and CO₂ by >10%";
    }
    else if (comp.changes.co2_change_pct < -5.0 && comp.changes.fuel_change_pct < -5.0) {
        // AV uses >5% more CO₂ and fuel
        comp.verdict = ComparisonMetrics::Verdict::BASELINE_BETTER;
        comp.verdict_reason = "AV system uses >5% more fuel and emits more CO₂";
    }
    else {
        comp.verdict = ComparisonMetrics::Verdict::MIXED;
        comp.verdict_reason = "Trade-offs between metrics (some better, some worse)";
    }

    return comp;
}

void print_comparison_summary(const ComparisonMetrics& comp)
{
    std::cout << "\n";
    std::cout << "╔════════════════════════════════════════════════════════════════╗\n";
    std::cout << "║              AV SYSTEM vs BASELINE COMPARISON                  ║\n";
    std::cout << "╠════════════════════════════════════════════════════════════════╣\n";
    std::cout << "║ Experiment: " << std::left << std::setw(48) << comp.experiment_name << "║\n";
    std::cout << "╠════════════════════════════════════════════════════════════════╣\n";

    // Verdict
    std::cout << "║ VERDICT:                                                       ║\n";
    std::string verdict_str;
    switch (comp.verdict) {
        case ComparisonMetrics::Verdict::AV_BETTER:
            verdict_str = "✓ AV SYSTEM BETTER";
            break;
        case ComparisonMetrics::Verdict::BASELINE_BETTER:
            verdict_str = "✗ PRIVATE VEHICLES BETTER";
            break;
        case ComparisonMetrics::Verdict::MIXED:
            verdict_str = "≈ MIXED RESULTS";
            break;
        default:
            verdict_str = "? INSUFFICIENT DATA";
    }
    std::cout << "║   " << std::left << std::setw(60) << verdict_str << "║\n";
    std::cout << "║   Reason: " << std::left << std::setw(52) << comp.verdict_reason << "║\n";
    std::cout << "╠════════════════════════════════════════════════════════════════╣\n";

    std::cout << "║ SERVICE COVERAGE                                               ║\n";

    int baseline_reachable = comp.baseline.individual_distances_km.size();
    int baseline_total = comp.baseline.total_commuters;

    // Show total if different from reachable
    if (baseline_total != baseline_reachable) {
        std::cout << "║   Total Commuters:              " << std::setw(6) << baseline_total
                  << "                        ║\n";
        std::cout << "║   Reachable:                    " << std::setw(6) << baseline_reachable
                  << " (" << std::fixed << std::setprecision(1)
                  << (baseline_reachable * 100.0 / baseline_total) << "%)              ║\n";
    }

    std::cout << "║   Baseline Service:             " << std::setw(5) << std::fixed << std::setprecision(1)
              << 100.0 << "% (" << baseline_reachable << "/" << baseline_reachable << " served)     ║\n";
    std::cout << "║   AV System Service:            " << std::setw(5) << std::fixed << std::setprecision(1)
              << comp.changes.service_rate_pct << "% (" << comp.av_system.served_commuters << "/"
              << comp.av_system.total_commuters << " served)     ║\n";


    // Distance (VMT)
    std::cout << "║ VEHICLE-MILES TRAVELED (VMT)                                   ║\n";
    std::cout << "║   Baseline:                     " << std::setw(6) << std::fixed << std::setprecision(2)
              << comp.baseline.total_vmt_km << " km                    ║\n";
    std::cout << "║   AV System:                    " << std::setw(6) << std::fixed << std::setprecision(2)
              << comp.av_system.total_vmt_km << " km                    ║\n";
    std::cout << "║   Difference:                   " << std::setw(6) << std::fixed << std::setprecision(2)
              << comp.diffs.vmt_diff_km << " km ("
              << std::setw(5) << std::setprecision(1) << comp.changes.vmt_change_pct << "%)        ║\n";
    std::cout << "╠════════════════════════════════════════════════════════════════╣\n";

    // Fuel
    std::cout << "║ FUEL CONSUMPTION                                               ║\n";
    std::cout << "║   Baseline:                     " << std::setw(6) << std::fixed << std::setprecision(2)
              << comp.baseline.total_fuel_liters << " L                     ║\n";
    std::cout << "║   AV System:                    " << std::setw(6) << std::fixed << std::setprecision(2)
              << comp.av_system.total_fuel_liters << " L                     ║\n";
    std::cout << "║   Difference:                   " << std::setw(6) << std::fixed << std::setprecision(2)
              << comp.diffs.fuel_diff_L << " L ("
              << std::setw(5) << std::setprecision(1) << comp.changes.fuel_change_pct << "%)         ║\n";
    std::cout << "╠════════════════════════════════════════════════════════════════╣\n";

    // CO₂
    std::cout << "║ CO₂ EMISSIONS                                                  ║\n";
    std::cout << "║   Baseline:                     " << std::setw(6) << std::fixed << std::setprecision(2)
              << comp.baseline.total_co2_kg << " kg                    ║\n";
    std::cout << "║   AV System:                    " << std::setw(6) << std::fixed << std::setprecision(2)
              << comp.av_system.total_co2_kg << " kg                    ║\n";
    std::cout << "║   Difference:                   " << std::setw(6) << std::fixed << std::setprecision(2)
              << comp.diffs.co2_diff_kg << " kg ("
              << std::setw(5) << std::setprecision(1) << comp.changes.co2_change_pct << "%)        ║\n";
    std::cout << "╠════════════════════════════════════════════════════════════════╣\n";

    // Efficiency Metrics
    std::cout << "║ EFFICIENCY METRICS                                             ║\n";
    std::cout << "║   Baseline Occupancy:           " << std::setw(6) << std::fixed << std::setprecision(2)
              << comp.baseline.avg_occupancy << "                          ║\n";
    std::cout << "║   AV Occupancy:                 " << std::setw(6) << std::fixed << std::setprecision(2)
              << comp.av_system.avg_vehicle_occupancy << " (+"
              << std::setw(4) << std::setprecision(2) << comp.changes.occupancy_improvement << ")                ║\n";
    std::cout << "║   Baseline Empty Ratio:         " << std::setw(6) << std::fixed << std::setprecision(1)
              << comp.baseline.empty_miles_ratio << "%                       ║\n";
    std::cout << "║   AV Empty Ratio:               " << std::setw(6) << std::fixed << std::setprecision(1)
          << comp.av_system.empty_ratio << "%                       ║\n";  // FIX: Use direct value, multiply by 100
    std::cout << "║   AV Pooling Rate:              " << std::setw(6) << std::fixed << std::setprecision(1)
              << comp.changes.pooling_rate_pct << "%                       ║\n";
    std::cout << "║   AV Detour Penalty:            " << std::setw(6) << std::fixed << std::setprecision(2)
              << (comp.changes.detour_penalty + 1.0) << "x                        ║\n";  // FIX: add 1.0 back
    std::cout << "╠════════════════════════════════════════════════════════════════╣\n";

    // Time Performance
    std::cout << "║ TRIP TIME                                                      ║\n";
    std::cout << "║   Baseline Avg:                 " << std::setw(6) << std::fixed << std::setprecision(2)
              << comp.baseline.avg_trip_time_min << " min                   ║\n";
    std::cout << "║   AV System Avg:                " << std::setw(6) << std::fixed << std::setprecision(2)
              << comp.av_system.avg_total_trip_time_min << " min                   ║\n";

    // FIX: Better wording for time
    std::string time_change_label;
    if (comp.changes.trip_time_change_pct < 0) {
        time_change_label = " (AV slower)";
    } else if (comp.changes.trip_time_change_pct > 0) {
        time_change_label = " (AV faster)";
    } else {
        time_change_label = " (same)";
    }

    std::cout << "║   Difference:                   " << std::setw(6) << std::fixed << std::setprecision(2)
              << comp.diffs.trip_time_diff_min << " min ("
              << std::setw(5) << std::setprecision(1) << std::abs(comp.changes.trip_time_change_pct) << "%"
              << time_change_label << ")   ║\n";

    std::cout << "╚════════════════════════════════════════════════════════════════╝\n";
    std::cout << "\n";

}

void write_comparison_json(const ComparisonMetrics& comp, const std::string& filename)
{
    std::ofstream out(filename);
    if (!out.is_open()) {
        std::cerr << "Error: Could not open " << filename << " for writing\n";
        return;
    }
    
    out << std::fixed << std::setprecision(2);
    out << "{\n";
    out << "  \"experiment_name\": \"" << comp.experiment_name << "\",\n";
    
    // Verdict
    out << "  \"verdict\": {\n";
    std::string verdict_str;
    switch (comp.verdict) {
        case ComparisonMetrics::Verdict::AV_BETTER: verdict_str = "AV_BETTER"; break;
        case ComparisonMetrics::Verdict::BASELINE_BETTER: verdict_str = "BASELINE_BETTER"; break;
        case ComparisonMetrics::Verdict::MIXED: verdict_str = "MIXED"; break;
        default: verdict_str = "INSUFFICIENT_DATA";
    }
    out << "    \"result\": \"" << verdict_str << "\",\n";
    out << "    \"reason\": \"" << comp.verdict_reason << "\"\n";
    out << "  },\n";
    
    // Changes (percentage)
    out << "  \"changes_percent\": {\n";
    out << "    \"vmt\": " << comp.changes.vmt_change_pct << ",\n";
    out << "    \"fuel\": " << comp.changes.fuel_change_pct << ",\n";
    out << "    \"co2\": " << comp.changes.co2_change_pct << ",\n";
    out << "    \"trip_time\": " << comp.changes.trip_time_change_pct << ",\n";
    out << "    \"service_rate\": " << comp.changes.service_rate_pct << ",\n";
    out << "    \"pooling_rate\": " << comp.changes.pooling_rate_pct << "\n";
    out << "  },\n";
    
    // Absolute differences
    out << "  \"absolute_differences\": {\n";
    out << "    \"vmt_km\": " << comp.diffs.vmt_diff_km << ",\n";
    out << "    \"fuel_L\": " << comp.diffs.fuel_diff_L << ",\n";
    out << "    \"co2_kg\": " << comp.diffs.co2_diff_kg << ",\n";
    out << "    \"trip_time_min\": " << comp.diffs.trip_time_diff_min << "\n";
    out << "  },\n";
    
    // Raw metrics (baseline)
    out << "  \"baseline\": {\n";
    out << "    \"commuters\": " << comp.baseline.total_commuters << ",\n";
    out << "    \"vmt_km\": " << comp.baseline.total_vmt_km << ",\n";
    out << "    \"fuel_L\": " << comp.baseline.total_fuel_liters << ",\n";
    out << "    \"co2_kg\": " << comp.baseline.total_co2_kg << ",\n";
    out << "    \"avg_trip_time_min\": " << comp.baseline.avg_trip_time_min << "\n";
    out << "  },\n";
    
    // Raw metrics (AV)
    out << "  \"av_system\": {\n";
    out << "    \"commuters\": " << comp.av_system.total_commuters << ",\n";
    out << "    \"served\": " << comp.av_system.served_commuters << ",\n";
    out << "    \"vmt_km\": " << comp.av_system.total_vmt_km << ",\n";
    out << "    \"fuel_L\": " << comp.av_system.total_fuel_liters << ",\n";
    out << "    \"co2_kg\": " << comp.av_system.total_co2_kg << ",\n";
    out << "    \"avg_trip_time_min\": " << comp.av_system.avg_total_trip_time_min << ",\n";
    out << "    \"occupancy\": " << comp.av_system.avg_vehicle_occupancy << ",\n";
    out << "    \"empty_ratio\": " << comp.av_system.empty_ratio << "\n";
    out << "  }\n";
    
    out << "}\n";
    out.close();
    
    std::cout << "✓ Comparison written to: " << filename << "\n";
}

void write_comparison_csv(
    const std::vector<ComparisonMetrics>& comparisons,
    const std::string& filename)
{
    std::ofstream out(filename);
    if (!out.is_open()) {
        std::cerr << "Error: Could not open " << filename << " for writing\n";
        return;
    }
    
    // Header
    out << "Experiment,Commuters,Verdict,";
    out << "Baseline_VMT_km,AV_VMT_km,VMT_Change_%,";
    out << "Baseline_Fuel_L,AV_Fuel_L,Fuel_Change_%,";
    out << "Baseline_CO2_kg,AV_CO2_kg,CO2_Change_%,";
    out << "Service_Rate_%,Occupancy,Empty_Ratio_%,Pooling_Rate_%\n";
    
    // Data rows
    for (const auto& comp : comparisons) {
        out << std::fixed << std::setprecision(2);
        
        out << comp.experiment_name << ",";
        out << comp.baseline.total_commuters << ",";
        
        std::string verdict_str;
        switch (comp.verdict) {
            case ComparisonMetrics::Verdict::AV_BETTER: verdict_str = "AV_BETTER"; break;
            case ComparisonMetrics::Verdict::BASELINE_BETTER: verdict_str = "BASELINE_BETTER"; break;
            case ComparisonMetrics::Verdict::MIXED: verdict_str = "MIXED"; break;
            default: verdict_str = "INSUFFICIENT_DATA";
        }
        out << verdict_str << ",";
        
        out << comp.baseline.total_vmt_km << ",";
        out << comp.av_system.total_vmt_km << ",";
        out << comp.changes.vmt_change_pct << ",";
        
        out << comp.baseline.total_fuel_liters << ",";
        out << comp.av_system.total_fuel_liters << ",";
        out << comp.changes.fuel_change_pct << ",";
        
        out << comp.baseline.total_co2_kg << ",";
        out << comp.av_system.total_co2_kg << ",";
        out << comp.changes.co2_change_pct << ",";
        
        out << comp.changes.service_rate_pct << ",";
        out << comp.av_system.avg_vehicle_occupancy << ",";
        out << comp.changes.empty_miles_penalty << ",";
        out << comp.changes.pooling_rate_pct << "\n";
    }
    
    out.close();
    std::cout << "✓ Batch comparison CSV written to: " << filename << "\n";
}

void write_comparison_latex(
    const std::vector<ComparisonMetrics>& comparisons,
    const std::string& filename)
{
    std::ofstream out(filename);
    if (!out.is_open()) {
        std::cerr << "Error: Could not open " << filename << " for writing\n";
        return;
    }
    
    out << "\\begin{table}[h]\n";
    out << "\\centering\n";
    out << "\\caption{AV System vs Private Vehicle Baseline Comparison}\n";
    out << "\\label{tab:av_baseline_comparison}\n";
    out << "\\begin{tabular}{lrrrrrr}\n";
    out << "\\hline\n";
    out << "\\textbf{Experiment} & \\textbf{N} & \\textbf{VMT} & \\textbf{Fuel} & \\textbf{CO$_2$} & \\textbf{Occ.} & \\textbf{Empty} \\\\\n";
    out << " & & (\\%) & (\\%) & (\\%) & & (\\%) \\\\\n";
    out << "\\hline\n";
    
    out << std::fixed << std::setprecision(1);
    for (const auto& comp : comparisons) {
        out << comp.experiment_name << " & ";
        out << comp.baseline.total_commuters << " & ";
        out << comp.changes.vmt_change_pct << " & ";
        out << comp.changes.fuel_change_pct << " & ";
        out << comp.changes.co2_change_pct << " & ";
        out << std::setprecision(2) << comp.av_system.avg_vehicle_occupancy << " & ";
        out << std::setprecision(1) << comp.changes.empty_miles_penalty << " \\\\\n";
    }
    
    out << "\\hline\n";
    out << "\\end{tabular}\n";
    out << "\\end{table}\n";
    
    out.close();
    std::cout << "✓ LaTeX table written to: " << filename << "\n";
}
