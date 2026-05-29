// Latent space visualization window
#include "window.h"
#include "vstgui/lib/controls/ctextlabel.h"

void LatentSpaceWindow::init() {
    auto* title = new CTextLabel(CRect(0, 0, 200, 30));
    addView(title);
}
