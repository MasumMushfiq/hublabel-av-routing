cmake_minimum_required(VERSION 3.13)
project(RoutingKit)

# --- Toolchain / flags (unchanged from your current file) ---
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_CXX_FLAGS "-O3 -DNDEBUG -mcpu=apple-m1")
set(DEV_CXX_FLAGS "-g -ggdb -O0 -fno-omit-frame-pointer")
set(RELEASE_CXX_FLAGS "-O3 -DNDEBUG")
set(CMAKE_CXX_FLAGS_DEBUG   "${CMAKE_CXX_FLAGS} ${DEV_CXX_FLAGS}")
set(CMAKE_CXX_FLAGS_RELEASE "${CMAKE_CXX_FLAGS} ${RELEASE_CXX_FLAGS}")

set(EXECUTABLE_OUTPUT_PATH ${CMAKE_BINARY_DIR}/../bin)
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -Xpreprocessor -fopenmp")
set(CMAKE_OSX_SYSROOT "/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk")
set(ZLIB_INCLUDE_DIR "/opt/homebrew/opt/zlib/include")

include_directories("/opt/homebrew/opt/libomp/include")
include_directories("/opt/homebrew/opt/google-sparsehash/include")

include_directories(include)
include_directories(src)
include_directories(planner)
include_directories(planner/external)

# --- Core sources (unchanged) ---
set(SRC
        include/routingkit/my_timer.h
        include/routingkit/bit_vector.h
        include/routingkit/constants.h
        include/routingkit/contraction_hierarchy.h
        include/routingkit/dijkstra.h
        include/routingkit/filter.h
        include/routingkit/geo_dist.h
        include/routingkit/geo_position_to_node.h
        include/routingkit/graph_util.h
        include/routingkit/id_mapper.h
        include/routingkit/id_queue.h
        include/routingkit/id_set_queue.h
        include/routingkit/inverse_vector.h
        include/routingkit/min_max.h
        include/routingkit/nested_dissection.h
        include/routingkit/osm_decoder.h
        include/routingkit/osm_graph_builder.h
        include/routingkit/osm_profile.h
        include/routingkit/osm_simple.h
        include/routingkit/permutation.h
        include/routingkit/sort.h
        include/routingkit/strongly_connected_component.h
        include/routingkit/tag_map.h
        include/routingkit/timer.h
        include/routingkit/timestamp_flag.h
        include/routingkit/vector_io.h
        include/routingkit/shortest_dijkstra_single.h
        include/routingkit/ch_dijkstra_single.h
        include/routingkit/ch_dijkstra_hl.h
        include/routingkit/ori_dijkstra.h

        src/searchnode.h
        src/modified_dijkstra.h
        src/cpool.h
        src/landmark.h
        src/my_timer.cpp
        src/bit_select.cpp
        src/bit_vector.cpp
        src/buffered_asynchronous_reader.cpp
        src/tree_node.h
        src/contraction_hierarchy.cpp
        src/expect.cpp
        src/file_data_source.cpp
        src/geo_position_to_node.cpp
        src/graph_util.cpp
        src/id_mapper.cpp
        src/nested_dissection.cpp
        src/osm_decoder.cpp
        src/osm_graph_builder.cpp
        src/osm_profile.cpp
        src/osm_simple.cpp
        src/protobuf.cpp
        src/strongly_connected_component.cpp
        src/timer.cpp
        src/vector_io.cpp
        src/verify.cpp

        src/bit_select.h
        src/buffered_asynchronous_reader.h
        src/emulate_gcc_builtin.h
        src/expect.h
        src/file_data_source.h
        src/protobuf.h
        src/verify.h
        src/CPD.h
        src/CPD.cpp
        src/DCPD.h
        src/DCPD.cpp
        src/my_timer.h
        src/my_timer.cpp

        src/construction.h
        src/coverage_ordering.h
        src/coverage_ordering_bp.h
        src/coverage_ordering_compress.h
        src/coverage_ordering_path.h
        src/graph.h
        src/graph_search.h
        src/heap.h
        src/labels.h
        src/ordering.h
        src/paras.h
        src/sse2neon.h
        src/time_util.h
)

# --- Planner sources (unchanged) ---
set(PLANNER_SRC
        planner/commuter.cpp
        planner/station.cpp
        planner/av_selection.cpp
        planner/baseline_greedy_assignment.cpp
        planner/hub_label_utils.cpp
        planner/edge_attrs.cpp
        planner/time_cost.cpp
)

