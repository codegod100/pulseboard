#include "store.h"

#include "util.h"

namespace {

const QString ARTICLE_COLUMNS = QStringLiteral(R"(
  a.id, a.feed_url, COALESCE(f.title, a.feed_url) AS feed_title,
  f.favicon_url AS feed_favicon_url, a.guid, a.title, a.url, a.author,
  a.summary, a.content, a.full_content, a.published, a.updated,
  COALESCE(r.is_read, 0) AS is_read)");

const QString ARTICLE_FROM = QStringLiteral(R"(
  FROM articles a
  LEFT JOIN feeds f ON f.feed_url = a.feed_url
  LEFT JOIN read_state r ON r.article_id = a.id AND r.user_did = ?)");

// Times are UTC in `timestamp` columns, as SQLite kept them.
const QString NOW = QStringLiteral("(now() AT TIME ZONE 'utc')");
// "now minus ? minutes"; the parameter is e.g. "30 minutes".
const QString AGO = QStringLiteral("((now() AT TIME ZONE 'utc') - CAST(? AS interval))");

Param orNull(const QString &s) {
    return s.isEmpty() ? null() : Param(s);
}

Param timeOrNull(const QDateTime &t) {
    return t.isValid() ? Param(util::dbTime(t)) : null();
}

QString minutes(int m) {
    return QStringLiteral("%1 minutes").arg(m);
}

QStringList column(const Rows &rows, const char *key) {
    QStringList out;
    for (const Row &r : rows)
        out.append(text(r, key));
    return out;
}

}  // namespace

// --- articles ----------------------------------------------------------------

std::optional<Row> Store::getArticle(const QString &user, qint64 id) {
    return db.first(QStringLiteral("SELECT %1 %2 WHERE a.id = ?").arg(ARTICLE_COLUMNS, ARTICLE_FROM),
                    {user, id});
}

Rows Store::listArticles(const QString &user, const QString &status, const QString &feedUrl, int limit) {
    QString sql = QStringLiteral("SELECT %1 %2 JOIN subscriptions s ON s.feed_url = a.feed_url AND s.user_did = ? WHERE 1=1")
                      .arg(ARTICLE_COLUMNS, ARTICLE_FROM);
    Params params{user, user};
    if (status == u"unread")
        sql += QStringLiteral(" AND COALESCE(r.is_read, 0) = 0");
    else if (status == u"read")
        sql += QStringLiteral(" AND COALESCE(r.is_read, 0) = 1");
    if (!feedUrl.isEmpty()) {
        sql += QStringLiteral(" AND a.feed_url = ?");
        params.append(feedUrl);
    }
    // NULL published sorts last: an undated article is almost always a
    // parse failure, and burying it beats putting it at the top.
    sql += QStringLiteral(" ORDER BY a.published IS NULL, a.published DESC, a.id DESC LIMIT ?");
    params.append(limit);
    return db.all(sql, params);
}

Rows Store::searchArticles(const QString &user, const QString &query, int limit) {
    if (query.trimmed().isEmpty())
        return {};
    // websearch_to_tsquery takes what people type ("quoted phrases", -not,
    // or) and never raises on it.
    return db.all(QStringLiteral(R"(SELECT %1 %2
        JOIN subscriptions s ON s.feed_url = a.feed_url AND s.user_did = ?
        JOIN (SELECT id, ts_rank(search, q) AS rank
              FROM articles, websearch_to_tsquery('english', ?) q
              WHERE search @@ q) m ON m.id = a.id
        ORDER BY m.rank DESC, a.id DESC LIMIT ?)").arg(ARTICLE_COLUMNS, ARTICLE_FROM),
                  {user, user, query, limit});
}

