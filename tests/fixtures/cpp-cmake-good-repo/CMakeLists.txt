cmake_minimum_required(VERSION 3.21)
project(GoodProject VERSION 1.0.0)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

include(FetchContent)
FetchContent_Declare(
    googletest
    GIT_REPOSITORY https://github.com/google/googletest.git
    GIT_TAG v1.14.0
)
FetchContent_Declare(
    fmt
    GIT_REPOSITORY https://github.com/fmtlib/fmt.git
    GIT_TAG 10.2.1
)

FetchContent_MakeAvailable(googletest fmt)

add_library(mylib src/lib.cpp)
target_compile_features(mylib PUBLIC cxx_std_17)
target_compile_options(mylib PRIVATE -Wall -Wextra -Wpedantic)

add_executable(myapp src/main.cpp)
target_link_libraries(myapp PRIVATE mylib fmt::fmt)

install(TARGETS mylib myapp DESTINATION lib)
