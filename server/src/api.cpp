// The routes: the same JSON API the Python server (and the Nim reader before
// it) served, so the Qt client need not care which one is behind it. Each
// request is handled start to finish here; `wasmtime serve` gives every
// request a fresh instance, so nothing is kept between them but the database.

#include "db.h"
#include "feeds.h"
#include "html.h"
#include "oauth.h"
#include "opml.h"
#include "pages.h"
#include "store.h"
#include "util.h"
#include "wasihttp.h"

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QSet>

#include <cstdio>

namespace {

// A session ends after this long without use; every authenticated request
// pushes the expiry forward, at most once a day.
constexpr qint64 SESSION_IDLE_LIMIT = 30 * 24 * 60 * 60;
constexpr qint64 SESSION_RENEW_EVERY = 24 * 60 * 60;
// The cookie only carries the token; the row decides whether it is still
// good. Browsers cap Max-Age at 400 days.
constexpr qint64 SESSION_COOKIE_MAX_AGE = 400 * 24 * 60 * 60;
const QByteArray COOKIE = "pulseboard_session";

// How many feeds one request may fetch.
constexpr int MAX_FEEDS_PER_REQUEST = 40;
// The client refreshes every time it opens; a feed fetched this recently (by
// that or by the cron run) is not fetched again.
constexpr int FRESH_MINUTES = 10;
constexpr qsizetype MAX_OPML = 1000000;

const QSet<QString> API_ROOTS = {"feeds", "articles", "unread", "opml", "refresh", "read",
                                 "read-all", "fetch-content"};

using http::Request;
using http::Response;

void logf(const QString &msg) {
    std::fprintf(stderr, "pulseboard: %s\n", qPrintable(msg));
}

// --- responses -------------------------------------------------------------------

Response json(const QJsonValue &v, int status = 200) {
    Response r;
    r.status = status;
    r.headers.set("content-type", "application/json");
    r.body = v.isArray() ? QJsonDocument(v.toArray()).toJson(QJsonDocument::Compact)
                         : QJsonDocument(v.toObject()).toJson(QJsonDocument::Compact);
    return r;
}

Response fail(int status, const QString &msg) {
    return json(QJsonObject{{"error", msg}}, status);
}

Response htmlPage(const QString &body, int status = 200) {
    Response r;
    r.status = status;
    r.headers.set("content-type", "text/html; charset=utf-8");
    r.body = body.toUtf8();
    return r;
}

Response redirect(const QString &location, int status = 303, const QByteArray &cookie = {}) {
    Response r;
    r.status = status;
    r.headers.set("location", location.toUtf8());
    if (!cookie.isNull())
        r.headers.set("set-cookie", cookie);
    return r;
}

QByteArray sessionCookie(const QString &token, qint64 maxAge) {
    return COOKIE + '=' + token.toUtf8() + "; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age="
           + QByteArray::number(maxAge);
}

// --- requests --------------------------------------------------------------------

// Query string and form body together. Clients send parameters in either, as
// they did to the Nim reader, so routes read them from here.
struct Params {
    util::Pairs items;

