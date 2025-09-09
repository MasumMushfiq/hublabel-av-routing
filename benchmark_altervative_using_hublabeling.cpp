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
#include <sstream>

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
        string ch_file;
        string first_out_file;
        string head_file;
        string weight_file;
        string query_file;
        int num_of_alternative_paths;
        int landmark;
        int step = 10;
//        string result_file;
//        string percentage;
//        string number_of_landmark;



        if(argc != 5){
            cerr << argv[0] << "ch_file query_count  " << endl;
            return 1;
        }else{
            file_location = argv[1];
            ch_file = file_location + ".ch";
            first_out_file = file_location + ".first";
            head_file = file_location + ".head";
            weight_file = file_location + ".weight";
            query_file = argv[2];
            num_of_alternative_paths = strtol(argv[3], NULL, 10);
            landmark = strtol(argv[4], NULL, 10);
//            result_file = argv[2];
//            percentage = argv[3];
//            number_of_landmark = argv[4];
//            order_file = argv[3];
//            mapper_file = argv[4];
        }




        cout << "Loading graph ... " << flush;

        vector<unsigned>first_out = load_vector<unsigned>(first_out_file);
        vector<unsigned>head = load_vector<unsigned>(head_file);
        vector<unsigned>weight = load_vector<unsigned>(weight_file);

        cout << "done" << endl;


        cout << "Validity tests ... " << flush;
        check_if_graph_is_valid(first_out, head);
        cout << "done" << endl;

        cout << "Loading Contraction Hierarchy ... " << flush;
        ContractionHierarchy ch = ContractionHierarchy::load_file(ch_file);
        cout << "done" << endl;
        cout << "Check Contraction Hierarchy  ... " << flush;
        check_contraction_hierarchy_for_errors(ch);
        cout << "done" << endl;
        cout << ch.node_count() << endl;



        std::vector<tuple <int, int>> query_points;
        std::ifstream ifs(query_file);
        unsigned a , b;
        ifs >> std::ws;
        while (ifs.good()){
            ifs >> a >> b ;
            query_points.push_back(std::make_tuple(a , b));
            ifs >> std::ws;
        }
        ifs.close();
        cout << "Number of queries : " << query_points.size() << endl;


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
        vector<NodeID> rank(ch.node_count());
        vector<NodeID> inv(ch.node_count());
        for(int i = 0; i < ch.node_count(); ++i){
            NodeID tv;
            order_ifs >> tv;
            rank[tv] = i;
            inv[i] = tv;
        }
        cout << "Done" << endl;
        std::random_device rd; // obtain a random number from hardware
        std::mt19937 gen(50); // seed the generator
        std::uniform_int_distribution<> distr(0, ch.node_count()); // define the range

        lab.landmark_list = load_vector<unsigned>(file_location+".landmark"+ to_string(landmark));
        lab.number_of_landmark = landmark;


