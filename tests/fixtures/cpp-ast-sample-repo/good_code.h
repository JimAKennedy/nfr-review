#pragma once

#include <memory>
#include <string>
#include <vector>

namespace example {

class ResourceManager {
public:
    ResourceManager();
    ~ResourceManager() = default;

    void add_resource(std::unique_ptr<std::string> resource);
    std::shared_ptr<std::string> get_resource(int index) const;
    size_t count() const noexcept;

private:
    std::vector<std::shared_ptr<std::string>> resources_;
};

}  // namespace example