void Store::upsertArticles(const QString &feedUrl, const feeds::Feed &parsed) {
    QList<Statement> stmts;
    for (const feeds::Article &a : parsed.articles) {
        if (a.guid.isEmpty())
            continue;
        stmts.append({QStringLiteral(R"(INSERT INTO articles
               (feed_url, guid, title, url, author, summary, content, published, updated)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(feed_url, guid) DO NOTHING)"),
                      {feedUrl, a.guid, a.title, orNull(a.url), orNull(a.author), orNull(a.summary),
                       orNull(a.content), timeOrNull(a.published), timeOrNull(a.updated)}});
    }
    // Read state carried over from elsewhere (an import, a moved
    // subscription) is keyed on (feed_url, guid); attach it to whatever ids
    // the articles got.
    stmts.append({QStringLiteral(R"(INSERT INTO read_state (user_did, article_id, is_read, read_at)
           SELECT h.user_did, a.id, h.is_read, h.read_at
           FROM read_state_history h
           JOIN articles a ON a.feed_url = h.feed_url AND a.guid = h.guid
           WHERE h.feed_url = ?
           ON CONFLICT(user_did, article_id) DO NOTHING)"),
                  {feedUrl}});
    for (qsizetype i = 0; i < stmts.size(); i += 50)
        db.batch(stmts.mid(i, 50));
}

void Store::updateFullContent(qint64 id, const QString &content) {
    db.run(QStringLiteral("UPDATE articles SET full_content = ? WHERE id = ?"), {orNull(content), id});
}

// --- read state -----------------------------------------------------------------

void Store::setRead(const QString &user, qint64 id, bool read) {
    db.run(QStringLiteral(R"(INSERT INTO read_state (user_did, article_id, is_read, read_at)
           VALUES (?, ?, ?, %1)
           ON CONFLICT(user_did, article_id) DO UPDATE SET
             is_read = excluded.is_read, read_at = excluded.read_at)").arg(NOW),
           {user, id, read ? 1 : 0});
}

void Store::markAllRead(const QString &user, const QString &feedUrl) {
    // Two statements, not one with an optional predicate: getting this scope
    // wrong clears the whole account instead of one feed.
    if (!feedUrl.isEmpty()) {
        db.run(QStringLiteral(R"(INSERT INTO read_state (user_did, article_id, is_read, read_at)
               SELECT ?, a.id, 1, %1 FROM articles a
               WHERE a.feed_url = ?
               ON CONFLICT(user_did, article_id) DO UPDATE SET
                 is_read = 1, read_at = %1)").arg(NOW),
               {user, feedUrl});
    } else {
        db.run(QStringLiteral(R"(INSERT INTO read_state (user_did, article_id, is_read, read_at)
               SELECT ?, a.id, 1, %1 FROM articles a
               JOIN subscriptions s ON s.feed_url = a.feed_url AND s.user_did = ?
               ON CONFLICT(user_did, article_id) DO UPDATE SET
                 is_read = 1, read_at = %1)").arg(NOW),
               {user, user});
    }
}

int Store::unreadCount(const QString &user, const QString &feedUrl) {
    QString sql = QStringLiteral(R"(SELECT count(*) AS n FROM articles a
      JOIN subscriptions s ON s.feed_url = a.feed_url AND s.user_did = ?
      LEFT JOIN read_state r ON r.article_id = a.id AND r.user_did = ?
      WHERE COALESCE(r.is_read, 0) = 0)");
    Params params{user, user};
    if (!feedUrl.isEmpty()) {
        sql += QStringLiteral(" AND a.feed_url = ?");
        params.append(feedUrl);
    }
    const auto row = db.first(sql, params);
    return row ? int(integer(*row, "n")) : 0;
}

// --- feeds ---------------------------------------------------------------------

void Store::upsertFeed(const QString &url, const QString &title, const QString &siteUrl,
                       const QString &description, const QString &kind, const QString &faviconUrl) {
    // subscriber_count and the error columns are owned by subscribe and by
    // the fetcher; a metadata refresh that reset them would revive dead feeds.
    db.run(QStringLiteral(R"(INSERT INTO feeds (feed_url, title, site_url, description, feed_type, favicon_url)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(feed_url) DO UPDATE SET
             title = COALESCE(excluded.title, feeds.title),
             site_url = COALESCE(excluded.site_url, feeds.site_url),
             description = COALESCE(excluded.description, feeds.description),
             feed_type = COALESCE(excluded.feed_type, feeds.feed_type),
             favicon_url = COALESCE(excluded.favicon_url, feeds.favicon_url))"),
           {url, orNull(title), orNull(siteUrl), orNull(description), orNull(kind), orNull(faviconUrl)});
}