//        std::ifstream inputFile("./dataset/MEL/data.txt"); // Replace "input.txt" with your input file name
//        std::vector<std::vector<unsigned int>> lines; // Vector to store lines as vectors of integers
//
//        std::string line;
//        while (std::getline(inputFile, line)) {
//            std::vector<unsigned int> numbers; // Vector to store integers from each line
//
//            std::stringstream ss(line);
//            int num;
//            while (ss >> num) {
//                numbers.push_back(num);
//            }
//
//            lines.push_back(numbers);
//        }
//        double tbs_score, tlo_score;
//        // Print the vectors of integers
//        int c = 0;
//        std::vector<double> t_b_s_scores;
//        std::vector<double> t_lo_scores;
//
//        std::vector<double> f_b_s_scores;
//        std::vector<double> f_lo_scores;
//        for (const auto& numbers : lines) {
//            c ++;
//            // cout << numbers.size() << endl;
////            for (const auto& numbers : lines) {
////                for (int num : numbers) {
////                    std::cout << num << " ";
////                }
////                std::cout << std::endl;
////            }
//            std::tie(tbs_score, tlo_score) = get_Local_Optimality_and_Bounded_Stretch(numbers, lab, first_out, head, weight);
//            // cout << tbs_score << " " << tlo_score << endl;
//            t_b_s_scores.push_back(tbs_score);
//            t_lo_scores.push_back(tlo_score);
//            if(c % 3 == 0){
//                c = 0;
//                cout << "Maximum BS: " << *std::max_element(t_b_s_scores.begin(), t_b_s_scores.end()) << "  ";
//                cout << "Minimum LO : " << *std::min_element(t_lo_scores.begin(), t_lo_scores.end()) <<  "  " << numbers.size() <<  endl;
//
//                f_b_s_scores.push_back(*std::max_element(t_b_s_scores.begin(), t_b_s_scores.end()));
//                f_lo_scores.push_back(*std::min_element(t_lo_scores.begin(), t_lo_scores.end()));
//
//
//                t_b_s_scores.clear();
//                t_lo_scores.clear();
//
//
//            }
//
//            //std::cout << std::endl;
//        }
//
//        cout << f_b_s_scores.size() << " " << f_lo_scores.size() << endl;
//        cout << "Maximum Final BS: " << *std::max_element(f_b_s_scores.begin(), f_b_s_scores.end()) << "  ";
//        cout << "Minimum Final LO : " << *std::min_element(f_lo_scores.begin(), f_lo_scores.end()) << endl;
//
//
//        double b_s_count = 0 ;
//        for(auto x:f_b_s_scores)
//            b_s_count += x;
//        cout << "Average : " <<  b_s_count / f_b_s_scores.size() << endl;
//        cout << endl;
//
//        double l_o_count = 0 ;
//        for(auto x:f_lo_scores)
//            l_o_count += x;
//        cout << "Average : " << l_o_count / f_lo_scores.size() << endl;
//        cout << endl;

        // cout << lab.query(0, 1000) << " " << lab.get_max_landmard_distance(0, 1000) << endl;

        unsigned from, to;
        // 558088 737002 736999
        /*
        from = 558088;
        to = 737002;
        vector<int> path = vector<int>();
        int  cost = lab.query_path(from, to, rank, inv, path);
        cout << cost << endl;
        cout << "The path is";
        for(auto x:path)
            cout << " " << x;
        cout << endl;


        int p1,p2;
        int distance1, distance2;

        tie(distance1, p1) = lab.query_distance_next(from, to);
        tie(distance2, p2) = lab.query_distance_next( to, from);

        cout << distance1 << " " << p1 << endl;
        cout << distance2 << " " << p2 << endl;

        from = 737000;
        to = 736999;

        path = vector<int>();
        cost = lab.query_path(from, to, rank, inv, path);
        cout << cost << endl;
        cout << "The path is";
        for(auto x:path)
            cout << " " << x;
        cout << endl;


        tie(distance1, p1) = lab.query_distance_next(from, to, inv);
        tie(distance2, p2) = lab.query_distance_next( to, from, inv);

        cout << distance1 << " " << p1 << endl;
        cout << distance2 << " " << p2 << endl;

        */

        //my_timer timer_path = my_timer();
        //timer_path.start();
        from = 558087;
        to = 736998;
        vector<int> path = vector<int>();
        int  cost = lab.query_path(from, to, rank, inv, path);
        // timer_path.stop();
        //cout <<  timer_path.elapsed_time_micro() << endl;
        cout << cost << endl;
        cout << path.size() << endl;
