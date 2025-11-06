#include <iostream>
#include <fstream>
#include <sstream>
#include <vector>
#include <string>
#include <unordered_map>

#include "planner/ortools_solver.h"
#include "planner/hub_label_utils.h"
#include "planner/edge_attrs.h"
#include "planner/av_selection.h"
#include "planner/id_types.h"
#include "planner/av_config.h"
#include "planner/commuter.h"
#include "planner/station.h"


int main(int argc, char* argv[])
{
    if (argc != 7)
    {
        std::cerr << "Usage: " << argv[0] << "\n"
            << "  commuters.csv stations.csv dist_label_prefix speed_table.txt assignments.csv av_routes.csv\n";
        return 1;
    }
    const std::string commuters_csv = argv[1];
    const std::string stations_csv = argv[2];
    const std::string dist_prefix = argv[3]; // dataset/MELTON/melton_dist
    const std::string speed_table = argv[4]; // files/melton_graph_speed.txt
    const std::string assignments = argv[5];
    const std::string av_routes_out = argv[6];

    // 1) Load inputs
    auto commuters = load_commuters(commuters_csv);
    auto stations = load_stations(stations_csv);
    if (stations.empty())
    {
        std::cerr << "No station rows.\n";
        return 2;
    }
    const int station_node = stations.front().node_id;

    // 2) Load distance labels (only)
    if (!init_distance_labels(dist_prefix))
    {
        std::cerr << "Failed to load distance labels: " << dist_prefix << "\n";
        return 3;
    }

    // 3) Speed/edge table for timing
    std::unordered_map<EdgeKey, EdgeAttr> edge_tbl = load_edge_attrs(speed_table);;
    if (edge_tbl.empty())
    {
        std::cerr << "Failed to load speed table: " << speed_table << "\n";
        return 4;
    }

    // 4) Expose your distance label path query
    auto query_path = [](int s, int t, std::vector<int>& out)-> int
    {
        return distance_mm(static_cast<NodeID>(s), static_cast<NodeID>(t), &out);
    };

    // 5) Build vehicle list (quick derivation from your default types/fleet sizes)
    std::vector<AVType> types = default_av_types(); // you already have this
    std::vector<OrToolsVehicle> vehicles;
    for (const auto& t : types)
    {
        for (int k = 0; k < t.fleet_size; ++k)
        {
            vehicles.push_back(OrToolsVehicle{t.name, t.capacity, t.max_speed_kmph});
        }
    }
    if (vehicles.empty())
    {
        // Fallback: one small car
        vehicles.push_back(OrToolsVehicle{"Car", 4});
    }

    // 6) Derive commuter_nodes in node-id order
    std::vector<int> commuter_nodes;
    commuter_nodes.reserve(commuters.size());
    for (const auto& c : commuters) commuter_nodes.push_back(c.origin_node);

    /*std::vector<int> pickup_earliest_min;
    pickup_earliest_min.reserve(commuters.size());
    for (const auto& c : commuters) pickup_earliest_min.push_back(c.tw.pickup_earliest_min);

    std::vector<int> drop_off_latest;
    drop_off_latest.reserve(commuters.size());
    for (const auto& c : commuters) drop_off_latest.push_back(c.tw.drop_off_latest_min);*/

    // Convert minutes to milliseconds
    std::vector<int64_t> pickup_earliest_ms;
    pickup_earliest_ms.reserve(commuters.size());
    for (const auto& c : commuters)
        pickup_earliest_ms.push_back(c.tw.pickup_earliest_min * 60LL * 1000LL);

    std::vector<int64_t> dropoff_latest_ms;
    dropoff_latest_ms.reserve(commuters.size());
    for (const auto& c : commuters)
        dropoff_latest_ms.push_back(c.tw.drop_off_latest_min * 60LL * 1000LL);

    // 7) Solve
    OrToolsConfig cfg;
    cfg.time_limit_seconds = 30;
    cfg.log_search = false;
    cfg.allow_partial_solution = true;  // ADD THIS LINE

    // --- DIAG A: distance matrix & savings (drop this BEFORE calling solve_pdptw) ---
    auto print_distance_diag = [&](const std::vector<int>& commuter_nodes,
                                   int station_node,
                                   const QueryPathFn& query_path)
    {
        const int N = static_cast<int>(commuter_nodes.size());
        if (N == 0)
        {
            std::cout << "[diag] no commuters\n";
            return;
        }

        auto node_of = [&](int m)
        {
            if (m == 0) return station_node; // depot
            return commuter_nodes[m - 1]; // C1..CN
        };

        const int M = N + 1; // depot + N customers
        std::vector<std::vector<long long>> D(M, std::vector<long long>(M, -1));
        bool any_offdiag_unreach = false;
        long long max_asym = 0;

        // Fill matrix (off-diagonal)
        for (int i = 0; i < M; ++i)
        {
            for (int j = 0; j < M; ++j)
            {
                if (i == j) continue;
                std::vector<int> leg;
                int d_mm = query_path(node_of(i), node_of(j), leg);
                if (d_mm <= 0)
                {
                    any_offdiag_unreach = true;
                    d_mm = -1;
                }
                D[i][j] = d_mm;
            }
        }

        // Asymmetry
        for (int i = 0; i < M; ++i)
            for (int j = i + 1; j < M; ++j)
                if (D[i][j] >= 0 && D[j][i] >= 0)
                    max_asym = std::max(max_asym, std::llabs((long long)D[i][j] - (long long)D[j][i]));

        auto lab = [&](int m)-> std::string
        {
            if (m == 0) return "DEPOT";
            std::ostringstream os;
            os << "C" << m << "(node=" << node_of(m) << ")";
            return os.str();
        };

        std::cout << "[diag] Distance matrix off-diagonal (mm):\n";
        std::cout << "         ";
        for (int j = 0; j < M; ++j) std::cout << std::setw(8) << (j == 0 ? "DEPOT" : ("C" + std::to_string(j)));
        std::cout << "\n";
        for (int i = 0; i < M; ++i)
        {
            std::cout << std::setw(6) << (i == 0 ? "DEPOT" : ("C" + std::to_string(i))) << " ";
            for (int j = 0; j < M; ++j)
            {
                if (i == j)
                {
                    std::cout << std::setw(8) << "--";
                    continue;
                }
                if (D[i][j] < 0) std::cout << std::setw(8) << "UNREACH";
                else std::cout << std::setw(8) << D[i][j];
            }
            std::cout << "\n";
        }
        std::cout << "[diag] any off-diagonal UNREACH? " << (any_offdiag_unreach ? "YES" : "NO") << "\n";
        std::cout << "[diag] max asymmetry |d(i,j)-d(j,i)| = " << max_asym << " mm\n";

        // Clarke–Wright savings s(i,j) = d(0,i) + d(0,j) - d(i,j) (i<j, i,j>0)
        struct S
        {
            int i, j;
            long long s;
        };
        std::vector<S> Slist;
        for (int i = 1; i <= N; ++i)
            for (int j = i + 1; j <= N; ++j)
            {
                if (D[0][i] < 0 || D[0][j] < 0 || D[i][j] < 0) continue;
                long long s = (long long)D[0][i] + (long long)D[0][j] - (long long)D[i][j];
                if (s > 0) Slist.push_back({i, j, s});
            }
        std::sort(Slist.begin(), Slist.end(), [](const S& a, const S& b) { return a.s > b.s; });
        std::cout << "[diag] savings pairs with s(i,j)>0: " << Slist.size()
            << " / " << (N * (N - 1) / 2) << "\n";
        std::cout << "[diag] Top savings (i,j,s_mm):\n";
        for (size_t k = 0; k < std::min<size_t>(10, Slist.size()); ++k)
        {
            std::cout << "  C" << Slist[k].i << ", C" << Slist[k].j << " : " << Slist[k].s << " mm\n";
        }
    };

    // call it:
    print_distance_diag(commuter_nodes, station_node, query_path);
    //------------------Diagnostic Ends----------------------------------


    // const bool ok = solve_pdptw(
    //     commuter_nodes, station_node, vehicles,
    //     query_path, edge_tbl,
    //     assignments, av_routes_out, cfg
    // );

    const bool ok = solve_cvrp_distance(commuter_nodes, station_node, vehicles, query_path, edge_tbl,
        pickup_earliest_ms, dropoff_latest_ms, assignments, av_routes_out, cfg);

    if (!ok) return 5;
    std::cout << "PDPTW solution written:\n  " << assignments << "\n  " << av_routes_out << "\n";
    return 0;
}
