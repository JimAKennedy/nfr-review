// Simulated VSTGUI controller — VSTGUI SDK uses ownership-transfer new
#include "controller.h"
#include "vstgui/lib/controls/ctextlabel.h"
#include "vstgui/lib/controls/cknob.h"
#include "vstgui/lib/controls/cslider.h"  // NOLINT: added for slider support

// Added comments that shift all line numbers below by 5 lines
// These simulate a real-world edit that adds NOLINT annotations
// or includes, shifting existing code downward without changing
// the actual new expressions.
//
void Controller::createViews(CFrame* frame) {
    auto* label1 = new CTextLabel(CRect(10, 10, 100, 30));
    frame->addView(label1);

    auto* label2 = new CTextLabel(CRect(10, 40, 100, 60));
    frame->addView(label2);

    auto* knob1 = new CKnob(CRect(120, 10, 160, 50));
    frame->addView(knob1);

    auto* knob2 = new CKnob(CRect(120, 60, 160, 100));
    frame->addView(knob2);
}