//        cout << "The path is";
//        for(auto x:path)
//            cout << " " << x;
//        cout << endl;



        //return 0;
        vector<pair<unsigned , unsigned >> via_nodes;
        //unsigned dis = lab.generating_via_nodes(from, to, rank, inv, via_nodes);
        //cout << via_nodes.size() << endl;


        /*
        int j = 0;
        // The loop while queue is empty
        cout << "Total via nodes : " << via_nodes.size() << endl;
        while(!via_nodes.empty())
        {
            // Prints and pops the element in the top of the queue
            pair<int,int> top=via_nodes.top();
            via_nodes.pop();
            cout<<"("<<top.first<<","<<top.second<<")"<<endl;
            if(top.second < double(dis) * 1.5){
                j++;
            }
        }
        vector<int> path = vector<int>();
        int  cost = lab.query_path(from, to, rank, inv, path);
        cout << cost << endl;
        cout << "The path is";
        for(auto x:path)
            cout << " " << x;
        cout << endl;
        cout << "Total via nodes after distance puring : " << j << endl;*/
        std::vector<int> via_numbers;
        std::vector<int> via_numbers_after_distance_puring;
        std::vector<int> via_numbers_after_exact_distance_puring;
        std::vector<int> via_numbers_after_detour_filtering;
        std::vector<int> via_numbers_after_similarity_filtering;
        std::vector<int> cache_size;


        std::vector<double> s_score;
        std::vector<double> b_s_score;
        std::vector<double> lo_scores;
        vector<vector< tuple < vector<unsigned> , unsigned, double >>> alternative_Paths;



        double time_for_node_generation = 0;
        double time_for_landmark_puring = 0;
        double time_for_sim_puring = 0;
        double time_for_bslo_puring = 0;
        unsigned total_hash_size = 0;
        int total = 0;
        my_timer timer1 = my_timer();
        timer1.start();
        for (auto&& point: query_points)
        {
            //from = distr(gen);
            //to = distr(gen);
            std::tie(from, to) = point;
            vector<unsigned> meeting_points;
            meeting_points.push_back(0);

            //cout << from << "  " << to << endl;
            if(lab.query(from, to) == INF_WEIGHT){
                continue;
            }
            std::unordered_map<std::pair<unsigned, unsigned>, unsigned, pair_hash> hub_lookup;

            vector< tuple < vector<unsigned> , unsigned, double >> a_paths;
            vector< tuple < vector<unsigned> , unsigned, double >> result_paths;
            vector<int> s_path(0);
            unsigned shortest_path = lab.query_path(from, to, rank, inv, s_path);
            hub_lookup.insert({make_pair(from, to), shortest_path});
            a_paths.push_back(make_tuple(vector<unsigned>(s_path.begin(),s_path.end()),shortest_path, 0));

            my_timer timer2 = my_timer();
            timer2.start();
            //priority_queue<pair<int,int>, vector<pair<int,int>>, Compare> via_nodes;
            vector< tuple<unsigned, unsigned, unsigned> > via_nodes_union;
            unsigned dis1 = lab.generating_via_nodes_union(from, to, rank, inv, via_nodes_union, shortest_path);
            timer2.stop();

            /*cout << dis << endl;
            vector<int> path = vector<int>();
            unsigned cost = lab.query_path(from, to, rank, inv, path);
            cout << cost << endl;
            cout << lab.query(from, to) << endl;
            cout << via_nodes.size() << endl;*/

            //cout << dis << endl;
            vector<unsigned> nodes;

            // The loop while queue is empty
            //cout << "Total via nodes : " << via_nodes.size() << endl;

            for(auto x:via_nodes_union) {
                unsigned v,d, s;
                std::tie(v, d, s) = x;
                /*if(lab.query(from, v) + lab.query(v, to) < double(shortest_path) * 1.5){
                    nodes.push_back(v);
                }*/
                //cout << v << " " << s << endl;
                if( s == 0 ){
                    //cout << lab.query(from , v) << endl;
                    if(lab.get_max_landmard_distance(v , to) + d  < double(shortest_path) * 1.5){
                        //cout << lab.query(v, to) << "  " << lab.get_max_landmard_distance(v , to) << " " << lab.get_min_landmard_upperband(v, to)<< endl;
                        nodes.push_back(v);
                    }
                    //cout << v << " " << d << " " << s << endl;
                } else if (s == 1){
                    //cout << lab.query(v , to) << endl;
                    if(lab.get_max_landmard_distance(from, v) + d  < double(shortest_path) * 1.5){
                        nodes.push_back(v);
                    }
                    //cout << v << " " << d << " " << s << endl;

                } else{
                    nodes.push_back(v);
                }

            }

            int j = 0;
            int k = 0;
            int l = 0;

            // The loop while queue is empty
            //cout << "Total via nodes : " << via_nodes.size() << endl;
            via_numbers.push_back(via_nodes_union.size());
            for(auto x:nodes)
            {
                j++;
                unsigned v_node = x;
                //int v_node = top.first;
                // cout << v_node << endl;
                int p1, p2;
                int distance1, distance2;

                tie(distance1, p1) = lab.query_distance_next(v_node, from, inv);
                tie(distance2, p2) = lab.query_distance_next(v_node, to, inv);

                hub_lookup.insert({make_pair(from, v_node), distance1});
                hub_lookup.insert({make_pair(v_node, to), distance2});

                if(distance1 + distance2 > 1.5 * (double) shortest_path){
                    continue;
                }
                l++;
                // cout << p1 << "  " << p2 << endl;
                if(p1 == p2){
                    continue;
                }
                k++;
                my_timer timer3 = my_timer();
                timer3.start();
                vector<int> path1(0);
                distance1 = lab.query_path(from, v_node, rank, inv, path1);

                vector<int> path2(0);
                distance2 = lab.query_path(v_node, to, rank, inv, path2);

                /*if(distance1 + distance2 > 1.5 * (double) shortest_path){
                    continue;
                }
                l++;

                if(path1[path1.size() - 2] == path2[1]){
                    continue;
                }
                k++;
                 */

                //For Hub
                /*if(path1[path1.size() - 2] == path2[1]){

                    //cout << "***********" << endl;
                    //cout << from << " " << x << " " << to << endl;
                    //cout << path1[path1.size() - 2] << " " << path2[1] << endl;
                    *//*int p1,p2;
                    int distance1, distance2;

                    tie(distance1, p1) = lab.query_distance_next(v_node, from, inv);
                    tie(distance2, p2) = lab.query_distance_next( v_node, to, inv);

                    //cout << distance1 << " " << p1 << endl;
                    //cout << distance2 << " " << p2 << endl;
                    //cout << "***********" << endl;
                    if(p1 != path1[path1.size() - 2] || p2 != path2[1]){
                        cout << "Problem" << endl;
                    }*//*
                    continue;
                }*/
                vector<unsigned> path(path1.begin(), path1.end());
                path.insert(path.end(), path2.begin() + 1, path2.end());

                timer3.stop();
                time_for_landmark_puring += timer3.elapsed_time_nano();

                if(path1[path1.size() - 2] == path2[1]){
                    cout << "*****" << endl;
                    cout << "Problem" << " " << from << "  "  << v_node << "  " << to << endl;
                    cout << "The path is";
                    for(auto x:path)
                        cout << " " << x;
                    cout << endl;
                    tie(distance1, p1) = lab.query_distance_next(v_node, from, inv);
                    tie(distance2, p2) = lab.query_distance_next(v_node, to, inv);
                    cout << p1 << "  " << p2 << endl;
                    cout << "*****" << endl;
                }


                my_timer timer4 = my_timer();
                timer4.start();
                int flag = 1;
                double max = 0;
                double sim_score = similarity_check(get<0>(a_paths[0]), path, get<1>(a_paths[0]), distance1 + distance2, first_out, head, weight);
                if(sim_score > 0.50){
                    flag = 0;
                }
                /*for(auto p:a_paths){
                    double sim_score = similarity_check(get<0>(p), path, get<1>(p), distance1 + distance2, first_out, head, weight, 0.5);
                    //double sim_score = similarity_check(get<0>(p), path, get<1>(p), distance1 + distance2, first_out, head, weight);
                    if(sim_score == -1){
                        flag = 0;
                        break;
                    }
                    if(sim_score > 0.50){
                        flag = 0;
                        break;
                    }
                    if(sim_score > max){
                        max = sim_score;
                    }
                }*/
                if(flag == 1){
                    a_paths.push_back(make_tuple(path, distance1 + distance2, max));
                    meeting_points.push_back(path1.size());
                    // cout << "******" << endl;
                    // cout << path1.size() << endl;
                }

                timer4.stop();
                time_for_sim_puring += timer4.elapsed_time_nano();
            }

            my_timer timer5 = my_timer();
            timer5.start();
            via_numbers_after_distance_puring.push_back(j);
            via_numbers_after_exact_distance_puring.push_back(l);
            via_numbers_after_detour_filtering.push_back(k);
            via_numbers_after_similarity_filtering.push_back(a_paths.size());
            if(a_paths.size() >= num_of_alternative_paths){
                total++;
                double max = 0;
                vector<double> similarity_scores(a_paths.size());
                vector<double> bounded_stretch_scores(a_paths.size());
                vector<double> local_optimality_scores(a_paths.size());
                vector<double> length_scores(a_paths.size());
                similarity_scores[0] = 0;
                bounded_stretch_scores[0] = 1;
                local_optimality_scores[0] = 1;
                length_scores[0] = 0;
                double bs_score, lo_score;

                for (int i = 1; i < a_paths.size(); i++) {
                    similarity_scores[i] = get<2>(a_paths[i]);
                    //std::tie(bs_score, lo_score) = get_Local_Optimality_and_Bounded_Stretch_Optimal(get<0>(a_paths[i]), meeting_points[i], lab, first_out, head, weight, shortest_path, 10);
                    std::tie(bs_score, lo_score) = get_Local_Optimality_and_Bounded_Stretch_Optimal_Caching(get<0>(a_paths[i]), meeting_points[i], lab, first_out, head, weight, hub_lookup, shortest_path, 10);
                    /*cout << bs_score << " " << lo_score << endl;
                    std::tie(bs_score, lo_score) = get_Local_Optimality_and_Bounded_Stretch(get<0>(a_paths[i]), lab, first_out, head, weight);
                    cout << bs_score << " " << lo_score << endl;*/

                    bounded_stretch_scores[i] = bs_score;
                    local_optimality_scores[i] = lo_score;
                    length_scores[i] =  (double) (get<1>(a_paths[i]) - get<1>(a_paths[0])) / get<1>(a_paths[0]);

                    /*cout << similarity_scores[i] << "  " << bounded_stretch_scores[i] << "  "
                         << local_optimality_scores[i] << "  " << length_scores[i] << " "
                         << endl;*/
                }

                normalise_vector(similarity_scores);
                normalise_vector(bounded_stretch_scores);
                normalise_vector(local_optimality_scores);
                normalise_vector(length_scores);

                result_paths.push_back(make_tuple(get<0>(a_paths[0]), get<1>(a_paths[0]), get<2>(a_paths[0])));
                for (int i = 0; i < a_paths.size(); i++) {
                    double normalised_score =
                            -bounded_stretch_scores[i] - similarity_scores[i] + local_optimality_scores[i] -
                            length_scores[i];
                    // cout << similarity_scores[i] << "  " << bounded_stretch_scores[i] << "  " << local_optimality_scores[i] << "  " << length_scores[i] << " " << normalised_score << endl;
                    get<2>(a_paths[i]) = normalised_score;
                }

                alternative_Paths.push_back(a_paths);


            }
            timer5.stop();
            time_for_bslo_puring += timer5.elapsed_time_nano();
            time_for_node_generation += timer2.elapsed_time_nano();

            //total++;
            //if(total == num_of_alternative_paths) break;

            std::size_t mapSize = sizeof(hub_lookup);
            for (const auto& entry : hub_lookup) {
                mapSize += sizeof(entry.first) + sizeof(entry.second);
            }
            cache_size.push_back(mapSize);
            cout << "Size of hub_lookup: " << mapSize << " bytes " << hub_lookup.size() << std::endl;
            total_hash_size += mapSize;

        }
        cout << "Avg. Size : " << (total_hash_size / query_points.size()) /1e6 << " MB" << endl;
        timer1.stop();
        double query_time = timer1.elapsed_time_nano()  / 1e9;
        time_for_node_generation = time_for_node_generation / 1e9;
        time_for_landmark_puring = time_for_landmark_puring / 1e9;
        time_for_sim_puring = time_for_sim_puring / 1e9;
        time_for_bslo_puring = time_for_bslo_puring / 1e9;