    QString get(const char *name, const QString &def = {}) const {
        for (const auto &[k, v] : items)
            if (k == QLatin1StringView(name))
                return v;
        return def;
    }
    qint64 getInt(const char *name, qint64 def) const {
        bool ok = false;
        const qint64 v = get(name).trimmed().toLongLong(&ok);
        return ok ? v : def;
    }
};

util::Pairs multipart(const QByteArray &body, const QByteArray &contentType) {
    util::Pairs out;
    const qsizetype b = contentType.indexOf("boundary=");
    if (b < 0)
        return out;
    QByteArray boundary = contentType.mid(b + 9);
    if (const qsizetype semi = boundary.indexOf(';'); semi >= 0)
        boundary.truncate(semi);
    boundary = boundary.trimmed();
    if (boundary.startsWith('"') && boundary.endsWith('"') && boundary.size() >= 2)
        boundary = boundary.mid(1, boundary.size() - 2);
    const QByteArray delim = "--" + boundary;
    qsizetype pos = body.indexOf(delim);
    while (pos >= 0) {
        pos += delim.size();
        if (body.mid(pos, 2) == "--")
            break;
        const qsizetype headEnd = body.indexOf("\r\n\r\n", pos);
        if (headEnd < 0)
            break;
        const QByteArray head = body.mid(pos, headEnd - pos);
        const qsizetype next = body.indexOf("\r\n" + delim, headEnd + 4);
        if (next < 0)
            break;
        const QByteArray value = body.mid(headEnd + 4, next - headEnd - 4);
        QString name;
        bool isFile = false;
        for (const QByteArray &line : head.split('\n')) {
            const QByteArray l = line.trimmed();
            if (!l.toLower().startsWith("content-disposition:"))
                continue;
            for (const QByteArray &part : l.split(';')) {
                const QByteArray p = part.trimmed();
                if (p.startsWith("name="))
                    name = QString::fromUtf8(p.mid(5)).remove(u'"');
                else if (p.startsWith("filename="))
                    isFile = true;
            }
        }
        // As the Python server did, only text fields count, not uploads.
        if (!name.isEmpty() && !isFile)
            out.append({name, QString::fromUtf8(value)});
        pos = next + 2;
    }
    return out;
}

Params paramsOf(const Request &req) {
    Params p;
    p.items = util::parseQuery(req.query);
    if (req.method == "POST" || req.method == "PUT" || req.method == "DELETE") {
        const QByteArray ctype = req.headers.get("content-type");
        if (ctype.contains("application/x-www-form-urlencoded") || ctype.isEmpty())
            p.items += util::parseQuery(req.body);
        else if (ctype.contains("multipart/form-data"))
            p.items += multipart(req.body, ctype);
    }
    return p;
}

QString cookie(const Request &req, const QByteArray &name) {
    for (const QByteArray &part : req.headers.get("cookie").split(';')) {
        const QByteArray kv = part.trimmed();
        const qsizetype eq = kv.indexOf('=');
        if (eq > 0 && kv.left(eq) == name)
            return QString::fromUtf8(kv.mid(eq + 1));
    }
    return {};
}

// Where the reader is served from, which AT Protocol sign-in names as the
// client. Pinned by PUBLIC_ORIGIN when set; behind a proxy (Fly), from the
// X-Forwarded headers; else the request itself.
QString origin(const Request &req) {
    QString pinned = qEnvironmentVariable("PUBLIC_ORIGIN");
    while (pinned.endsWith(u'/'))
        pinned.chop(1);
    if (!pinned.isEmpty())
        return pinned;
    const QString proto = QString::fromUtf8(req.headers.get("x-forwarded-proto").split(',').first()).trimmed();
    const QString host = QString::fromUtf8(req.headers.get("x-forwarded-host").split(',').first()).trimmed();
    return (proto.isEmpty() ? QString::fromUtf8(req.scheme.isEmpty() ? "http" : req.scheme) : proto)
           + QStringLiteral("://") + (host.isEmpty() ? QString::fromUtf8(req.authority) : host);
}

// --- JSON shapes -----------------------------------------------------------------

QJsonObject articleJson(const Row &a) {
    QString content = text(a, "full_content");
    if (content.isEmpty())
        content = text(a, "content");
    QString feedTitle = text(a, "feed_title");
    if (feedTitle.isEmpty())
        feedTitle = text(a, "feed_url");
    return {
        {"id", integer(a, "id")},
        {"feed_url", text(a, "feed_url")},
        {"feed_title", feedTitle},
        {"title", text(a, "title")},
        {"url", text(a, "url")},
        {"author", text(a, "author")},
        {"summary", text(a, "summary")},
        // Sanitised on the way out, whichever source it came from.
        {"content", html::sanitizeFragment(content)},
        {"published", util::isoTime(text(a, "published"))},
        {"is_read", integer(a, "is_read") != 0},
    };
}

QJsonObject feedJson(const Row &s) {
    QString title = text(s, "title");
    if (title.isEmpty())
        title = text(s, "feed_url");
    return {
        {"feed_url", text(s, "feed_url")},
        {"title", title},
        {"category", text(s, "category")},
        {"unread", integer(s, "unread")},
        {"favicon_url", text(s, "favicon_url")},
        {"site_url", text(s, "site_url")},
        {"error", text(s, "last_error")},
    };
}

// --- the services: refresh and sessions ------------------------------------------

struct Refreshed {
    QString url;
    int added = 0;
    QString error;
};

// Fetch several feeds concurrently and store what came back. A failure is
// recorded on the feed rather than returned as an error of the request: one
// unreachable feed should not stop a refresh of the others.
QList<Refreshed> refreshMany(Store &store, QStringList urls) {
    if (urls.size() > MAX_FEEDS_PER_REQUEST)
        urls = urls.mid(0, MAX_FEEDS_PER_REQUEST);
    QList<Refreshed> out;
    if (urls.isEmpty())
        return out;
    QList<feeds::Request> reqs;
    for (const QString &u : urls) {
        const auto [etag, lastModified] = store.validators(u);
        reqs.append({u, etag, lastModified});
    }
    const QList<feeds::Result> results = feeds::fetchAll(reqs);
    for (qsizetype i = 0; i < urls.size(); ++i) {
        const QString &url = urls[i];
        const feeds::Result &r = results[i];
        Refreshed done{url, 0, {}};
        if (!r.ok) {
            logf(QStringLiteral("feed %1 failed: %2").arg(url, r.error));
            store.markFetchError(url, r.error);
            done.error = r.error;
        } else if (r.notModified) {
            store.markFetched(url, r.etag, r.lastModified);
        } else {
            const int before = store.countArticles(url);
            store.upsertArticles(url, r.feed);
            store.upsertFeed(url, r.feed.title, r.feed.siteUrl, r.feed.description, r.feed.kind,
                             r.feed.faviconUrl);
            store.markFetched(url, r.etag, r.lastModified);
            done.added = qMax(store.countArticles(url) - before, 0);
        }
        out.append(done);
    }
    return out;
}

Refreshed refreshFeed(Store &store, const QString &url) {
    return refreshMany(store, {url}).value(0);
}

// The cron run: refresh whatever is due, oldest first.
void scheduled(Store &store, int olderThanMinutes = 30) {
    store.purgeExpired(http::unixTime());
    refreshMany(store, store.feedsToFetch(olderThanMinutes, MAX_FEEDS_PER_REQUEST));
}

// --- static files ------------------------------------------------------------------

Response staticFile(const QString &urlPath) {
    const QString root = QDir::cleanPath(qEnvironmentVariable("PULSEBOARD_STATIC", QStringLiteral("/dist")));
    QString rel = urlPath;
    while (rel.startsWith(u'/'))
        rel.remove(0, 1);
    if (rel.isEmpty())
        rel = QStringLiteral("index.html");
    const QString target = QDir::cleanPath(root + u'/' + rel);
    QFile f(target);
    if (!target.startsWith(root + u'/') || !QFileInfo(target).isFile() || !f.open(QIODevice::ReadOnly))
        return fail(404, QStringLiteral("not found"));
    Response r;
    r.body = f.readAll();
    static const QHash<QString, QByteArray> types = {
        {"html", "text/html; charset=utf-8"}, {"js", "text/javascript; charset=utf-8"},
        {"mjs", "text/javascript; charset=utf-8"}, {"css", "text/css; charset=utf-8"},
        {"wasm", "application/wasm"}, {"json", "application/json"}, {"png", "image/png"},
        {"svg", "image/svg+xml"}, {"ico", "image/x-icon"}, {"webp", "image/webp"},
        {"woff2", "font/woff2"}, {"ttf", "font/ttf"}, {"txt", "text/plain; charset=utf-8"},
        {"gz", "application/gzip"}, {"webmanifest", "application/manifest+json"}};
    const QString suffix = QFileInfo(target).suffix().toLower();
    r.headers.set("content-type", types.value(suffix, "application/octet-stream"));
    if (suffix == u"html" || suffix == u"js" || suffix == u"wasm")
        r.headers.set("cache-control", "no-cache");
    return r;
}

// --- the routes ----------------------------------------------------------------------

Params paramsOf(const Request &req);

struct Ctx {
    explicit Ctx(const Request &r) : req(r), p(paramsOf(r)) {}
    Ctx(const Ctx &) = delete;
    const Request &req;
    Params p;
    Db db;
    Store store{db};
    QString path;  // decoded
    QString user;  // set once signed in
};

constexpr const char *NOT_SIGNED_IN = "AT Protocol authentication required";

bool signedIn(Ctx &c) {
    const QString token = cookie(c.req, COOKIE);
    if (token.isEmpty())
        return false;
    c.user = c.store.sessionUser(token, http::unixTime(), SESSION_IDLE_LIMIT, SESSION_RENEW_EVERY);
    return !c.user.isEmpty();
}

Response notSignedIn(const Ctx &c) {
    if (c.path == u"/" || c.path == u"/index.html")
        return redirect(QStringLiteral("/auth/login"), 307);
    return fail(401, QString::fromLatin1(NOT_SIGNED_IN));
}

Response authorize(Ctx &c) {
    const QString identity = c.p.get("identity").trimmed();
    if (identity.isEmpty() || identity.startsWith(u"did:"))
        return htmlPage(pages::loginPage(identity, QStringLiteral("Enter a handle, like you.bsky.social.")), 400);
    const oauth::Outcome o = oauth::authorize(c.store, origin(c.req), identity);
    if (o.ok)
        return redirect(o.value);
    logf(QStringLiteral("auth/authorize failed for %1: %2").arg(identity, o.error));
    if (o.userError)
        return htmlPage(pages::loginPage(identity, o.error), 400);
    return htmlPage(pages::loginPage(identity, QStringLiteral(
                                                   "Couldn't start sign-in for that handle. Check it and try again.")),
                    502);
}

Response callback(Ctx &c) {
    const oauth::Outcome o = oauth::callback(c.store, origin(c.req), c.p.items);
    if (!o.ok) {
        logf(QStringLiteral("auth/callback failed: %1").arg(o.error));
        if (o.userError)
            return htmlPage(pages::retryPage(), 401);
        return htmlPage(pages::loginPage({}, QStringLiteral("Sign-in failed. Please try again.")), 401);
    }
    const QString token = util::token(32);
    c.store.createSession(token, o.value, http::unixTime() + SESSION_IDLE_LIMIT);
    return redirect(QStringLiteral("/"), 303, sessionCookie(token, SESSION_COOKIE_MAX_AGE));
}

Response logout(Ctx &c) {
    const QString token = cookie(c.req, COOKIE);
    if (!token.isEmpty())
        c.store.deleteSession(token);
    return redirect(QStringLiteral("/auth/login"), 303, sessionCookie({}, 0));
}

Response listFeeds(Ctx &c) {
    QJsonArray out;
    for (const Row &s : c.store.listSubscriptions(c.user))
        out.append(feedJson(s));
    return json(out);
}

Response subscribe(Ctx &c) {
    const QString url = c.p.get("url").trimmed();
    if (url.isEmpty())
        return fail(400, QStringLiteral("url required"));
    if (!util::isHttpUrl(url))
        return fail(400, QStringLiteral("url must be http(s)"));
    // Subscribe first so a feed that fails to fetch is still listed, with its
    // error visible, rather than vanishing.
    c.store.upsertFeed(url);
    c.store.subscribe(c.user, url, {}, c.p.get("category"));
    const Refreshed r = refreshFeed(c.store, url);
    if (!r.error.isEmpty())
        return json(QJsonObject{{"feed_url", url}, {"added", 0}, {"error", r.error}});
    return json(QJsonObject{{"feed_url", url}, {"added", r.added}});
}

// url names the subscription; new_url, title and category replace its fields
// (new_url defaults to url, so a rename leaves it).
Response editFeed(Ctx &c) {
    const QString url = c.p.get("url").trimmed();
    if (url.isEmpty() || !c.store.getSubscription(c.user, url))
        return fail(404, QStringLiteral("no such subscription"));
    QString newUrl = c.p.get("new_url").trimmed();
    if (newUrl.isEmpty())
        newUrl = url;
    if (!util::isHttpUrl(newUrl))
        return fail(400, QStringLiteral("url must be http(s)"));
    if (newUrl != url && c.store.getSubscription(c.user, newUrl))
        return fail(409, QStringLiteral("already subscribed to that URL"));
    if (newUrl != url)
        c.store.upsertFeed(newUrl);
    c.store.updateSubscription(c.user, url, newUrl, c.p.get("title").trimmed(), c.p.get("category").trimmed());
    if (newUrl == url)
        return json(QJsonObject{{"feed_url", url}, {"added", 0}});
    // The edit is saved either way; a fetch failure is reported alongside
    // rather than as "error", which the client takes to mean nothing changed.
    const Refreshed r = refreshFeed(c.store, newUrl);
    if (!r.error.isEmpty())
        return json(QJsonObject{{"feed_url", newUrl}, {"added", 0}, {"fetch_error", r.error}});
    return json(QJsonObject{{"feed_url", newUrl}, {"added", r.added}});
}

Response unsubscribe(Ctx &c) {
    if (c.p.get("url").isEmpty())
        return fail(400, QStringLiteral("url required"));
    c.store.unsubscribe(c.user, c.p.get("url"));
    return json(QJsonObject{{"ok", true}});
}

Response exportOpml(Ctx &c) {
    QList<opml::Feed> list;
    for (const Row &s : c.store.listSubscriptions(c.user, 5000))
        list.append({text(s, "feed_url"), text(s, "title"), text(s, "site_url"), {}, text(s, "category")});
    Response r;
    r.headers.set("content-type", "application/xml; charset=utf-8");
    r.headers.set("content-disposition", "attachment; filename=pulseboard-subscriptions.opml");
    r.body = opml::render(list).toUtf8();
    return r;
}

Response importOpml(Ctx &c) {
    const QString source = c.p.get("opml");
    if (source.isEmpty())
        return fail(400, QStringLiteral("OPML required"));
    if (source.size() > MAX_OPML)
        return fail(413, QStringLiteral("OPML is too large"));
    QList<opml::Feed> imported;
    QString err;
    if (!opml::parse(source, &imported, &err))
        return fail(400, QStringLiteral("invalid OPML: ") + err);
    int added = 0;
    QJsonArray errors;
    QStringList urls;
    for (const opml::Feed &f : imported) {
        if (!util::isHttpUrl(f.url)) {
            errors.append(QJsonObject{{"feed_url", f.url}, {"error", "not an http(s) URL"}});
            continue;
        }
        c.store.upsertFeed(f.url, f.title, f.siteUrl, f.description);
        if (c.store.subscribe(c.user, f.url, f.title, f.category))
            added++;
        urls.append(f.url);
    }
    // Past the per-request cap, the next refresh or cron run fetches them.
    for (const Refreshed &r : refreshMany(c.store, urls))
        if (!r.error.isEmpty())
            errors.append(QJsonObject{{"feed_url", r.url}, {"error", r.error}});
    return json(QJsonObject{{"imported", imported.size()}, {"added", added}, {"errors", errors}});
}

Response listArticles(Ctx &c) {
    const int limit = int(qBound(qint64(1), c.p.getInt("limit", 50), qint64(500)));
    const QString q = c.p.get("q");
    Rows rows;
    if (!q.isEmpty()) {
        rows = c.store.searchArticles(c.user, q, limit);
    } else {
        const QString status = c.p.get("status");
        rows = c.store.listArticles(c.user, (status == u"all" || status == u"read") ? status : QStringLiteral("unread"),
                                    c.p.get("feed"), limit);
    }
    QJsonArray out;
    for (const Row &a : rows)
        out.append(articleJson(a));
    return json(out);
}

Response getArticle(Ctx &c, const QString &idText) {
    bool ok = false;
    const qint64 id = idText.toLongLong(&ok);
    const auto a = ok ? c.store.getArticle(c.user, id) : std::nullopt;
    if (!a)
        return fail(404, QStringLiteral("no such article"));
    return json(articleJson(*a));
}

Response unread(Ctx &c) {
    return json(QJsonObject{{"count", c.store.unreadCount(c.user)}});
}

Response markRead(Ctx &c) {
    const qint64 id = c.p.getInt("id", 0);
    if (!id)
        return fail(400, QStringLiteral("id required"));
    c.store.setRead(c.user, id, c.p.get("undo") != u"1");
    return json(QJsonObject{{"id", id}});
}

Response markAllRead(Ctx &c) {
    c.store.markAllRead(c.user, c.p.get("feed"));
    return json(QJsonObject{{"unread", c.store.unreadCount(c.user)}});
}

Response refresh(Ctx &c) {
    const int minutes = c.p.get("force") == u"1" ? -1 : FRESH_MINUTES;
    int added = 0;
    QJsonArray errors;
    for (const Refreshed &r : refreshMany(c.store, c.store.staleSubscriptions(c.user, minutes))) {
        added += r.added;
        if (!r.error.isEmpty())
            errors.append(QJsonObject{{"feed_url", r.url}, {"error", r.error}});
    }
    return json(QJsonObject{{"added", added}, {"errors", errors}});
}

Response fetchContent(Ctx &c) {
    const qint64 id = c.p.getInt("id", 0);
    const auto a = c.store.getArticle(c.user, id);
    const QString url = a ? text(*a, "url") : QString();
    if (url.isEmpty())
        return fail(404, QStringLiteral("no such article"));
    if (!util::isHttpUrl(url))
        return fail(400, QStringLiteral("article has no http(s) URL"));
    http::Outgoing req;
    req.url = url;
    req.headers.set("user-agent", feeds::USER_AGENT);
    const http::Response res = http::fetch(req);
    if (!res.error.isEmpty())
        return fail(502, QStringLiteral("fetching %1: %2").arg(url, res.error));
    if (res.status != 200)
        return fail(502, QStringLiteral("HTTP %1").arg(res.status));
    QString err;
    const QString content = html::extractArticle(QString::fromUtf8(res.body), &err);
    if (!err.isEmpty())
        return fail(502, err);
    c.store.updateFullContent(id, content);
    return json(QJsonObject{{"id", id}, {"content", content}});
}

// Work for the machine's own refresh loop (see server/fly/entrypoint.sh),
// behind a secret it makes up at boot.
Response internal(Ctx &c, const QString &what) {
    const QByteArray secret = qgetenv("CRON_SECRET");
    if (secret.isEmpty() || c.req.headers.get("x-pulseboard-cron") != secret)
        return fail(404, QStringLiteral("not found"));
    if (what == u"migrate") {
        const QStringList applied = c.db.migrate();
        return json(QJsonObject{{"applied", QJsonArray::fromStringList(applied)}});
    }
    if (what == u"cron") {
        scheduled(c.store, int(c.p.getInt("older_than", 30)));
        return json(QJsonObject{{"ok", true}});
    }
    // The pure parts, for server/tests (only with PULSEBOARD_TEST_HOOKS set).
    if (qEnvironmentVariableIsSet("PULSEBOARD_TEST_HOOKS")) {
        const QString in = QString::fromUtf8(c.req.body);
        if (what == u"test/sanitize")
            return json(QJsonObject{{"out", html::sanitizeFragment(in)}});
        if (what == u"test/extract") {
            QString err;
            const QString out = html::extractArticle(in, &err);
            return json(QJsonObject{{"out", out}, {"error", err}});
        }
        if (what == u"test/parse-feed") {
            feeds::Feed f;
            QString err;
            if (!feeds::parse(c.req.body, QStringLiteral("u"), &f, &err))
                return json(QJsonObject{{"error", err}});
            QJsonArray arts;
            for (const feeds::Article &a : f.articles)
                arts.append(QJsonObject{{"guid", a.guid}, {"title", a.title}, {"url", a.url},
                                        {"author", a.author}, {"content", a.content}, {"summary", a.summary},
                                        {"published", util::dbTime(a.published)},
                                        {"updated", util::dbTime(a.updated)}});
            return json(QJsonObject{{"title", f.title}, {"site_url", f.siteUrl}, {"kind", f.kind},
                                    {"favicon_url", f.faviconUrl}, {"description", f.description},
                                    {"articles", arts}});
        }
        if (what == u"test/opml") {
            QList<opml::Feed> list;
            QString err;
            if (!opml::parse(in, &list, &err))
                return json(QJsonObject{{"error", err}});
            QJsonArray out;
            for (const opml::Feed &f : list)
                out.append(QJsonObject{{"url", f.url}, {"title", f.title}, {"category", f.category}});
            return json(QJsonObject{{"feeds", out}, {"rendered", opml::render(list)}});
        }
    }
    return fail(404, QStringLiteral("not found"));
}

Response route(Ctx &c) {
    const QByteArray &m = c.req.method;
    const QString &path = c.path;
    const bool get = m == "GET" || m == "HEAD";
    const bool post = m == "POST";

    if (path == u"/health" && get)
        return json(QJsonObject{{"ok", true}});
    if (path == u"/oauth-client-metadata.json" && get)
        return json(oauth::clientMetadata(origin(c.req)));
    if (path == u"/auth/login" && get)
        return htmlPage(pages::loginPage());
    if (path == u"/auth/authorize" && get)
        return authorize(c);
    if (path == u"/auth/callback" && get)
        return callback(c);
    if (path == u"/auth/logout" && get)
        return logout(c);
    if (path.startsWith(u"/internal/") && post)
        return internal(c, path.mid(10));

    // Everything below is the signed-in reader's.
    const QString root = path.mid(1).section(u'/', 0, 0);
    const bool isApi = API_ROOTS.contains(root) || path == u"/" || path == u"/index.html";
    if (!isApi) {
        // The client's files (wasm, js, css, icons) are public: they are
        // code, not data, and the browser must load them to show the sign-in
        // redirect at all.
        if (get)
            return staticFile(path);
        return fail(405, QStringLiteral("method not allowed"));
    }
    if (!signedIn(c))
        return notSignedIn(c);

    if (path == u"/" || path == u"/index.html")
        return get ? staticFile(QStringLiteral("/")) : fail(405, QStringLiteral("method not allowed"));
    if (path == u"/feeds") {
        if (get) return listFeeds(c);
        if (post) return subscribe(c);
        if (m == "PUT") return editFeed(c);
        if (m == "DELETE") return unsubscribe(c);
    } else if (path == u"/opml") {
        if (get) return exportOpml(c);
        if (post) return importOpml(c);
    } else if (path == u"/articles") {
        if (get) return listArticles(c);
    } else if (path.startsWith(u"/articles/") && path.count(u'/') == 2) {
        if (get) return getArticle(c, path.mid(10));
    } else if (path == u"/unread") {
        if (get) return unread(c);
    } else if (path == u"/read") {
        if (post) return markRead(c);
    } else if (path == u"/read-all") {
        if (post) return markAllRead(c);
    } else if (path == u"/refresh") {
        if (post) return refresh(c);
    } else if (path == u"/fetch-content") {
        if (post) return fetchContent(c);
    } else {
        // Unknown paths under an API root stay JSON 404s, never static files.
        return fail(get ? 404 : 405, get ? QStringLiteral("not found") : QStringLiteral("method not allowed"));
    }
    return fail(get ? 404 : 405, get ? QStringLiteral("not found") : QStringLiteral("method not allowed"));
}

}  // namespace

http::Response handleRequest(const http::Request &req) {
    Ctx c(req);
    c.path = QString::fromUtf8(QByteArray::fromPercentEncoding(req.path));
    Response r = route(c);
    if (c.db.failed()) {
        logf(QStringLiteral("%1 %2 failed: %3").arg(QString::fromUtf8(req.method), c.path, c.db.error()));
        r = fail(500, QStringLiteral("internal error"));
    }
    return r;
}
