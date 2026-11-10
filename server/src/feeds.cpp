#include "feeds.h"

#include "util.h"
#include "wasihttp.h"

#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QRegularExpression>
#include <QTimeZone>
#include <QXmlStreamReader>

#include <cstdio>
#include <memory>
#include <vector>

namespace feeds {

const char USER_AGENT[] = "pulseboard/0.3 (+https://github.com/codegod100/pulseboard)";

namespace {

const char ACCEPT_FEED[] =
    "application/xml,application/atom+xml,application/rss+xml,"
    "application/rdf+xml,application/feed+json,text/html;q=0.9";

// --- dates -------------------------------------------------------------------

QDateTime parseIso(QString s) {
    static const QRegularExpression iso(QStringLiteral(
        "^(\\d{4})-(\\d{2})-(\\d{2})(?:[T ](\\d{2}):(\\d{2})(?::(\\d{2})(?:[.,](\\d+))?)?)?"
        "\\s*(Z|[+-]\\d{2}(?::?\\d{2})?)?$"),
        QRegularExpression::CaseInsensitiveOption);
    const auto m = iso.match(s);
    if (!m.hasMatch())
        return {};
    const QDate date(m.captured(1).toInt(), m.captured(2).toInt(), m.captured(3).toInt());
    if (!date.isValid())
        return {};
    int msec = 0;
    if (!m.captured(7).isEmpty())
        msec = (m.captured(7) + QStringLiteral("000")).left(3).toInt();
    const QTime time(m.captured(4).toInt(), m.captured(5).toInt(), m.captured(6).toInt(), msec);
    if (!time.isValid())
        return {};
    int offset = 0;
    const QString z = m.captured(8);
    if (!z.isEmpty() && z.toUpper() != u"Z") {
        const QString d = QString(z).remove(u':');
        const int hh = d.mid(1, 2).toInt(), mm = d.size() >= 5 ? d.mid(3, 2).toInt() : 0;
        offset = (hh * 3600 + mm * 60) * (d[0] == u'-' ? -1 : 1);
    }
    return QDateTime(date, time, QTimeZone::fromSecondsAheadOfUtc(offset)).toUTC();
}

QDateTime parseRfc822(const QString &s) {
    static const QRegularExpression rfc(QStringLiteral(
        "^(?:[A-Za-z]+,?\\s*)?(\\d{1,2})\\s+([A-Za-z]{3})[A-Za-z]*\\.?,?\\s+(\\d{2,4}),?\\s+"
        "(\\d{1,2}):(\\d{1,2})(?::(\\d{1,2}))?(?:\\.\\d+)?\\s*([A-Za-z]+|[+-]\\d{4}|[+-]\\d{2}:\\d{2})?"));
    const auto m = rfc.match(s.trimmed());
    if (!m.hasMatch())
        return {};
    static const QStringList months = {"jan", "feb", "mar", "apr", "may", "jun",
                                       "jul", "aug", "sep", "oct", "nov", "dec"};
    const int month = int(months.indexOf(m.captured(2).toLower())) + 1;
    if (month == 0)
        return {};
    int year = m.captured(3).toInt();
    if (m.captured(3).size() == 2)
        year += year > 68 ? 1900 : 2000;
    else if (m.captured(3).size() == 3)
        year += 1900;
    const QDate date(year, month, m.captured(1).toInt());
    const QTime time(m.captured(4).toInt(), m.captured(5).toInt(), m.captured(6).toInt());
    if (!date.isValid() || !time.isValid())
        return {};
    int offset = 0;
    const QString z = m.captured(7).toUpper();
    static const QHash<QString, int> zones = {
        {"UT", 0}, {"UTC", 0}, {"GMT", 0}, {"Z", 0}, {"AST", -4}, {"ADT", -3},
        {"EST", -5}, {"EDT", -4}, {"CST", -6}, {"CDT", -5}, {"MST", -7}, {"MDT", -6},
        {"PST", -8}, {"PDT", -7}};
    if (z.startsWith(u'+') || z.startsWith(u'-')) {
        const QString d = QString(z).remove(u':');
        offset = (d.mid(1, 2).toInt() * 3600 + d.mid(3, 2).toInt() * 60) * (d[0] == u'-' ? -1 : 1);
    } else if (zones.contains(z)) {
        offset = zones.value(z) * 3600;
    }
    return QDateTime(date, time, QTimeZone::fromSecondsAheadOfUtc(offset)).toUTC();
}

// --- XML ---------------------------------------------------------------------

struct Element {
    QString name;  // local name
    QList<QPair<QString, QString>> attrs;  // local names
    QString text;  // all text inside, in document order (CDATA included)
    std::vector<std::unique_ptr<Element>> children;
};

QString localName(QStringView q) {
    const qsizetype c = q.lastIndexOf(u':');
    return (c < 0 ? q : q.mid(c + 1)).toString();
}

std::unique_ptr<Element> readXml(QXmlStreamReader &r, QString *error) {
    std::unique_ptr<Element> root;
    std::vector<Element *> stack;
    while (!r.atEnd()) {
        r.readNext();
        if (r.isStartElement()) {
            auto e = std::make_unique<Element>();
            e->name = localName(r.qualifiedName());
            for (const auto &a : r.attributes())
                e->attrs.append({localName(a.qualifiedName()), a.value().toString()});
            Element *raw = e.get();
            if (stack.empty()) {
                if (root) {
                    *error = QStringLiteral("junk after document element");
                    return nullptr;
                }
                root = std::move(e);
            } else {
                stack.back()->children.push_back(std::move(e));
            }
            stack.push_back(raw);
        } else if (r.isEndElement()) {
            if (!stack.empty())
                stack.pop_back();
        } else if (r.isCharacters() || r.isEntityReference()) {
            const QString t = r.isEntityReference() ? r.text().toString() : r.text().toString();
            for (Element *e : stack)
                e->text += t;
        }
    }
    if (r.hasError()) {
        *error = r.errorString() + QStringLiteral(": line %1, column %2").arg(r.lineNumber()).arg(r.columnNumber());
        return nullptr;
    }
    if (!root) {
        *error = QStringLiteral("no element found");
        return nullptr;
    }
    return root;
}

const Element *child(const Element *n, const char *name) {
    if (!n)
        return nullptr;
    for (const auto &c : n->children)
        if (c->name == QLatin1StringView(name))
            return c.get();
    return nullptr;
}

QList<const Element *> children(const Element *n, const char *name) {
    QList<const Element *> out;
    if (!n)
        return out;
    for (const auto &c : n->children)
        if (c->name == QLatin1StringView(name))
            out.append(c.get());
    return out;
}

QString textOf(const Element *n, const char *name) {
    const Element *c = child(n, name);
    return c ? c->text.trimmed() : QString();
}

QString attrOf(const Element *n, const char *name) {
    if (!n)
        return {};
    for (const auto &[k, v] : n->attrs)
        if (k == QLatin1StringView(name))
            return v;
    return {};
}

QString cleanFavicon(const QString &url) {
    const QString u = url.trimmed();
    return util::isHttpUrl(u) ? u : QString();
}

// Prefer rel="alternate" (or no rel), then the first link. A feed whose
// first link is rel="self" would otherwise point every article at the feed.
QString pickAtomLink(const Element *entry) {
    QString first;
    for (const Element *link : children(entry, "link")) {
        const QString href = attrOf(link, "href");
        if (href.isEmpty())
            continue;
        if (first.isEmpty())
            first = href;
        const QString rel = attrOf(link, "rel");
        if (rel.isEmpty() || rel == u"alternate")
            return href;
    }
    return first;
}

// --- formats -----------------------------------------------------------------

Feed convertRss(const Element *root, const QString &url) {
    const Element *channel = child(root, "channel");
    const Element *image = child(channel, "image");
    Feed f;
    f.url = url;
    f.title = textOf(channel, "title");
    f.siteUrl = textOf(channel, "link");
    f.description = textOf(channel, "description");
    f.kind = QStringLiteral("rss");
    f.faviconUrl = cleanFavicon(textOf(image, "url"));
    for (const Element *item : children(channel, "item")) {
        Article a;
        a.guid = textOf(item, "guid");
        a.title = textOf(item, "title");
        a.url = textOf(item, "link");
        // content:encoded is the full body; description is the summary.
        a.content = textOf(item, "encoded");
        a.summary = textOf(item, "description");
        a.author = textOf(item, "author");
        if (a.author.isEmpty())
            a.author = textOf(item, "creator");
        QString date = textOf(item, "pubDate");
        if (date.isEmpty())
            date = textOf(item, "date");
        a.published = parseTime(date);
        if (a.guid.isEmpty())
            a.guid = a.url;
        f.articles.append(a);
    }
    return f;
}

Feed convertRdf(const Element *root, const QString &url) {
    const Element *channel = child(root, "channel");
    Feed f;
    f.url = url;
    f.title = textOf(channel, "title");
    f.siteUrl = textOf(channel, "link");
    f.description = textOf(channel, "description");
    f.kind = QStringLiteral("rss");
    // In RDF the items are siblings of <channel>, not inside it.
    for (const Element *item : children(root, "item")) {
        Article a;
        a.title = textOf(item, "title");
        a.url = textOf(item, "link");
        a.content = textOf(item, "encoded");
        a.summary = textOf(item, "description");
        a.author = textOf(item, "creator");
        a.published = parseTime(textOf(item, "date"));
        a.guid = attrOf(item, "about");
        if (a.guid.isEmpty())
            a.guid = a.url;
        f.articles.append(a);
    }
    return f;
}

Feed convertAtom(const Element *root, const QString &url) {
    Feed f;
    f.url = url;
    f.title = textOf(root, "title");
    f.siteUrl = pickAtomLink(root);
    f.description = textOf(root, "subtitle");
    f.kind = QStringLiteral("atom");
    QString icon = textOf(root, "icon");
    if (icon.isEmpty())
        icon = textOf(root, "logo");
    f.faviconUrl = cleanFavicon(icon);
    for (const Element *entry : children(root, "entry")) {
        Article a;
        a.guid = textOf(entry, "id");
        a.title = textOf(entry, "title");
        a.url = pickAtomLink(entry);
        a.content = textOf(entry, "content");
        a.summary = textOf(entry, "summary");
        a.author = textOf(child(entry, "author"), "name");
        a.published = parseTime(textOf(entry, "published"));
        a.updated = parseTime(textOf(entry, "updated"));
        if (a.guid.isEmpty())
            a.guid = a.url;
        // Atom requires <updated> but not <published>.
        if (!a.published.isValid())
            a.published = a.updated;
        f.articles.append(a);
    }
    return f;
}

QString str(const QJsonValue &v) {
    return v.isString() ? v.toString() : QString();
}

Feed convertJson(const QJsonObject &doc, const QString &url) {
    Feed f;
    f.url = url;
    f.title = str(doc.value("title"));
    f.siteUrl = str(doc.value("home_page_url"));
    f.description = str(doc.value("description"));
    f.kind = QStringLiteral("json");
    f.faviconUrl = cleanFavicon(str(doc.value("icon")));
    for (const QJsonValue &v : doc.value("items").toArray()) {
        if (!v.isObject())
            continue;
        const QJsonObject item = v.toObject();
        Article a;
        const QJsonValue id = item.value("id");
        if (id.isString())
            a.guid = id.toString();
        else if (id.isDouble())
            a.guid = id.toVariant().toString();
        a.title = str(item.value("title"));
        a.url = str(item.value("url"));
        a.content = str(item.value("content_html"));
        if (a.content.isEmpty())
            a.content = str(item.value("content_text"));
        a.summary = str(item.value("summary"));
        a.published = parseTime(str(item.value("date_published")));
        a.updated = parseTime(str(item.value("date_modified")));
        if (item.value("author").isObject())
            a.author = str(item.value("author").toObject().value("name"));
        const QJsonArray authors = item.value("authors").toArray();
        if (a.author.isEmpty() && !authors.isEmpty() && authors.first().isObject())
            a.author = str(authors.first().toObject().value("name"));
        if (a.guid.isEmpty())
            a.guid = a.url;
        f.articles.append(a);
    }
    return f;
}

// HTML named entities (&nbsp;, &mdash;) are undefined in XML, and plenty of
// feeds use them anyway. Rewrite them as numeric references.
QString fixEntities(const QString &text) {
    static const QRegularExpression entity(QStringLiteral("&([A-Za-z][A-Za-z0-9]*);"));
    static const QStringList xml = {"amp", "lt", "gt", "quot", "apos"};
    QString out;
    qsizetype last = 0;
    auto it = entity.globalMatch(text);
    while (it.hasNext()) {
        const auto m = it.next();
        out += QStringView(text).mid(last, m.capturedStart() - last);
        last = m.capturedEnd();
        const QString name = m.captured(1);
        if (xml.contains(name)) {
            out += m.captured(0);
            continue;
        }
        const auto e = util::namedEntity(name.toUtf8() + ';');
        if (e && !e->isEmpty()) {
            for (char32_t cp : e->toUcs4())
                out += QStringLiteral("&#%1;").arg(uint(cp));
        } else {
            out += QStringLiteral("&amp;") + name + u';';
        }
    }
    out += QStringView(text).mid(last);
    return out;
}

std::unique_ptr<Element> parseXml(const QByteArray &body, QString *error) {
    QXmlStreamReader r(body);
    r.setNamespaceProcessing(false);
    QString first;
    if (auto root = readXml(r, &first))
        return root;
    QString text = QString::fromUtf8(body);
    if (text.startsWith(QChar(0xfeff)))
        text.remove(0, 1);
    static const QRegularExpression decl(QStringLiteral("^\\s*<\\?xml[^>]*\\?>"));
    text.remove(decl);
    QXmlStreamReader again(fixEntities(text));
    again.setNamespaceProcessing(false);
    QString second;
    if (auto root = readXml(again, &second))
        return root;
    *error = QStringLiteral("not valid XML: ") + first;
    return nullptr;
}

QString describeRefusal(const http::Response &res) {
    const QString server = QString::fromUtf8(res.headers.get("server"));
    static const QRegularExpression tags(QStringLiteral("<[^>]*>"));
    QString text = QString::fromUtf8(res.body);
    text.replace(tags, QStringLiteral(" "));
    text = text.simplified();
    QString out = server.isEmpty() ? QString() : QStringLiteral(" from ") + server;
    if (!text.isEmpty())
        out += QStringLiteral(": ") + (text.size() > 160 ? text.left(160) + QChar(0x2026) : text);
    return out;
}

bool isCloudflareChallenge(const http::Response &res) {
    if (res.headers.get("cf-mitigated") == "challenge")
        return true;
    return (res.status == 403 || res.status == 429 || res.status == 503)
           && res.headers.get("server").toLower() == "cloudflare";
}

bool isRetryable(int status) {
    return status == 429 || status >= 500;
}

}  // namespace

QDateTime parseTime(const QString &raw) {
    const QString s = raw.trimmed();
    if (s.isEmpty())
        return {};
    QDateTime t = parseIso(s);
    if (!t.isValid())
        t = parseRfc822(s);
    return t;
}

bool parse(const QByteArray &body, const QString &url, Feed *out, QString *error) {
    QByteArray trimmed = body.trimmed();
    if (trimmed.startsWith("\xef\xbb\xbf"))
        trimmed = trimmed.mid(3).trimmed();
    if (trimmed.isEmpty()) {
        *error = QStringLiteral("empty document");
        return false;
    }
    if (trimmed.startsWith('{')) {
        QJsonParseError perr;
        const QJsonDocument doc = QJsonDocument::fromJson(trimmed, &perr);
        if (perr.error != QJsonParseError::NoError) {
            *error = QStringLiteral("not valid JSON");
            return false;
        }
        if (!doc.isObject()) {
            *error = QStringLiteral("not a JSON Feed");
            return false;
        }
        *out = convertJson(doc.object(), url);
        return true;
    }
    auto root = parseXml(trimmed, error);
    if (!root)
        return false;
    if (root->name == u"rss")
        *out = convertRss(root.get(), url);
    else if (root->name == u"feed")
        *out = convertAtom(root.get(), url);
    else if (root->name == u"RDF")
        *out = convertRdf(root.get(), url);
    else {
        *error = QStringLiteral("unrecognised feed root element: ") + root->name;
        return false;
    }
    return true;
}

QList<Result> fetchAll(const QList<Request> &reqs, int retries, int baseDelayMs) {
    QList<Result> results(reqs.size());
    QList<qsizetype> pending;
    for (qsizetype i = 0; i < reqs.size(); ++i) {
        if (!util::isHttpUrl(reqs[i].url))
            results[i].error = QStringLiteral("not an http(s) URL: ") + reqs[i].url;
        else
            pending.append(i);
    }
    for (int attempt = 0; attempt <= retries && !pending.isEmpty(); ++attempt) {
        if (attempt)
            http::sleepMs(baseDelayMs * (1 << (attempt - 1)));
        QList<http::Outgoing> outgoing;
        for (qsizetype i : pending) {
            http::Outgoing o;
            o.url = reqs[i].url;
            o.headers.set("accept", ACCEPT_FEED);
            o.headers.set("user-agent", USER_AGENT);
            if (!reqs[i].etag.isEmpty())
                o.headers.set("if-none-match", reqs[i].etag.toUtf8());
            if (!reqs[i].lastModified.isEmpty())
                o.headers.set("if-modified-since", reqs[i].lastModified.toUtf8());
            outgoing.append(o);
        }
        const QList<http::Response> got = http::fetchAll(outgoing, 8);
        QList<qsizetype> again;
        for (qsizetype k = 0; k < pending.size(); ++k) {
            const qsizetype i = pending[k];
            const QString &url = reqs[i].url;
            const http::Response &res = got[k];
            Result &r = results[i];
            if (!res.error.isEmpty()) {  // the connection never completed
                r.error = QStringLiteral("fetching %1: %2").arg(url, res.error);
                again.append(i);
                continue;
            }
            if (res.status == 304) {
                r.ok = true;
                r.notModified = true;
                r.etag = reqs[i].etag;
                r.lastModified = reqs[i].lastModified;
                continue;
            }
            if (res.status >= 200 && res.status < 300) {
                QString err;
                if (!parse(res.body, url, &r.feed, &err)) {
                    r.error = QStringLiteral("parsing %1: %2").arg(url, err);
                    continue;
                }
                r.ok = true;
                r.error.clear();
                r.etag = QString::fromUtf8(res.headers.get("etag"));
                r.lastModified = QString::fromUtf8(res.headers.get("last-modified"));
                continue;
            }
            r.error = QStringLiteral("fetching %1: HTTP %2%3").arg(url).arg(res.status).arg(describeRefusal(res));
            std::fprintf(stderr, "pulseboard: feed %s: HTTP %d\n", qPrintable(url), res.status);
            if (isCloudflareChallenge(res)) {
                // Retrying cannot get past a challenge page, so stop and say
                // plainly what happened.
                r.error = QStringLiteral(
                    "fetching %1: HTTP %2: the site's Cloudflare bot protection refused the fetch "
                    "(it served a challenge page, not the feed); the site owner would need to "
                    "allow feed readers").arg(url).arg(res.status);
                continue;
            }
            if (isRetryable(res.status))
                again.append(i);
        }
        pending = again;
    }
    return results;
}

}  // namespace feeds