//        cout << "Average time for node generation : " << time_for_node_generation / query_points.size() << "  " << time_for_node_generation / query_time << endl;
//        cout << "Average time for path finding : " << time_for_landmark_puring / query_points.size() << "  " << time_for_landmark_puring / query_time << endl;
//        cout << "Average time for similarity puring : " << time_for_sim_puring / query_points.size() << "  " << time_for_sim_puring / query_time << endl;
//        cout << "Average time for bs/lo puring : " << time_for_bslo_puring / query_points.size() << "  " << time_for_bslo_puring / query_time << endl;
//
        cout << "Average query time : " << query_time/ query_points.size() << endl;



        cout << "Number of queries returned k path : " << total << endl;
        cout << "*********** Via Nodes Summary ***********" << endl;
        cout << "Minimum : " << *std::min_element(via_numbers.begin(), via_numbers.end()) << endl;
        cout << "Maximum : " << *std::max_element(via_numbers.begin(), via_numbers.end()) << endl;
        int count = 0 ;
        for(auto x:via_numbers)
            count += x;
        cout << "Average : " << count / total << endl;
        cout << endl;

        cout << "*********** Via Nodes after Landmark distance puring Summary ***********" << endl;
        cout << "Minimum : " << *std::min_element(via_numbers_after_distance_puring.begin(), via_numbers_after_distance_puring.end()) << endl;
        cout << "Maximum : " << *std::max_element(via_numbers_after_distance_puring.begin(), via_numbers_after_distance_puring.end()) << endl;
        count = 0 ;
        for(auto x:via_numbers_after_distance_puring)
            count += x;
        cout << "Average : " << count / total << endl;
        cout << endl;


        cout << "*********** Via Nodes after Exact  distance puring Summary ***********" << endl;
        cout << "Minimum : " << *std::min_element(via_numbers_after_exact_distance_puring.begin(), via_numbers_after_exact_distance_puring.end()) << endl;
        cout << "Maximum : " << *std::max_element(via_numbers_after_exact_distance_puring.begin(), via_numbers_after_exact_distance_puring.end()) << endl;
        count = 0 ;
        for(auto x:via_numbers_after_exact_distance_puring)
            count += x;
        cout << "Average : " << count / total << endl;
        cout << endl;


        cout << "*********** Via Nodes after detour filtering Summary ***********" << endl;
        cout << "Minimum : " << *std::min_element(via_numbers_after_detour_filtering.begin(), via_numbers_after_detour_filtering.end()) << endl;
        cout << "Maximum : " << *std::max_element(via_numbers_after_detour_filtering.begin(), via_numbers_after_detour_filtering.end()) << endl;
        count = 0 ;
        for(auto x:via_numbers_after_detour_filtering)
            count += x;
        cout << "Average : " << count / total << endl;
        cout << endl;

        cout << "*********** Via Nodes after similarity filtering Summary ***********" << endl;
        cout << "Minimum : " << *std::min_element(via_numbers_after_similarity_filtering.begin(), via_numbers_after_similarity_filtering.end()) << endl;
        cout << "Maximum : " << *std::max_element(via_numbers_after_similarity_filtering.begin(), via_numbers_after_similarity_filtering.end()) << endl;
        count = 0 ;
        for(auto x:via_numbers_after_similarity_filtering)
            count += x;
        cout << "Average : " << count / total << endl;
        cout << endl;

        cout << "*********** Cache Summary ***********" << endl;
        cout << "Minimum : " << *std::min_element(cache_size.begin(), cache_size.end()) / 1e6 << endl;
        cout << "Maximum : " << *std::max_element(cache_size.begin(), cache_size.end()) / 1e6 << endl;
        count = 0 ;
        for(auto x:cache_size)
            count += x;
        cout << "Average : " << ((float) count / query_points.size()) / 1e6  << endl;
        cout << endl;
