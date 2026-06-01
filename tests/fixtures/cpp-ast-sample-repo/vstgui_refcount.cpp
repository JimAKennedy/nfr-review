// VSTGUI / VST3 SDK ownership-transfer patterns (mixed safe and unsafe)
#include <memory>

class CRect {};
class CTextLabel {
public:
    CTextLabel(CRect r, const char* t) {}
};
class CView {};
class CViewContainer {
public:
    void addView(CView* v) {}
    void removeView(CView* v) {}
    void replaceView(CView* old_v, CView* new_v) {}
};
class RangeParameter {
public:
    RangeParameter(const char* name, int id, const char* unit, double lo, double hi, double def) {}
};
class EditController {
public:
    void addParameter(RangeParameter* p) {}
};

// --- Safe: ownership-transfer calls ---
void setup_views(CViewContainer* container) {
    container->addView(new CTextLabel(CRect(), "Hello"));       // safe: addView takes ownership
    container->addView(new CView());                            // safe
    container->replaceView(nullptr, new CView());               // safe: replaceView
}

void setup_params(EditController* ctrl) {
    ctrl->addParameter(new RangeParameter("Gain", 1, "dB", -12.0, 12.0, 0.0)); // safe: addParameter
}

// --- Safe: REFCOUNT-SAFE comment annotation ---
void annotated_patterns() {
    CView* v = new CView(); // REFCOUNT-SAFE: transferred to framework
    auto* label = new CTextLabel(CRect(), "test"); // ownership transfer
}

// --- Unsafe: plain raw new, no suppression ---
void bad_patterns() {
    int* leaked = new int(42);
    char* buf = new char[1024];
}
