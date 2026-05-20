cmake_minimum_required(VERSION 3.21)
project(IntegrationDemo VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)

include(FetchContent)

FetchContent_Declare(
    googletest
    GIT_REPOSITORY https://github.com/google/googletest.git
    GIT_TAG v1.14.0
)

FetchContent_Declare(
    spdlog
    GIT_REPOSITORY https://github.com/gabime/spdlog.git
    GIT_TAG main
)

FetchContent_MakeAvailable(googletest spdlog)

add_executable(demo src/main.cpp)
target_compile_features(demo PRIVATE cxx_std_17)
target_compile_options(demo PRIVATE -Wall -Wextra -Wpedantic)

install(TARGETS demo DESTINATION bin)
