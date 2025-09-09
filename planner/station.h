#ifndef STATION_H
#define STATION_H

#include <string>
#include <vector>

/**
 * @brief Represents a train station with a name and its corresponding node ID on the graph.
 */
struct Station {
    std::string name;   ///< Human-readable station name (e.g., "Melton")
    int node_id;        ///< Node ID of the station in the routing graph
};

/**
 * @brief Loads a list of stations from a CSV file.
 *
 * The CSV file should have a header and be formatted as:
 * name,node_id
 * Example:
 * Melton,17535
 *
 * @param filename Path to the CSV file.
 * @return Vector of Station objects.
 */
std::vector<Station> load_stations(const std::string& filename);

#endif // STATION_H
