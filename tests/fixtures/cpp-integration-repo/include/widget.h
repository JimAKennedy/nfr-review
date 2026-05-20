#pragma once

#include <memory>
#include <string>

namespace demo {

class Widget {
public:
    explicit Widget(std::string name);
    ~Widget();
    const std::string& name() const;

private:
    std::string name_;
};

}  // namespace demo
