// OPML, the portable backup format for subscriptions. Outlines nest
// arbitrarily, but only entries with xmlUrl are subscriptions.
#pragma once

#include <QList>
#include <QString>

namespace opml {

struct Feed {
    QString url, title, siteUrl, description, category;
};

// Returns false (and sets `error`) for anything that is not an OPML document.
bool parse(const QString &source, QList<Feed> *out, QString *error);
QString render(const QList<Feed> &feeds, const QString &title = QStringLiteral("Pulseboard subscriptions"));

}  // namespace opml
