#include "opml.h"

#include "util.h"

#include <QXmlStreamReader>

namespace opml {

namespace {

QString label(const QXmlStreamAttributes &a) {
    for (const char *key : {"title", "text", "htmlUrl", "xmlUrl"}) {
        const QString v = a.value(QLatin1StringView(key)).toString().trimmed();
        if (!v.isEmpty())
            return v;
    }
    return {};
}

}  // namespace

bool parse(const QString &source, QList<Feed> *out, QString *error) {
    QXmlStreamReader r(source);
    r.setNamespaceProcessing(false);
    // The category of each open outline: a feed entry has none of its own
    // children, a folder names the category for what is inside it.
    QList<QString> categories{QString()};
    bool sawRoot = false;
    while (!r.atEnd()) {
        r.readNext();
        if (r.isStartElement()) {
            if (!sawRoot) {
                sawRoot = true;
                if (r.name().toString().toLower() != u"opml") {
                    *error = QStringLiteral("expected an OPML document");
                    return false;
                }
                categories.append(categories.last());
                continue;
            }
            QString category = categories.last();
            if (r.name().toString().toLower() == u"outline") {
                const auto a = r.attributes();
                const QString url = a.value(QLatin1StringView("xmlUrl")).toString().trimmed();
                if (!url.isEmpty()) {
                    out->append({url, label(a), a.value(QLatin1StringView("htmlUrl")).toString().trimmed(),
                                 a.value(QLatin1StringView("description")).toString().trimmed(), category});
                    // Anything nested in a feed entry is ignored.
                    r.skipCurrentElement();
                    continue;
                }
                category = label(a);
            }
            categories.append(category);
        } else if (r.isEndElement()) {
            if (categories.size() > 1)
                categories.removeLast();
        }
    }
    if (r.hasError()) {
        *error = r.errorString() + QStringLiteral(": line %1, column %2").arg(r.lineNumber()).arg(r.columnNumber());
        return false;
    }
    if (!sawRoot) {
        *error = QStringLiteral("no element found");
        return false;
    }
    return true;
}

QString render(const QList<Feed> &feeds, const QString &title) {
    auto e = [](const QString &s) { return util::escape(s, true); };
    auto line = [&](const Feed &f, const QString &indent) {
        QString s = indent + QStringLiteral("<outline text=\"%1\" title=\"%1\" type=\"rss\" xmlUrl=\"%2\"")
                                 .arg(e(f.title), e(f.url));
        if (!f.siteUrl.isEmpty())
            s += QStringLiteral(" htmlUrl=\"%1\"").arg(e(f.siteUrl));
        if (!f.description.isEmpty())
            s += QStringLiteral(" description=\"%1\"").arg(e(f.description));
        return s + QStringLiteral("/>\n");
    };
    QString out = QStringLiteral("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<opml version=\"2.0\">\n")
                  + QStringLiteral("  <head><title>%1</title></head>\n  <body>\n").arg(e(title));
    QStringList categories;
    for (const Feed &f : feeds) {
        if (f.category.isEmpty())
            out += line(f, QStringLiteral("    "));
        else if (!categories.contains(f.category))
            categories.append(f.category);
    }
    for (const QString &c : categories) {
        out += QStringLiteral("    <outline text=\"%1\" title=\"%1\">\n").arg(e(c));
        for (const Feed &f : feeds)
            if (f.category == c)
                out += line(f, QStringLiteral("      "));
        out += QStringLiteral("    </outline>\n");
    }
    out += QStringLiteral("  </body>\n</opml>\n");
    return out;
}

}  // namespace opml
