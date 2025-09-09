//
// Created by Bojie Shen on 8/8/20.
//

//
// Created by Bojie Shen on 7/10/19.
//

#include "CPD.h"
#include <fstream>
#include <stdexcept>
#include <cassert>
#include <routingkit/constants.h>
#include <iostream>

// compile with -O3 -DNDEBUG
namespace RoutingKit {
    void CPD::append_row_multiple_symbols(
            unsigned source_node, const vector<set<unsigned short>> & allowed_first_move) {

        auto get_allowed_local = [&](unsigned x) {
            return allowed_first_move[x];
        };

        unsigned int node_begin = 0;
        set<unsigned short> allowed_up_to_now = get_allowed_local(0);

        for (unsigned i = 1; i <  allowed_first_move.size(); ++i) {
            pair<int,set<unsigned short>> allowed_next = getIntersection(allowed_up_to_now , get_allowed_local(i));
            if (allowed_next.first == 0  && allowed_next.second.empty()) {

                entry.push_back((node_begin << 8) |  *allowed_up_to_now.begin());
                node_begin = i;
                allowed_up_to_now = get_allowed_local(i);
            } else
                allowed_up_to_now = allowed_next.second;
        }
        entry.push_back((node_begin << 8) | *allowed_up_to_now.begin());

        begin.push_back(entry.size());
    }

    void CPD::append_row(
            unsigned source_node, const vector<unsigned short>& allowed_first_move) {

        auto get_allowed_local = [&](unsigned x) {
            return allowed_first_move[x];
        };

        unsigned node_begin = 0;
        unsigned short allowed_up_to_now = get_allowed_local(0);

        if(allowed_up_to_now == 0xFE){
            allowed_up_to_now = get_allowed_local(1);
        }
        for (unsigned i = 1; i < allowed_first_move.size(); ++i) {
            unsigned short local = get_allowed_local(i);
            if(allowed_up_to_now != get_allowed_local(i) ){
                if(local == 0xFE){
                    continue;
                }else{
                    entry.push_back((node_begin << 8) |  allowed_up_to_now);
                    node_begin = i;
                    allowed_up_to_now = local;
                }

            }
        }
        entry.push_back((node_begin << 8) | allowed_up_to_now);

        begin.push_back(entry.size());
    }


    void CPD::append_row_using_mapper(
            unsigned source_node, const vector<unsigned short>& allowed_first_move) {

        auto get_allowed_local = [&](unsigned x) {
            x = (*DFS_mapper)[x];
            return allowed_first_move[x];
        };

        unsigned node_begin = 0;
        unsigned short allowed_up_to_now = get_allowed_local(0);

        if(allowed_up_to_now == 0xFE){
            allowed_up_to_now = get_allowed_local(1);
        }
        for (unsigned i = 1; i < allowed_first_move.size(); ++i) {
            unsigned short local = get_allowed_local(i);
            if(allowed_up_to_now != get_allowed_local(i) ){
                if(local == 0xFE){
                    continue;
                }else{
                    entry.push_back((node_begin << 8) |  allowed_up_to_now);
                    node_begin = i;
                    allowed_up_to_now = local;
                }

            }
        }
        entry.push_back((node_begin << 8) | allowed_up_to_now);

        begin.push_back(entry.size());
    }



    void CPD::append_row_with_landmark(
            unsigned source_node, const vector<unsigned short>& allowed_first_move) {

        auto get_allowed_local = [&](unsigned x) {
            if(allowed_first_move[x] == 0xFF){
                unsigned* startPtr = (*landmark_pointer)[source_node];
                unsigned* endPtr = (*landmark_pointer)[x];
                unsigned min = *(startPtr) +  *(endPtr);
                unsigned best = 0;
                for(int i = 1 ; i < number_of_landmarks; i++){
                    unsigned current_distance = *(startPtr+i*2) +  *(endPtr+i*2);
                    if( min > current_distance){
                        min = current_distance;
                        best = i;
                    }
                }
                return (unsigned short)*(startPtr+best*2 +1);
            }else {
                return allowed_first_move[x];
            }
        };

        unsigned node_begin = 0;
        unsigned short allowed_up_to_now = get_allowed_local(0);

        if(allowed_up_to_now == 0xFE){
            allowed_up_to_now = get_allowed_local(1);
        }
        for (unsigned i = 1; i < allowed_first_move.size(); ++i) {
            unsigned short local = get_allowed_local(i);
            if(allowed_up_to_now != get_allowed_local(i) ){
                if(local == 0xFE){
                    continue;
                }else{
                    entry.push_back((node_begin << 8) |  allowed_up_to_now);
                    node_begin = i;
                    allowed_up_to_now = local;
                }

            }
        }
        entry.push_back((node_begin << 8) | allowed_up_to_now);

        begin.push_back(entry.size());
    }


    void CPD::append_row_with_landmark_using_mapper(
            unsigned source_node, const vector<unsigned short>& allowed_first_move) {

        auto get_allowed_local = [&](unsigned x) {
            x = (*DFS_mapper)[x];
            if(allowed_first_move[x] == 0xFF){
                unsigned* startPtr = (*landmark_pointer)[source_node];
                unsigned* endPtr = (*landmark_pointer)[x];
                unsigned min = *(startPtr) +  *(endPtr);
                unsigned best = 0;
                for(int i = 1 ; i < number_of_landmarks; i++){
                    unsigned current_distance = *(startPtr+i*2) +  *(endPtr+i*2);
                    if( min > current_distance){
                        min = current_distance;
                        best = i;
                    }
                }
                return (unsigned short)*(startPtr+best*2 +1);
            }else {
                return allowed_first_move[x];
            }
        };

        unsigned node_begin = 0;
        unsigned short allowed_up_to_now = get_allowed_local(0);

        if(allowed_up_to_now == 0xFE){
            allowed_up_to_now = get_allowed_local(1);
        }
        for (unsigned i = 1; i < allowed_first_move.size(); ++i) {
            unsigned short local = get_allowed_local(i);
            if(allowed_up_to_now != get_allowed_local(i) ){
                if(local == 0xFE){
                    continue;
                }else{
                    entry.push_back((node_begin << 8) |  allowed_up_to_now);
                    node_begin = i;
                    allowed_up_to_now = local;
                }

            }
        }
        entry.push_back((node_begin << 8) | allowed_up_to_now);

        begin.push_back(entry.size());
    }

    void CPD::append_rows(const CPD &other) {
        unsigned offset = begin.back();
        for (auto x:make_range(other.begin.begin() + 1, other.begin.end()))
            begin.push_back(x + offset);
        std::copy(other.entry.begin(), other.entry.end(), back_inserter(entry));
    }

    void CPD::append_rows(const CPD &other,unsigned row_id) {
//        int offset = begin.back();
//
//        for (auto x:make_range(other.begin.begin() + 1, other.begin.end()))
//            begin.push_back(x + offset);
//
        unsigned start = other.begin[row_id];
        unsigned end =other.begin[row_id+1];
        std::copy(other.entry.begin()+ start , other.entry.begin()+end, back_inserter(entry));
        begin.push_back(entry.size());
    }

    const set<unsigned>& CPD::get_allowed_multiple_row(unsigned x, unsigned s, const vector<set<unsigned>> &fmoves) const {
        return fmoves[x];
    }



    const unsigned & CPD::get_allowed(unsigned x, unsigned s, const vector<unsigned> &fmoves) const {
        return fmoves[x];
    }



}
