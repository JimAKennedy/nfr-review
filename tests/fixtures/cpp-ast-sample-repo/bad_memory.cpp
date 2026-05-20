#include <cstdlib>
#include <cstring>
#include <iostream>

class LeakyBuffer {
public:
    LeakyBuffer(size_t size) {
        data_ = new char[size];
        raw_ptr_ = data_;
    }

    ~LeakyBuffer() {
        delete[] data_;
    }

    void leak_memory() {
        int* leaked = new int(42);
        std::cout << *leaked << std::endl;
    }

    void use_malloc() {
        void* block = malloc(1024);
        memset(block, 0, 1024);
        free(block);
    }

private:
    char* data_;
    char* raw_ptr_;
};

int* create_dangling() {
    int* p = new int(10);
    return p;
}

void double_delete() {
    int* x = new int(5);
    delete x;
    delete x;
}
