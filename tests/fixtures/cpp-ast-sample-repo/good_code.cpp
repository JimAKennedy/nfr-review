#include "good_code.h"

#include <iostream>
#include <utility>

namespace example {

ResourceManager::ResourceManager() = default;

void ResourceManager::add_resource(std::unique_ptr<std::string> resource) {
    resources_.push_back(std::move(resource));
}

std::shared_ptr<std::string> ResourceManager::get_resource(int index) const {
    if (index < 0 || static_cast<size_t>(index) >= resources_.size()) {
        return nullptr;
    }
    return resources_[index];
}

size_t ResourceManager::count() const noexcept {
    return resources_.size();
}

}  // namespace example

int main() {
    auto mgr = example::ResourceManager();
    mgr.add_resource(std::make_unique<std::string>("hello"));
    auto res = mgr.get_resource(0);
    if (res) {
        std::cout << *res << std::endl;
    }
    return 0;
}
