
#include "commuter.h"
#include <fstream>
#include <sstream>
#include <iostream>

int hhmm_to_seconds(const std::string& hhmm) {
    int h, m;
    char sep;
    std::stringstream ss(hhmm);
    ss >> h >> sep >> m;
    return h * 3600 + m * 60;
}

std::vector<Commuter> load_commuters(const std::string& filename) {
    std::vector<Commuter> commuters;
    std::ifstream file(filename);

    if (!file.is_open()) {
        std::cerr << "Error: Could not open commuter file: " << filename << "\n";
        return commuters;
    }

    std::string line;
    std::getline(file, line); // skip header

    while (std::getline(file, line)) {
        std::stringstream ss(line);
        Commuter c{};
        std::string token;

        std::getline(ss, token, ',');
        c.id = std::stoi(token);
        std::getline(ss, token, ',');
        c.origin_node = std::stoi(token);
        std::getline(ss, token, ',');
        c.destination_node = std::stoi(token);
        std::getline(ss, token, ',');
        c.window_start = hhmm_to_seconds(token);
        std::getline(ss, token, ',');
        c.window_end = hhmm_to_seconds(token);

        commuters.push_back(c);
    }

    return commuters;
}