void Store::markFetched(const QString &url, const QString &etag, const QString &lastModified) {
    db.run(QStringLiteral(R"(UPDATE feeds SET last_fetched_at = %1,
             last_error = NULL, error_count = 0,
             etag = ?, last_modified = ? WHERE feed_url = ?)").arg(NOW),
           {orNull(etag), orNull(lastModified), url});
}

QPair<QString, QString> Store::validators(const QString &url) {
    const auto row = db.first(QStringLiteral("SELECT etag, last_modified FROM feeds WHERE feed_url = ?"), {url});
    if (!row)
        return {};
    return {text(*row, "etag"), text(*row, "last_modified")};
}

int Store::countArticles(const QString &url) {
    const auto row = db.first(QStringLiteral("SELECT count(*) AS n FROM articles WHERE feed_url = ?"), {url});
    return row ? int(integer(*row, "n")) : 0;
}

QStringList Store::staleSubscriptions(const QString &user, int mins) {
    QString sql = QStringLiteral(R"(SELECT s.feed_url FROM subscriptions s
           LEFT JOIN feeds f ON f.feed_url = s.feed_url
           WHERE s.user_did = ?)");
    Params params{user};
    if (mins >= 0) {
        sql += QStringLiteral(" AND (f.last_fetched_at IS NULL OR f.last_fetched_at < %1)").arg(AGO);
        params.append(minutes(mins));
    }
    sql += QStringLiteral(" ORDER BY f.last_fetched_at IS NOT NULL, f.last_fetched_at");
    return column(db.all(sql, params), "feed_url");
}

void Store::markFetchError(const QString &url, const QString &error) {
    db.run(QStringLiteral(R"(UPDATE feeds SET last_fetched_at = %1,
             last_error = ?, error_count = error_count + 1 WHERE feed_url = ?)").arg(NOW),
           {error, url});
}

QStringList Store::feedsToFetch(int olderThanMinutes, int limit) {
    // Feeds that keep failing drop out so a dead URL does not take a slot
    // every cycle.
    return column(db.all(QStringLiteral(R"(SELECT feed_url FROM feeds
           WHERE subscriber_count > 0 AND error_count < 10
             AND (last_fetched_at IS NULL OR last_fetched_at < %1)
           ORDER BY last_fetched_at IS NOT NULL, last_fetched_at
           LIMIT ?)").arg(AGO),
                         {minutes(olderThanMinutes), limit}),
                  "feed_url");
}

// --- subscriptions ------------------------------------------------------------------

namespace {
const QString RECOUNT = QStringLiteral(R"(UPDATE feeds SET subscriber_count = (
      SELECT count(*) FROM subscriptions WHERE feed_url = ?)
    WHERE feed_url = ?)");
}

bool Store::subscribe(const QString &user, const QString &url, const QString &title, const QString &category) {
    const auto existing = getSubscription(user, url);
    db.run(QStringLiteral(R"(INSERT INTO subscriptions (user_did, feed_url, title, category)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(user_did, feed_url) DO UPDATE SET
             title = COALESCE(excluded.title, subscriptions.title),
             category = COALESCE(excluded.category, subscriptions.category))"),
           {user, url, orNull(title), orNull(category)});
    db.run(RECOUNT, {url, url});
    return !existing.has_value();
}

void Store::unsubscribe(const QString &user, const QString &url) {
    db.batch({{QStringLiteral("DELETE FROM subscriptions WHERE user_did = ? AND feed_url = ?"), {user, url}},
              {RECOUNT, {url, url}}});
}

