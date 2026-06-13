# Melton canonical network artifacts

The Melton main-case experiments use the existing canonical network, hub-label,
residential-candidate, commuter, and matrix artifacts already present in this
repository/workspace.

These files were generated earlier using the previous map-processing environment.
That exact environment is no longer available, and rerunning the pyrosm extraction
with the current environment produces a slightly different road graph.

For this paper, Melton remains the completed primary case using the existing
canonical artifacts. The new generic OSM conversion script in `python/` is used
for additional transferability stations such as Caulfield and Pakenham, where all
station-specific files are generated consistently within the current project.
EOF
