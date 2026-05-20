#include <iostream>
#include <memory>
#include <vector>

#include "widget.h"
#include "legacy.h"

namespace demo {

Widget::Widget(std::string name) : name_(std::move(name)) {}
Widget::~Widget() = default;
const std::string& Widget::name() const { return name_; }

}  // namespace demo

void good_function() {
    auto w = std::make_unique<demo::Widget>("safe");
    std::cout << w->name() << std::endl;
}

void bad_memory() {
    int* raw = new int(42);
    delete raw;

    void* mem = malloc(128);
    free(mem);
}

void bad_exception() {
    try {
        throw std::runtime_error("oops");
    } catch (...) {
        // silently swallowed
    }
}

int main() {
    good_function();
    bad_memory();
    bad_exception();
    return 0;
}
