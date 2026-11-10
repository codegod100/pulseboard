// Feeds, subscriptions, articles and read state in Postgres (Neon).
//
// Ported from the Python server's store.py (Postgres dialect). Read state is
// per-user and lives in its own table, so "the article list" is always a LEFT
// JOIN: an article with no read_state row is unread. Times are UTC in
// `timestamp` columns.
#pragma once

#include "db.h"
#include "feeds.h"

#include <QStringList>
#include <optional>

class Store {
public:
    explicit Store(Db &db) : db(db) {}

    // --- articles
    std::optional<Row> getArticle(const QString &user, qint64 id);
    Rows listArticles(const QString &user, const QString &status, const QString &feedUrl, int limit);
    Rows searchArticles(const QString &user, const QString &query, int limit);
    void upsertArticles(const QString &feedUrl, const feeds::Feed &parsed);
    void updateFullContent(qint64 id, const QString &content);

    // --- read state
    void setRead(const QString &user, qint64 id, bool read);
    void markAllRead(const QString &user, const QString &feedUrl);
    int unreadCount(const QString &user, const QString &feedUrl = {});

    // --- feeds
    void upsertFeed(const QString &url, const QString &title = {}, const QString &siteUrl = {},
                    const QString &description = {}, const QString &kind = {},
                    const QString &faviconUrl = {});
    void markFetched(const QString &url, const QString &etag, const QString &lastModified);
    QPair<QString, QString> validators(const QString &url);
    int countArticles(const QString &url);
    // The user's feeds not fetched in the last `minutes` (all of them when
    // negative), least recently fetched first.
    QStringList staleSubscriptions(const QString &user, int minutes);
    void markFetchError(const QString &url, const QString &error);
    QStringList feedsToFetch(int olderThanMinutes, int limit);

    // --- subscriptions
    bool subscribe(const QString &user, const QString &url, const QString &title, const QString &category);
    void unsubscribe(const QString &user, const QString &url);
    void updateSubscription(const QString &user, const QString &url, const QString &newUrl,
                            const QString &title, const QString &category);
    std::optional<Row> getSubscription(const QString &user, const QString &url);
    Rows listSubscriptions(const QString &user, int limit = 500);

    // --- users and sessions
    void createSession(const QString &token, const QString &did, qint64 expiresAt);
    QString sessionUser(const QString &token, qint64 now, qint64 idleLimit, qint64 renewEvery);
    void deleteSession(const QString &token);
    void putOAuthState(const QString &state, const QString &data, qint64 expiresAt);
    std::optional<QString> takeOAuthState(const QString &state, qint64 now);
    void purgeExpired(qint64 now);

    Db &db;
};
