// Simulated VSTGUI controller — VSTGUI SDK uses ownership-transfer new
#include "controller.h"
#include "vstgui/lib/controls/ctextlabel.h"
#include "vstgui/lib/controls/cknob.h"

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
