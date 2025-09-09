// planner/commuter.h
#ifndef COMMUTER_H
#define COMMUTER_H

#include <string>
#include <vector>

struct Commuter {
    int id;
    int origin_node;
    int destination_node;
    int window_start;  // Earliest time the trip can start
    int window_end;    // Latest time by which the trip must end
};

std::vector<Commuter> load_commuters(const std::string& filename);

#endif // COMMUTER_H
