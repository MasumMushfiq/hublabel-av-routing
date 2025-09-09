#include "station.h"
#include <fstream>
#include <sstream>
#include <iostream>

/**
 * @brief Loads station data from a CSV file.
 *
 * Reads each line of the file and converts it to a Station object. The expected
 * format is: name,node_id
 *
 * @param filename Path to the input CSV file.
 * @return std::vector<Station> List of station objects.
 */
std::vector<Station> load_stations(const std::string& filename) {
    std::vector<Station> stations;
    std::ifstream file(filename);

    if (!file.is_open()) {
        std::cerr << "Error: Could not open station file: " << filename << "\\n";
        return stations;
    }

    std::string line;
    std::getline(file, line); // skip header

    while (std::getline(file, line)) {
        std::stringstream ss(line);
        Station s;
        std::string token;

        std::getline(ss, s.name, ',');
        std::getline(ss, token, ',');
        s.node_id = std::stoi(token);

        stations.push_back(s);
    }

    return stations;
}