set(ANALYSIS_SRC
        planner/baseline_calculator.cpp
        planner/comparison_utility.cpp
)

# --- existing executables (unchanged) ---
add_executable(construct ${SRC} construct.cpp)
add_executable(testing_hublabeling ${SRC} testing_hublabeling.cpp)
add_executable(testing_graph ${SRC} testing_graph.cpp)
add_executable(simulate_first_mile ${SRC} ${PLANNER_SRC} simulate_first_mile.cpp)

# --- OpenMP from Homebrew, same logic (unchanged) ---
find_library(omp_lib omp "/opt/homebrew/opt")
if (omp_lib)
    target_link_libraries(testing_hublabeling  ${omp_lib})
    target_link_libraries(testing_graph        ${omp_lib})
    target_link_libraries(simulate_first_mile  ${omp_lib})
endif()

# --- Threads / Zlib (unchanged) ---
find_package(Threads REQUIRED)
find_package(ZLIB REQUIRED)

target_link_libraries(construct        ZLIB::ZLIB Threads::Threads)
target_link_libraries(testing_hublabeling ZLIB::ZLIB Threads::Threads)
target_link_libraries(testing_graph    ZLIB::ZLIB Threads::Threads)
target_link_libraries(simulate_first_mile ZLIB::ZLIB Threads::Threads)

# =====================================================================
# --- OR-Tools: use local source+build (no find_package) ---
# =====================================================================
# =====================================================================
# OR-Tools (LOCAL BUILD) — no Homebrew, no find_package
# =====================================================================
# Adjust if your or-tools checkout is elsewhere:
set(ORT_ROOT   "$ENV{HOME}/Developer/or-tools")
set(ORT_BUILD  "${ORT_ROOT}/build")

if(NOT EXISTS "${ORT_BUILD}/lib/libortools.dylib")
    message(FATAL_ERROR "Missing ${ORT_BUILD}/lib/libortools.dylib. Build OR-Tools locally first.")
endif()

# Protobuf library from the local OR-Tools superbuild
find_library(PROTOBUF_LIB
        NAMES protobuf libprotobuf
        PATHS "${ORT_BUILD}/lib"
        NO_DEFAULT_PATH
)
if(NOT PROTOBUF_LIB)
    message(FATAL_ERROR "libprotobuf not found under ${ORT_BUILD}/lib")
endif()

# Headers: OR-Tools sources + generated headers + absl/protobuf headers from superbuild
include_directories(
        "${ORT_ROOT}"                      # ortools/ headers from source tree
        "${ORT_BUILD}"                     # generated: build/ortools/... (pb.h)
        "${ORT_BUILD}/_deps/absl-src"      # absl headers
        "${ORT_BUILD}/_deps/protobuf-src/src" # protobuf headers
)

# Where the linker should search for libs at build time
link_directories(
        "${ORT_BUILD}/lib"                 # libortools.dylib, libprotobuf.dylib
)

# =====================================================================
# --- config_loader library ---
# =====================================================================
add_library(config_loader
        planner/config_loader.cpp
        planner/config_loader.h
)

target_include_directories(config_loader PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}/planner
        ${CMAKE_CURRENT_SOURCE_DIR}/planner/external
)


# --- simulate_first_mile_ortools target ---
add_executable(simulate_first_mile_ortools
        ${SRC}
        ${PLANNER_SRC}
        ${ANALYSIS_SRC}
        planner/ortools_solver.cpp
        planner/av_metrics.cpp
        simulate_first_mile_ortools.cpp
)

# Protobuf generated headers reference an export macro; make it harmless
target_compile_definitions(simulate_first_mile_ortools PRIVATE OR_PROTO_DLL=)

# Link everything explicitly (no transitive CMake packages)
target_link_libraries(simulate_first_mile_ortools PRIVATE
        config_loader
        "${ORT_BUILD}/lib/libortools.dylib"
        "${PROTOBUF_LIB}"
        ZLIB::ZLIB
        Threads::Threads
)

# Ensure the built binary can find the dylibs at runtime (no DYLD hacks needed)
set_target_properties(simulate_first_mile_ortools PROPERTIES
        BUILD_WITH_INSTALL_RPATH ON
        INSTALL_RPATH "${ORT_BUILD}/lib"
        RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/../bin"
)