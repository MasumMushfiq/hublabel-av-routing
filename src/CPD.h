//
// Created by Bojie Shen on 8/8/20.
//

#ifndef ROUTINGKIT_CPD_H
#define ROUTINGKIT_CPD_H

//
// Created by Bojie Shen on 7/10/19.

#pragma once
#include <vector>
#include <set>
#include <algorithm>
#include <string>
#include "binary_search.h"
#include "range.h"
#include "vec_io.h"

namespace RoutingKit {

//    #include "adj_graph.h"
//#include "mapper.h"
//#include "rect_wildcard.h"

    using namespace std;
//! Compressed Path database. Allows to quickly query the first out arc id of
//! any shortest source-target-path. There may be at most 15 outgoing arcs for
//! any node.
    class CPD {
    public:
        CPD():begin{0}{}
        explicit CPD( const std::vector<unsigned*>&landmark_pointer,
            unsigned landmark_number):begin{0},landmark_pointer(&landmark_pointer)
            {number_of_landmarks = landmark_number;};
        explicit CPD( const std::vector<unsigned>&DFS_mapper,const std::vector<unsigned*>&landmark_pointer,
             unsigned landmark_number):begin{0},landmark_pointer(&landmark_pointer),DFS_mapper(&DFS_mapper)
        {number_of_landmarks = landmark_number;};

        explicit CPD( const std::vector<unsigned>&DFS_mapper):begin{0},DFS_mapper(&DFS_mapper){};

        //! Adds a new node s to the CPD. first_move should be an array that
        //! maps every target node onto a 15-bit bitfield that has a bit set
        //! for every valid first move. get_first_move is free to return any of
        //! them.

        void append_row(unsigned source_node, const vector<unsigned short> & allowed_first_move);
        void append_row_with_landmark(unsigned source_node, const vector<unsigned short> & allowed_first_move);
        void append_row_using_mapper(unsigned source_node, const vector<unsigned short> & allowed_first_move);
        void append_row_with_landmark_using_mapper(unsigned source_node, const vector<unsigned short> & allowed_first_move);
        void append_rows(const CPD&other);
        void append_rows(const CPD &other,unsigned row_id);
        //! Get the first move.
        //! An ID of 0xF means that there is no path.
        //! If source_node == target_node then return value is undefined.
        unsigned char get_first_move(unsigned source_node, unsigned target_node)const{
            target_node <<= 8;
            target_node |= 0xFF;
            return *binary_find_last_true(
                    entry.begin() + begin[source_node],
                    entry.begin() + begin[source_node+1],
                    [=](unsigned x){return x <= target_node;}
            )&0xFF;
        }

        unsigned node_count() const{
            // get the number of rows
            // in inverse centroid cpd, this returns the number of centroids.
            return begin.size()-1;
        }

        unsigned entry_count()const{
            return entry.size();
        }

        friend bool operator==(const CPD&l, const CPD&r){
            return l.begin == r.begin && l.entry == r.entry;
        }

        friend bool operator!=(const CPD&l, const CPD&r){
            return !(l == r);
        }
        void save(std::FILE*f)const{
            save_vector(f, begin);
            save_vector(f, entry);
        }

        void load(std::FILE*f){
            begin = load_vector<unsigned>(f);
            entry = load_vector<unsigned>(f);
        }

        unsigned long long get_entry_size() const {
            return entry.size();
        }

        const vector<unsigned>& get_entry(unsigned row_number) const {
            entry.begin() + begin[row_number];
            entry.begin() + begin[row_number+1];

            return entry;
        }

        const vector<unsigned>& get_entry() const {
            return entry;
        }

        const vector<unsigned>& get_begin() const {
            return begin;
        }

        pair<int,set<unsigned short>> getIntersection(set<unsigned short>& s1, const set<unsigned short>& s2) {
            set<unsigned short> intersect = set<unsigned short>();
            if(s2.empty()&& s1.empty()){
                return pair<int,set<unsigned short>>(1,intersect);
            }else if(s2.empty()){
                return pair<int,set<unsigned short>>(1,s1);
            }else if(s1.empty()){
                return pair<int,set<unsigned short>>(1,s2);
            }
            set_intersection(s1.begin(),s1.end(),s2.begin(),s2.end(),
                             std::inserter(intersect,intersect.begin()));
            return pair<int,set<unsigned short>>(0,intersect);
        }


        void append_row_multiple_symbols(unsigned source_node, const vector<set<unsigned short>>& set);

        void push_back_row(const vector<unsigned>&compressed_row){
            entry.insert(entry.end(),compressed_row.begin(),compressed_row.end());
            begin.push_back(entry.size());
        }
    protected:
        std::vector<unsigned>begin;
        std::vector<unsigned>entry;
        const std::vector<unsigned*>*landmark_pointer;
        const std::vector<unsigned>*DFS_mapper;
        unsigned number_of_landmarks;
        const unsigned & get_allowed(unsigned x, unsigned s, const vector<unsigned> &fmoves) const;

        const set<unsigned>& get_allowed_multiple_row(unsigned x, unsigned s, const vector<set<unsigned>> &fmoves) const;


    };


}

#endif //ROUTINGKIT_CPD_H