//        cout << "Start measuring " << endl;
//        double avg_length = 0;
//        for(auto x:alternative_Paths){
//            // cout << endl;
//            std::sort(begin(x) , end(x), [](const tuple < vector<unsigned > , unsigned, double >& a,
//                                            const tuple < vector<unsigned > , unsigned, double >& b) -> bool
//            {
//                return std::get<2>(a) > std::get<2>(b);
//            });
//            /*for(int i = 0; i < x.size() ; i++){
//                cout << get<1>(x[i]) << "  " << get<2>(x[i]) << endl;
//            }*/
//
//            double max = 0;
//            for(int i = 0; i < num_of_alternative_paths ; i++){
//                for(int j = 0; j < num_of_alternative_paths ; j ++){
//                    if(i > j){
//                        double score = similarity_check(get<0>(x[i]), get<0>(x[j]), get<1>(x[i]), get<1>(x[j]), first_out, head, weight);
//                        // cout << score << endl;
//                        if (score > max){
//                            max = score;
//                        }
//                    }
//                }
//            }
//            s_score.push_back(max);
//
//            double bs_max = 0;
//            double lo_min = 1;
//            double bs_score, lo_score;
//            double total_lengths = 0;
//            for(int i = 0; i < num_of_alternative_paths ; i++){
//                // cout << score << endl;
//                std::tie(bs_score, lo_score) = get_Local_Optimality_and_Bounded_Stretch(get<0>(x[i]), lab, first_out, head, weight);;
//                // cout << bs_score << "   " << lo_score << endl;
//                if (bs_score > bs_max){
//                    bs_max = bs_score;
//                }
//                if (lo_score < lo_min){
//                    lo_min = lo_score;
//                }
//                total_lengths += get<1>(x[i]);
//            }
//            // cout << "Results "  << bs_max << "  " << lo_min << endl;
//            lo_scores.push_back(lo_min);
//            b_s_score.push_back(bs_max);
//            avg_length += (total_lengths / 3);
//        }

        /*cout << "***********  Similarity score for 3 alternative paths per query ***********" << endl;
        cout << "Minimum : " << *std::min_element(s_score.begin(), s_score.end()) << endl;
        cout << "Maximum : " << *std::max_element(s_score.begin(), s_score.end()) << endl;
        double s_count = 0 ;
        for(auto x:s_score)
            s_count += x;
        cout << "Average : " <<  s_count / s_score.size() << endl;
        cout << endl;

        cout << "***********  Bounded Stretch score for 3 alternative paths per query ***********" << endl;
        cout << "Minimum : " << *std::min_element(b_s_score.begin(), b_s_score.end()) << endl;
        cout << "Maximum : " << *std::max_element(b_s_score.begin(), b_s_score.end()) << endl;
        double b_s_count = 0 ;
        for(auto x:b_s_score)
            b_s_count += x;
        cout << "Average : " <<  b_s_count / b_s_score.size() << endl;
        cout << endl;

        cout << "***********  Local Optimality score for 3 alternative paths per query ***********" << endl;
        cout << "Minimum : " << *std::min_element(lo_scores.begin(), lo_scores.end()) << endl;
        cout << "Maximum : " << *std::max_element(lo_scores.begin(), lo_scores.end()) << endl;
        double lo_count = 0 ;
        for(auto x:lo_scores)
            lo_count += x;
        cout << "Average : " <<  lo_count / lo_scores.size() << endl;
        cout << endl;*/

        return 0;
    }catch(exception&err){
        cerr << "Stopped on exception : " << err.what() << endl;
    }
}