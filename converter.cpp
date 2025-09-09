//
// Created by Bojie Shen on 25/9/20.
//

#include <iostream>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>


using namespace std;
void load_data(string dimacs_file,vector<unsigned>& head,vector<unsigned>& tail,vector<unsigned>& weight){

    cout << "Loading data ... " << flush;

    ifstream in(dimacs_file);
    if(!in)
        throw runtime_error("Can not open \""+dimacs_file+"\"");

    string line;
    unsigned line_num = 0;
    unsigned next_arc = 0;

    unsigned node_count, arc_count;

    bool was_header_read = false;
    while(std::getline(in, line)){
        ++line_num;
        if(line.empty() ||line[0] == 'c')
            continue;

        std::istringstream lin(line);
        if(!was_header_read){
            was_header_read = true;
            std::string p, sp;
            if(!(lin >> p >> sp >> node_count >> arc_count))
                throw std::runtime_error("Can not parse header in dimacs file.");
            if(p != "p" || sp != "sp")
                throw std::runtime_error("Invalid header in dimacs file.");

            tail.resize(arc_count);
            head.resize(arc_count);
            weight.resize(arc_count);
        }else{
            std::string a;
            unsigned h, t, w;
            if(!(lin >> a >> t >> h >> w))
                throw std::runtime_error("Can not parse line num "+std::to_string(line_num)+" \""+line+"\" in dimacs file.");
            --h;
            --t;
            if(a != "a" || h >= node_count || t >= node_count)
                throw std::runtime_error("Invalid arc in line num "+std::to_string(line_num)+" \""+line+"\" in dimacs file.");
            if(next_arc < arc_count){
                head[next_arc] = h;
                tail[next_arc] = t;
                weight[next_arc] = w;
            }
            ++next_arc;
        }
    }

    if(next_arc != arc_count)
        throw std::runtime_error("The arc count in the header ("+to_string(arc_count)+") does not correspond with the actual number of arcs ("+to_string(next_arc)+").");

    cout << "done" << endl;


}



int main(int argc, char*argv[]){

    try{
        string dimacs_distance_file;
        string txt_file;
//        string weight_file;

        if(argc != 3){
            cerr << argv[0] << "dimacs_distane_file txt_file" << endl;
            return 1;
        }else{
            dimacs_distance_file = argv[1];
            txt_file = argv[2];
        }

        vector<unsigned> distance_head,distance_tail,distance;

        load_data(dimacs_distance_file,distance_head,distance_tail,distance);

        std::ofstream myFile(txt_file);
        bool should_remove = true;
        for(int i = 0 ; i < distance_head.size(); i ++){
            if(!should_remove){
                myFile<<distance_head[i]<<" "<<distance_tail[i]<<" "<<distance[i]<<"\n";
            }
            should_remove = !should_remove;
        }
        myFile.close();


        cout << "done" << endl;


    }catch(exception&err){
        cerr << "Stopped on exception : " << err.what() << endl;
    }
}