void Store::updateSubscription(const QString &user, const QString &url, const QString &newUrl,
                               const QString &title, const QString &category) {
    // On a move, the user's read state goes into read_state_history under
    // the new URL, so articles the new feed shares with the old one (same
    // guid) arrive already read.
    QList<Statement> stmts;
    if (newUrl != url)
        stmts.append({QStringLiteral(R"(INSERT INTO read_state_history (user_did, feed_url, guid, is_read, read_at)
               SELECT r.user_did, ?, a.guid, r.is_read, r.read_at
               FROM read_state r JOIN articles a ON a.id = r.article_id
               WHERE r.user_did = ? AND a.feed_url = ?
               ON CONFLICT(user_did, feed_url, guid) DO NOTHING)"),
                      {newUrl, user, url}});
    stmts.append({QStringLiteral(R"(UPDATE subscriptions SET feed_url = ?, title = ?, category = ?
           WHERE user_did = ? AND feed_url = ?)"),
                  {newUrl, orNull(title), orNull(category), user, url}});
    if (newUrl != url)
        for (const QString &u : {url, newUrl})
            stmts.append({RECOUNT, {u, u}});
    db.batch(stmts);
}

std::optional<Row> Store::getSubscription(const QString &user, const QString &url) {
    return db.first(QStringLiteral("SELECT id FROM subscriptions WHERE user_did = ? AND feed_url = ?"), {user, url});
}

Rows Store::listSubscriptions(const QString &user, int limit) {
    // The unread count is computed per row rather than stored: it is
    // per-user and changes constantly.
    return db.all(QStringLiteral(R"(SELECT s.feed_url,
             COALESCE(s.title, f.title, s.feed_url) AS title,
             COALESCE(s.category, '') AS category,
             f.site_url, f.description, f.favicon_url, f.last_error,
             (SELECT count(*) FROM articles a
              LEFT JOIN read_state r
                ON r.article_id = a.id AND r.user_did = s.user_did
              WHERE a.feed_url = s.feed_url AND COALESCE(r.is_read, 0) = 0) AS unread
           FROM subscriptions s
           LEFT JOIN feeds f ON f.feed_url = s.feed_url
           WHERE s.user_did = ?
           ORDER BY lower(COALESCE(s.title, f.title, s.feed_url))
           LIMIT ?)"),
                  {user, limit});
}

// --- users and sessions ----------------------------------------------------------------

void Store::createSession(const QString &token, const QString &did, qint64 expiresAt) {
    db.batch({{QStringLiteral("INSERT INTO users (did) VALUES (?) ON CONFLICT DO NOTHING"), {did}},
              {QStringLiteral("INSERT INTO web_sessions (token, user_did, expires_at) VALUES (?, ?, ?)"),
               {token, did, expiresAt}}});
}

QString Store::sessionUser(const QString &token, qint64 now, qint64 idleLimit, qint64 renewEvery) {
    // Pushes the expiry forward at most once per `renewEvery` seconds so a
    // regular reader is never sent to sign in.
    const auto row = db.first(
        QStringLiteral("SELECT user_did, expires_at FROM web_sessions WHERE token = ? AND expires_at > ?"),
        {token, now});
    if (!row)
        return {};
    if (integer(*row, "expires_at") < now + idleLimit - renewEvery)
        db.run(QStringLiteral("UPDATE web_sessions SET expires_at = ? WHERE token = ?"), {now + idleLimit, token});
    return text(*row, "user_did");
}

void Store::deleteSession(const QString &token) {
    db.run(QStringLiteral("DELETE FROM web_sessions WHERE token = ?"), {token});
}

void Store::putOAuthState(const QString &state, const QString &data, qint64 expiresAt) {
    db.run(QStringLiteral("INSERT INTO oauth_states (state, data, expires_at) VALUES (?, ?, ?)"),
           {state, data, expiresAt});
}

std::optional<QString> Store::takeOAuthState(const QString &state, qint64 now) {
    // Single use: the row is deleted whether or not it was still valid.
    const auto row = db.first(QStringLiteral("SELECT data, expires_at FROM oauth_states WHERE state = ?"), {state});
    if (!row)
        return std::nullopt;
    db.run(QStringLiteral("DELETE FROM oauth_states WHERE state = ?"), {state});
    if (integer(*row, "expires_at") > now)
        return text(*row, "data");
    return std::nullopt;
}

void Store::purgeExpired(qint64 now) {
    db.batch({{QStringLiteral("DELETE FROM web_sessions WHERE expires_at <= ?"), {now}},
              {QStringLiteral("DELETE FROM oauth_states WHERE expires_at <= ?"), {now}}});
}
