#include "commuter.h"

#include <fstream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>
#include <cctype>

namespace {

// very small trim (spaces and tabs)
inline std::string trim(std::string s) {
    size_t a = 0, b = s.size();
    while (a < b && (s[a] == ' ' || s[a] == '\t' || s[a] == '\r')) ++a;
    while (b > a && (s[b - 1] == ' ' || s[b - 1] == '\t' || s[b - 1] == '\r' || s[b - 1] == '\n')) --b;
    return s.substr(a, b - a);
}

inline std::vector<std::string> split_csv_line(const std::string& line) {
    // No quoted fields support by design (strict schema).
    std::vector<std::string> out;
    std::string cur;
    std::istringstream is(line);
    while (std::getline(is, cur, ',')) out.push_back(trim(cur));
    return out;
}

inline int parse_int_strict(const std::string& s, const char* field_name, int row_no) {
    if (s.empty()) {
        std::ostringstream msg;
        msg << "Row " << row_no << ": empty integer for field '" << field_name << "'";
        throw std::runtime_error(msg.str());
    }
    // ensure only optional sign + digits
    size_t i = 0;
    if (s[0] == '-' || s[0] == '+') i = 1;
    for (; i < s.size(); ++i) {
        if (!std::isdigit(static_cast<unsigned char>(s[i]))) {
            std::ostringstream msg;
            msg << "Row " << row_no << ": non-integer value '" << s
                << "' for field '" << field_name << "'";
            throw std::runtime_error(msg.str());
        }
    }
    try {
        return std::stoi(s);
    } catch (...) {
        std::ostringstream msg;
        msg << "Row " << row_no << ": cannot convert '" << s
            << "' to int for field '" << field_name << "'";
        throw std::runtime_error(msg.str());
    }
}

inline int parse_hhmm_to_minutes(const std::string& s, const char* field_name, int row_no) {
    // Expect exactly HH:MM, 24-hour, HH in [0..23], MM in [0..59]
    if (s.size() != 5 || s[2] != ':'
        || !std::isdigit(static_cast<unsigned char>(s[0]))
        || !std::isdigit(static_cast<unsigned char>(s[1]))
        || !std::isdigit(static_cast<unsigned char>(s[3]))
        || !std::isdigit(static_cast<unsigned char>(s[4]))) {
        std::ostringstream msg;
        msg << "Row " << row_no << ": malformed time '" << s
            << "' for field '" << field_name << "' (expected HH:MM)";
        throw std::runtime_error(msg.str());
    }
    int hh = (s[0] - '0') * 10 + (s[1] - '0');
    int mm = (s[3] - '0') * 10 + (s[4] - '0');
    if (hh < 0 || hh > 23 || mm < 0 || mm > 59) {
        std::ostringstream msg;
        msg << "Row " << row_no << ": out-of-range time '" << s
            << "' for field '" << field_name << "'";
        throw std::runtime_error(msg.str());
    }
    return hh * 60 + mm;
}

} // namespace

std::vector<Commuter> load_commuters(const std::string& path) {
    std::ifstream in(path);
    if (!in.is_open()) {
        throw std::runtime_error("Cannot open commuters CSV: " + path);
    }

    std::string line;
    if (!std::getline(in, line)) {
        throw std::runtime_error("Empty commuters CSV: " + path);
    }

    // Exact header required
    const std::string expected_header =
        "id,origin_node,destination_node,pickup_earliest,drop_off_latest";
    if (trim(line) != expected_header) {
        std::ostringstream msg;
        msg << "Invalid commuters CSV header.\n  Expected: " << expected_header
            << "\n  Found:    " << trim(line);
        throw std::runtime_error(msg.str());
    }

    std::vector<Commuter> rows;
    int row_no = 1; // header is line 1; first data row is 2
    while (std::getline(in, line)) {
        ++row_no;
        if (trim(line).empty()) continue;

        auto cols = split_csv_line(line);
        if (cols.size() != 5) {
            std::ostringstream msg;
            msg << "Row " << row_no << ": expected 5 columns, found " << cols.size();
            throw std::runtime_error(msg.str());
        }

        Commuter c;
        c.id               = parse_int_strict(cols[0], "id", row_no);
        c.origin_node      = parse_int_strict(cols[1], "origin_node", row_no);
        c.destination_node = parse_int_strict(cols[2], "destination_node", row_no);
        c.tw.pickup_earliest_min  = parse_hhmm_to_minutes(cols[3], "pickup_earliest", row_no);
        c.tw.drop_off_latest_min  = parse_hhmm_to_minutes(cols[4], "drop_off_latest", row_no);

        // Optional sanity check: pickup <= dropoff (same-day assumption)
        if (c.tw.pickup_earliest_min > c.tw.drop_off_latest_min) {
            std::ostringstream msg;
            msg << "Row " << row_no << ": pickup_earliest (" << cols[3]
                << ") is after drop_off_latest (" << cols[4] << ")";
            throw std::runtime_error(msg.str());
        }

        rows.push_back(c);
    }

    return rows;
}