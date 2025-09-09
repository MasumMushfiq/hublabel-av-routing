#include <routingkit/contraction_hierarchy.h>
#include <routingkit/inverse_vector.h>
#include <iostream>
#include <vector>
#include <iomanip>
#include "../src/graph.h"
#include "../src/coverage_ordering_path.h"

using namespace RoutingKit;
using namespace std;

bool comp(tuple<int, int> &a, tuple<int, int> &b )
{
    return (get<0>(a) == get<0>(b)) && (get<1>(a) == get<1>(b));
}


void normalise_vector(vector<double> &val){
    double max = *max_element(val.begin(), val.end());
    double min = *min_element(val.begin(), val.end());
    //cout << max << " " << min << endl;
    for(unsigned i = 0; i < val.size(); i++){
        //cout << val[i] << " ";
        val[i] = (val[i] - min) / (max - min);
        //cout << val[i] << endl;
    }

}

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
        string label_name = file_location + ".label";
        string order_name = file_location + ".order";

        const char* graphFileName=  graph_name.c_str();
        const char* labelFileName = label_name.c_str();
        const char* orderFileName = order_name.c_str();

        // build_shp_undirect_graph(graphFileName, labelFileName, orderFileName);
        PLabel lab;
        lab.load_labels(labelFileName);
        ifstream order_ifs(orderFileName);

        int no_of_nodes = 19756; // For testing purposes, we can set this to 8
        vector<NodeID> rank(no_of_nodes);
        vector<NodeID> inv(no_of_nodes);
        for(int i = 0; i < no_of_nodes; ++i){
            NodeID tv;
            order_ifs >> tv;
            rank[tv] = i;
            inv[i] = tv;
        }
//        for(int i = 0; i < 8 ; i++){
//            cout << i << " ---- > ";
//            lab.print_label(i, inv);
//            cout << endl;
//        }

        // cout << lab.query(0 , 3) << endl;
        // cout << lab.query(0 , 6) << endl;
        cout << lab.query(874, 17455) << endl;
        cout << lab.query(17455, 874) << endl;

        int from = 874;
        int to = 17455;
        vector<int> path = vector<int>();
        int  cost = lab.query_path(from, to, rank, inv, path);
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