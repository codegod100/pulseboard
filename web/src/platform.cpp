#include "platform.h"

#ifdef __EMSCRIPTEN__
#include <emscripten.h>
#include <emscripten/val.h>

using emscripten::val;

EM_JS(void, pb_copy_text, (const char *s), {
    const t = UTF8ToString(s);
    if (navigator.clipboard) navigator.clipboard.writeText(t).catch(() => {});
});

// index.html gives the <a> around the canvas this link while the pointer is on
// it, so a right click gets the browser's own menu: open in new tab, copy link.
EM_JS(void, pb_hover_link, (const char *s), {
    if (window.pbHoverLinkChanged) window.pbHoverLinkChanged(UTF8ToString(s));
});

namespace platform {
QUrl origin() {
    return QUrl(QString::fromStdString(val::global("location")["origin"].as<std::string>()) + "/");
}
void navigate(const QString &path) {
    val::global("location").call<void>("assign", path.toStdString());
}
void openUrl(const QString &url) {
    val::global("window").call<val>("open", url.toStdString(), std::string("_blank"),
                                    std::string("noopener"));
}
void copyText(const QString &text) { pb_copy_text(text.toUtf8().constData()); }
void hoverLink(const QString &url) { pb_hover_link(url.toUtf8().constData()); }
}

#else  // a desktop build, for working on the UI without a browser
#include <QClipboard>
#include <QDesktopServices>
#include <QGuiApplication>
#include <QDebug>

namespace platform {
QUrl origin() {
    const QByteArray base = qgetenv("PULSEBOARD_BASE");
    return QUrl(base.isEmpty() ? QStringLiteral("http://127.0.0.1:8765/") : QString::fromUtf8(base) + "/");
}
void navigate(const QString &path) {
    qWarning() << "navigate to" << path;
}
void openUrl(const QString &url) { QDesktopServices::openUrl(QUrl(url)); }
void copyText(const QString &text) { QGuiApplication::clipboard()->setText(text); }
void hoverLink(const QString &) {}
}
#endif
