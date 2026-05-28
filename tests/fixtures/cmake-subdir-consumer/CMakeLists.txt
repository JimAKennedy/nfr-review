cmake_minimum_required(VERSION 3.14)
project(SubdirPlugin VERSION 1.0.0)

set(CMAKE_CXX_STANDARD 17)

add_subdirectory(../cmake-shared-lib ${CMAKE_BINARY_DIR}/drumcore)

add_executable(subdir_plugin src/main.cpp)
target_link_libraries(subdir_plugin PRIVATE drumcore)
