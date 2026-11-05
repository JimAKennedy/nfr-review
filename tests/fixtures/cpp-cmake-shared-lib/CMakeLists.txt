cmake_minimum_required(VERSION 3.14)
project(drumcore VERSION 1.0.0)

set(CMAKE_CXX_STANDARD 17)

add_library(drumcore STATIC
    src/engine.cpp
    src/sampler.cpp
)

target_include_directories(drumcore PUBLIC include)
install(TARGETS drumcore)
