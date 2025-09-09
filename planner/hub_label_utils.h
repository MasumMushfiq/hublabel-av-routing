#ifndef HUB_LABEL_UTILS_H
#define HUB_LABEL_UTILS_H

#include <string>
#include <vector>

// Public API uses plain ints to avoid pulling in heavy headers.
// Treat node IDs as int throughout this interface.

/** Initialize BOTH distance and time hub-labels.
 *  dist_prefix -> loads dist_prefix.dorder / dist_prefix.dlabel   (distance in mm)
 *  time_prefix -> loads time_prefix.dorder / time_prefix.dlabel   (time in ms)
 *  Returns true on success.
 */
bool init_labels(const std::string& dist_prefix, const std::string& time_prefix);

/** Shortest-path distance (millimetres). Optionally fills path (vector<int>).
 *  Returns -1 if labels not loaded.
 */
int distance_mm(int u, int v, std::vector<int>* path_out = nullptr);

/** Shortest-path travel time (milliseconds). Optionally fills path (vector<int>).
 *  Returns -1 if labels not loaded.
 */
int time_ms(int u, int v, std::vector<int>* path_out = nullptr);

#endif // HUB_LABEL_UTILS_H