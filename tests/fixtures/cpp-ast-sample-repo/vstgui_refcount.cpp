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

// --- Safe: declare-then-pass (two-line ownership transfer) ---
void two_line_patterns(CViewContainer* container) {
    auto* label = new CTextLabel(CRect(), "test");
    container->addView(label);

    auto* view = new CView();
    container->replaceView(nullptr, view);
}

// --- Safe: member-variable assignment then addView (sub-pattern 1) ---
class MyView : public CViewContainer {
    CTextLabel* nameLabel_;
    CView* scaleSlider_;

    void initialize() {
        nameLabel_ = new CTextLabel(CRect(), "Name");
        addView(nameLabel_);

        scaleSlider_ = new CView();
        scaleSlider_->removeView(nullptr);  // some config calls in between
        addView(scaleSlider_);
    }
};

// --- Safe: return from factory method (sub-pattern 2) ---
class IPlugView {};
class VST3Editor : public IPlugView {
public:
    VST3Editor(void* ctrl, const char* a, const char* b) {}
};

IPlugView* createView(const char* name) {
    auto* editor = new VST3Editor(nullptr, "view", "editor.uidesc");
    return editor;
}

// --- Safe: static_cast in createInstance (sub-pattern 3) ---
class FUnknown {};
class IAudioProcessor : public FUnknown {};
class PlugProcessor : public IAudioProcessor {
public:
    static FUnknown* createInstance(void*) {
        return static_cast<IAudioProcessor*>(new PlugProcessor());
    }
};

// --- Unsafe: plain raw new, no suppression ---
void bad_patterns() {
    int* leaked = new int(42);
    char* buf = new char[1024];
}
