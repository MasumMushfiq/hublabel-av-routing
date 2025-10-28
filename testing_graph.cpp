#include <routingkit/vector_io.h>
#include <routingkit/my_timer.h>
#include <routingkit/contraction_hierarchy.h>
#include <routingkit/inverse_vector.h>
#include "CPD.h"
#include <iostream>
#include <stdexcept>
#include <vector>
#include <routingkit/geo_dist.h>
#include <iomanip>
#include <random>
#include "../src/graph.h"
#include "../src/coverage_ordering_path.h"
#include "../src/performance_metrics.h"
#include "verify.h"
#include <cassert>
//
// Created by Md Mushfiq on 24/7/2025.
//
using namespace std;
using namespace RoutingKit;

int main(int argc, char*argv[]){

    try{
        string file_location;


        if(argc != 2){
            cerr << argv[0] << "hub_file " << endl;
            return 1;
        }else{
            file_location = argv[1];
        }



        cout << "Loading Hub Labels" << endl;
        string graph_name = file_location + ".txt";
        string label_name = file_location + ".dlabel";
        string order_name = file_location + ".dorder";

        const char* graphFileName=  graph_name.c_str();
        const char* labelFileName = label_name.c_str();
        const char* orderFileName = order_name.c_str();

        // build_shp_undirect_graph(graphFileName, labelFileName, orderFileName);
        DPLabel label;
        label.load_labels(labelFileName);
        ifstream order_ifs(orderFileName);
        vector<NodeID> rank(19756);
        vector<NodeID> inv(19756);
        for(int i = 0; i < 19756; ++i){
            NodeID tv;
            order_ifs >> tv;
            rank[tv] = i;
            inv[i] = tv;
        }

        cout << "Hello World!" << endl;
        cout << label.query_p(874, 874) << endl;
        cout << label.query_p(6323, 17353) << endl;
        // cout << lab.query(6323 , 17455) << endl;

        int from = 881;
        int to = 10353;
        std::cout << label.query_p(from,to) << std::endl;
        vector<int> path = vector<int>();
        int  cost = label.query_path(from, to, rank, inv, path);
        cout << cost << endl;
        cout << "The path is";
        for(auto x:path)
            cout << " " << x;
        cout << endl;
       return 0;
    }catch(exception&err){
        cerr << "Stopped on exception : " << err.what() << endl;
    }
}