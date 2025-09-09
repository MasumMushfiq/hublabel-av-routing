//
// Created by Bojie Shen on 18/8/20.
//

#ifndef ROUTINGKIT_SEARCHNODE_H
#define ROUTINGKIT_SEARCHNODE_H



#pragma once
//#include "point.h"

namespace RoutingKit{

// A search node.
// Only makes sense given a mesh and an endpoint, which the node does not store.
// This means that the f value needs to be set manually.
    struct SearchNode
    {
        SearchNode* parent;
        // Note that all Points here will be in terms of a Cartesian plane.
        unsigned root; // -1 if start

        unsigned first_move;
        // If possible, set the orientation of left / root / right to be
        // "if I'm standing at 'root' and look at 'left', 'right' is on my right"
        bool is_forward;

        // The left vertex of the edge the interval is lying on.
        // When generating the successors of this node, end there.

        unsigned  g;

        unsigned  rank;


        SearchNode() {}
        SearchNode(SearchNode* p, unsigned rid, unsigned fm, bool forward, unsigned g,unsigned rk):
                parent(p), root(rid), first_move(fm), is_forward(forward),g(g),rank(rk) { }

        // Comparison.
        // Always take the "smallest" search node in a priority queue.
        bool operator<(const SearchNode& other) const
        {
                // If two nodes have the same f, the one with the bigger g
                // is "smaller" to us.
                return this->g < other.g;
        }

        bool operator>(const SearchNode& other) const
        {
                return this->g > other.g;
        }

//        friend std::ostream& operator<<(std::ostream& stream, const SearchNode& sn)
//        {
//            return stream << "SearchNode ([" << sn.root << ", [" << sn.left << ", "
//                          << sn.right << "]], f=" << sn.f << ", g=" << sn.g
//                          << ", poly=" << sn.next_polygon << ")";
//        }
//
//        void set_reached() { reached = true; }
//        void set_goal_id(int gid) { goal_id = gid; }
    };

    typedef SearchNode* SearchNodePtr;

}





#endif //ROUTINGKIT_SEARCHNODE_H
