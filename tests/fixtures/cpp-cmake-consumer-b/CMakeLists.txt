cmake_minimum_required(VERSION 3.14)
project(DrumPostProcessor VERSION 1.5.0)

set(CMAKE_CXX_STANDARD 17)

include(FetchContent)

FetchContent_Declare(
    drumcore
    GIT_REPOSITORY https://github.com/example-org/drumcore.git
    GIT_TAG v1.0.0
)
FetchContent_MakeAvailable(drumcore)

add_executable(drum_postprocessor src/main.cpp)
target_link_libraries(drum_postprocessor PRIVATE drumcore)
