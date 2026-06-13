# Melton canonical input backup

This folder preserves the canonical Melton input files used for the completed

primary case in the SIGSPATIAL 2026 AV fleet-composition experiments.

Main paper demand:

- `commuters_residential.csv`

- `commuters_residential_metadata.json`

These represent the final residential-origin setting. Myki provides temporal

station-arrival/tap-on demand, while spatial origins are sampled from residential

address candidates mapped to reachable road-network nodes.

Network inputs:

- `melton_nodes_lat_lon.csv`

- `melton_graph_speed.txt`

Residential origin candidate inputs:

- `melton_residential_candidate_nodes.csv`

- `melton_residential_candidate_points.csv`

- `melton_residential_candidate_node_mapping.csv`

- `melton_residential_candidates_metadata.json`

Legacy/debug demand, if present:

- `legacy_commuters_reachable_nodes.csv`

- `legacy_commuters_reachable_nodes_metadata.json`

The legacy reachable-node commuter file is not the main paper setting. It is

kept only for tracing earlier experiments if needed.


