// The few things the app asks of the browser directly.
#pragma once

#include <QString>
#include <QUrl>

namespace platform {
QUrl origin();                       // where the reader is: the page's own origin
void navigate(const QString &path);  // leave the app for another page
void openUrl(const QString &url);    // a new tab, as a link with target=_blank would
void copyText(const QString &text);  // to the clipboard
}
