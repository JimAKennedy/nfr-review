project(BadProject)

set(CMAKE_CXX_FLAGS "-std=c++17 -Wall")

include(FetchContent)
FetchContent_Declare(
    googletest
    GIT_REPOSITORY https://github.com/google/googletest.git
    GIT_TAG main
)
FetchContent_Declare(
    fmt
    GIT_REPOSITORY https://github.com/fmtlib/fmt.git
    GIT_TAG master
)

FetchContent_MakeAvailable(googletest fmt)

add_executable(myapp main.cpp)
