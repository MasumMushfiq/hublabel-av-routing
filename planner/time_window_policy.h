// time_window_policy.h
// ---------------------------------------------------------------------------
// Modular time-window assignment for commuter generation.
//
// Design
// ------
// TimeWindowPolicy  – pure abstract interface; assign() takes a commuter index
//                     and an RNG, returns a TimeWindow {pickup_earliest,
//                     drop_off_latest} as "HH:MM" strings.
//
// Concrete policies (add new ones here without touching the builder):
//   FixedPolicy       – every commuter gets the same fixed window (legacy behaviour)
//   NormalPeakPolicy  – drop_off_latest ~ N(peak, σ) clamped to
//                       [peak - cutoff, peak + cutoff]; σ = cutoff / 3  so that
//                       ±3σ spans the full cutoff band (~99.7 % of mass inside).
//                       pickup_earliest = drop_off_latest - window_width.
//
// Future policies to add (example):
//   MykiPolicy        – read per-commuter tap-on times from a Myki CSV,
//                       derive window from observed travel behaviour.
//   HistogramPolicy   – sample from an empirical hourly distribution.
// ---------------------------------------------------------------------------

#pragma once

#include <algorithm>
#include <cmath>
#include <random>
#include <stdexcept>
#include <string>

// ---------------------------------------------------------------------------
// Helpers: HH:MM <-> minutes-since-midnight
// ---------------------------------------------------------------------------

/// Parse "HH:MM" -> total minutes since midnight.  Throws on bad format.
inline int parse_hhmm(const std::string& s) {
    if (s.size() < 5 || s[2] != ':')
        throw std::invalid_argument("Time must be HH:MM, got: " + s);
    int h = std::stoi(s.substr(0, 2));
    int m = std::stoi(s.substr(3, 2));
    if (h < 0 || h > 23 || m < 0 || m > 59)
        throw std::invalid_argument("Time out of range: " + s);
    return h * 60 + m;
}

/// Format total minutes since midnight -> "HH:MM".
inline std::string format_hhmm(int total_minutes) {
    // clamp to [0, 1439] to handle floating-point rounding at boundaries
    total_minutes = std::max(0, std::min(1439, total_minutes));
    char buf[6];
    std::snprintf(buf, sizeof(buf), "%02d:%02d",
                  total_minutes / 60, total_minutes % 60);
    return std::string(buf);
}

// ---------------------------------------------------------------------------
// Result type
// ---------------------------------------------------------------------------

struct TimeWindow {
    std::string pickup_earliest;   // "HH:MM"
    std::string drop_off_latest;   // "HH:MM"
};

// ---------------------------------------------------------------------------
// Abstract base
// ---------------------------------------------------------------------------

class TimeWindowPolicy {
public:
    virtual ~TimeWindowPolicy() = default;

    /// Assign a time window to the i-th commuter (0-based).
    /// `rng` is provided so policies can be deterministic given a seed.
    virtual TimeWindow assign(std::size_t commuter_index,
                              std::mt19937_64& rng) const = 0;

    /// Human-readable description shown in the builder's startup banner.
    virtual std::string description() const = 0;
};

// ---------------------------------------------------------------------------
// Policy 1 – Fixed (legacy)
// ---------------------------------------------------------------------------
// Every commuter gets the same window regardless of index or RNG.
// Equivalent to the old PICKUP_EARLIEST_DEFAULT / DROP_OFF_LATEST_DEFAULT.
//
// CLI: --tw-policy fixed  (default when no policy flags are supplied)

class FixedPolicy : public TimeWindowPolicy {
public:
    /// @param pickup_earliest  "HH:MM"
    /// @param drop_off_latest  "HH:MM"
    FixedPolicy(const std::string& pickup_earliest,
                const std::string& drop_off_latest)
        : pickup_(pickup_earliest), dropoff_(drop_off_latest)
    {
        // validate at construction time
        parse_hhmm(pickup_earliest);
        parse_hhmm(drop_off_latest);
    }

    TimeWindow assign(std::size_t /*index*/, std::mt19937_64& /*rng*/) const override {
        return { pickup_, dropoff_ };
    }

    std::string description() const override {
        return "FixedPolicy: every commuter gets ["
               + pickup_ + ", " + dropoff_ + "]";
    }

private:
    std::string pickup_;
    std::string dropoff_;
};

