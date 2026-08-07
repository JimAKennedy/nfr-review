cmake_minimum_required(VERSION 3.14)
project(ctest_sample VERSION 1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
add_executable(ctest_sample src/main.cpp)

enable_testing()
add_test(NAME unit_tests COMMAND ctest_sample --test)

find_package(GTest QUIET)
if(GTest_FOUND)
    gtest_discover_tests(ctest_sample)
endif()
