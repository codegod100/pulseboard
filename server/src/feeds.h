// Fetching and parsing RSS, RDF, Atom and JSON Feed.
//
// Ported from the Python server's feeds.py. Feeds in the wild are not
// well-formed in the way a spec implies, so the rules that matter are the
// fallbacks: a missing GUID falls back to the link, a missing date stays empty
// rather than becoming "now", and an unparseable date does not discard the
// article. Elements are matched by local name, ignoring namespaces.
#pragma once

#include <QDateTime>
#include <QList>
#include <QString>

namespace feeds {

extern const char USER_AGENT[];

struct Article {
    QString guid, title, url, author, content, summary;
    QDateTime published, updated;  // invalid when unknown
};

struct Feed {
    QString url, title, siteUrl, description, kind, faviconUrl;
    QList<Article> articles;
};

// Best effort, always UTC; invalid when it cannot be read.
QDateTime parseTime(const QString &raw);

// Sniff the format and parse. On failure returns false and sets `error`.
bool parse(const QByteArray &body, const QString &url, Feed *out, QString *error);

struct Request {
    QString url, etag, lastModified;
};

struct Result {
    bool ok = false;
    bool notModified = false;  // 304 to last time's validators
    Feed feed;
    QString etag, lastModified;
    QString error;
};

// Fetch and parse several feeds at once, retrying only what is worth
// retrying (429 and 5xx, and connections that never completed).
QList<Result> fetchAll(const QList<Request> &reqs, int retries = 2, int baseDelayMs = 500);

}  // namespace feeds