// ---------------------------------------------------------------------------
// Policy 2 – NormalPeak
// ---------------------------------------------------------------------------
// Models a morning-peak surge with a Gaussian arrival-deadline distribution.
//
// Parameters (all configurable via CLI):
//   peak_time_minutes    – mode of the distribution (e.g. 480 = 08:00)
//   cutoff_minutes       – half-width of the acceptable window around the peak;
//                          samples are CLAMPED (not rejected) to
//                          [peak - cutoff, peak + cutoff].
//                          σ = cutoff / 3  ⟹ ±3σ = cutoff boundary.
//   window_width_minutes – fixed width of each commuter's individual pickup
//                          window:  pickup_earliest = drop_off_latest - width.
//
// Sampled value = drop_off_latest (deadline to be at station).
// pickup_earliest       = drop_off_latest - window_width_minutes.
//
// NOTE on clamping vs rejection sampling
// ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
// We clamp rather than reject-and-resample so the function always terminates
// in O(1).  The practical effect is a small pile-up of commuters exactly at
// the cutoff boundaries, which is realistic (hard schedule constraints).
// If you prefer hard truncation without boundary pile-up, switch to a
// std::normal_distribution inside a rejection loop with a finite retry cap.
//
// CLI: --tw-policy normal_peak  --peak-time HH:MM
//      --cutoff-minutes N  --window-width-minutes M

class NormalPeakPolicy : public TimeWindowPolicy {
public:
    /// @param peak_time_minutes      Mode of the Gaussian (minutes since midnight)
    /// @param cutoff_minutes         Half-width of the clamped range (> 0)
    /// @param window_width_minutes   Width of each commuter's individual window (> 0)
    NormalPeakPolicy(int peak_time_minutes,
                     int cutoff_minutes,
                     int window_width_minutes)
        : peak_(peak_time_minutes)
        , cutoff_(cutoff_minutes)
        , window_width_(window_width_minutes)
    {
        if (cutoff_minutes <= 0)
            throw std::invalid_argument("cutoff_minutes must be > 0");
        if (window_width_minutes <= 0)
            throw std::invalid_argument("window_width_minutes must be > 0");

        // σ chosen so that ±3σ = cutoff boundary  ⟹  σ = cutoff / 3
        sigma_ = static_cast<double>(cutoff_minutes) / 3.0;
        dist_  = std::normal_distribution<double>(
                     static_cast<double>(peak_), sigma_);
    }

    TimeWindow assign(std::size_t /*index*/, std::mt19937_64& rng) const override {
        // Sample drop_off_latest from N(peak, σ), clamped to [peak-cutoff, peak+cutoff]
        double raw      = dist_(rng);
        double clamped  = std::max(static_cast<double>(peak_ - cutoff_),
                                   std::min(static_cast<double>(peak_ + cutoff_), raw));
        int dropoff_min = static_cast<int>(std::round(clamped));
        int pickup_min  = dropoff_min - window_width_;

        // Guard against pickup going before midnight (unlikely but defensive)
        if (pickup_min < 0) {
            pickup_min  = 0;
            dropoff_min = window_width_;
        }

        return { format_hhmm(pickup_min), format_hhmm(dropoff_min) };
    }

    std::string description() const override {
        return "NormalPeakPolicy: drop_off_latest ~ N("
               + format_hhmm(peak_) + ", σ="
               + std::to_string(static_cast<int>(std::round(sigma_))) + " min)"
               + "  clamped to ["
               + format_hhmm(peak_ - cutoff_) + ", "
               + format_hhmm(peak_ + cutoff_) + "]"
               + "  window_width=" + std::to_string(window_width_) + " min";
    }

    // ---- accessors (useful for unit tests / diagnostics) ----
    int  peak()         const { return peak_; }
    int  cutoff()       const { return cutoff_; }
    int  window_width() const { return window_width_; }
    double sigma()      const { return sigma_; }

private:
    int    peak_;
    int    cutoff_;
    int    window_width_;
    double sigma_;
    mutable std::normal_distribution<double> dist_;  // mutable: operator() is non-const
};

// ---------------------------------------------------------------------------
// Factory helper used by the CLI parser in build_commuters_reachable.cpp
// ---------------------------------------------------------------------------
// Returns a heap-allocated policy; caller owns it (or wrap in unique_ptr).
// Supported policy names: "fixed", "normal_peak"
//
// For "fixed":
//   extra[0] = pickup_earliest (HH:MM)
//   extra[1] = drop_off_latest (HH:MM)
//
// For "normal_peak":
//   extra[0] = peak_time       (HH:MM)
//   extra[1] = cutoff_minutes  (integer string)
//   extra[2] = window_width_minutes (integer string)

inline TimeWindowPolicy* make_policy(
    const std::string& name,
    const std::vector<std::string>& extra)
{
    if (name == "fixed") {
        if (extra.size() < 2)
            throw std::invalid_argument(
                "fixed policy needs: pickup_earliest drop_off_latest");
        return new FixedPolicy(extra[0], extra[1]);
    }
    if (name == "normal_peak") {
        if (extra.size() < 3)
            throw std::invalid_argument(
                "normal_peak policy needs: peak_time(HH:MM) "
                "cutoff_minutes window_width_minutes");
        int peak   = parse_hhmm(extra[0]);
        int cutoff = std::stoi(extra[1]);
        int width  = std::stoi(extra[2]);
        return new NormalPeakPolicy(peak, cutoff, width);
    }
    throw std::invalid_argument("Unknown time-window policy: " + name
        + "  (supported: fixed, normal_peak)");
}
