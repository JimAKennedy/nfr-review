// Intentionally missing include guard for testing

#include <cstdlib>

struct LegacyData {
    int* values;
    int count;
};

LegacyData* create_legacy(int n);
void destroy_legacy(LegacyData* data);
