#include <algorithm>
#include <functional>
#include <iostream>
#include <vector>

template <typename T>
class Container {
public:
    void add(T item) { items_.push_back(std::move(item)); }
    size_t size() const noexcept { return items_.size(); }

    template <typename Pred>
    std::vector<T> filter(Pred predicate) const {
        std::vector<T> result;
        std::copy_if(items_.begin(), items_.end(),
                     std::back_inserter(result), predicate);
        return result;
    }

private:
    std::vector<T> items_;
};

template <typename T, typename U>
auto make_pair_sum(T a, U b) -> decltype(a + b) {
    return a + b;
}

int main() {
    Container<int> c;
    c.add(1);
    c.add(2);
    c.add(3);
    auto evens = c.filter([](int x) { return x % 2 == 0; });
    auto result = make_pair_sum(1, 2.5);
    std::cout << result << std::endl;
    return 0;
}
