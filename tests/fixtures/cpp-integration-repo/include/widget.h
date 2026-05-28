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

class FancyWidget : public Widget {
public:
    explicit FancyWidget(std::string name, int style);
    int style() const;

private:
    int style_;
};

}  // namespace demo
