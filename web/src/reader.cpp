#include "reader.h"
#include "platform.h"

#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QTimer>

static constexpr int kLimit = 100;

Reader::Reader(QObject *parent) : QObject(parent) {
    m_filter.setSourceModel(&m_feeds);
    connect(this, &Reader::toast, this, [this](const QString &t) { m_lastToast = t; });
    loadFeeds();
    // Show what is stored, then (once that list is in, so there is something
    // to compare against) have the reader fetch the feeds, so the app opens
    // on whatever arrived since the last visit. See gotArticles().
    loadArticles(false);
    // keep "5m" honest while the app sits open
    auto *tick = new QTimer(this);
    connect(tick, &QTimer::timeout, this, [this] { m_articles.retime(); });
    tick->start(60 * 1000);
}

QString Reader::selectedTitle() const {
    return m_sel >= 0 ? m_feeds.at(m_sel).title : QString();
}

int Reader::selectedUnread() const {
    return m_sel >= 0 ? m_feeds.at(m_sel).unread : 0;
}

// ------------------------------------------------------------------ requests

void Reader::loadFeeds() {
    m_api.get("/feeds", [this](const ApiResult &r) { gotFeeds(r); });
    m_api.get("/unread", [this](const ApiResult &r) {
        if (r.ok) {
            m_unread = r.json.toObject().value("count").toInt();
            emit changed();
        }
    });
}

void Reader::loadArticles(bool markNew) {
    QString path;
    if (!m_search.isEmpty()) {
        path = "/articles?q=" + Api::enc(m_search);
    } else {
        path = "/articles?status=";
        path += m_status == All ? "all" : m_status == Read ? "read" : "unread";
        if (m_sel >= 0)
            path += "&feed=" + Api::enc(m_selUrl);
    }
    path += "&limit=" + QString::number(kLimit);
    const int serial = ++m_serial;
    m_listState = Loading;
    emit changed();
    m_api.get(path, [this, serial, markNew](const ApiResult &r) {
        if (serial != m_serial)
            return;  // an older request, overtaken by a newer one
        if (!m_booted) {
            m_booted = true;
            startRefresh(true);
        }
        if (!r.ok) {
            m_listError = r.error;
            m_listState = Failed;
            emit changed();
            return;
        }
        m_articles.reset(r.json.toArray(), markNew);
        linkArticles();
        m_listState = Ready;
        emit changed();
    });
}

void Reader::startRefresh(bool quiet) {
    if (m_refreshing)
        return;
    m_refreshing = true;
    emit changed();
    m_api.post("/refresh", {}, [this, quiet](const ApiResult &r) {
        m_refreshing = false;
        emit changed();
        if (!r.ok) {
            emit toast(r.error);
            return;
        }
        const QJsonObject o = r.json.toObject();
        const int added = o.value("added").toInt();
        const int failed = int(o.value("errors").toArray().size());
        loadFeeds();
        loadArticles(true);
        if (quiet && failed == 0)
            return;
        QString t = QString::number(added) + " new";
        if (failed > 0)
            t += ", " + QString::number(failed) + " feed(s) failed";
        emit toast(t);
    });
}

void Reader::postRead(int row, bool read) {
    QByteArray body = "id=" + QByteArray::number(m_articles.at(row).id);
    if (!read)
        body += "&undo=1";
    m_api.post("/read", body, [this](const ApiResult &r) {
        if (!r.ok) {
            // put the counts and rows back as the server has them
            emit toast(r.error);
            loadFeeds();
            loadArticles(false);
        }
    });
}

void Reader::setRead(int row, bool read) {
    // flip one row locally, keeping the counts in step
    if (row < 0 || row >= m_articles.size() || m_articles.at(row).read == read)
        return;
    m_articles.setRead(row, read);
    const int d = read ? -1 : 1;
    m_unread = qMax(0, m_unread + d);
    if (row < m_artFeed.size())
        m_feeds.addUnread(m_artFeed[row], d);
    emit changed();
}

void Reader::linkArticles() {
    m_artFeed.resize(m_articles.size());
    for (int i = 0; i < m_articles.size(); ++i)
        m_artFeed[i] = m_feeds.find(m_articles.at(i).feedUrl);
}

void Reader::gotFeeds(const ApiResult &r) {
    if (!r.ok) {
        m_feedsError = r.error;
        emit changed();
        return;
    }
    m_feedsError.clear();
    m_feeds.reset(r.json.toArray());
    if (m_sel >= 0) {
        m_sel = m_feeds.find(m_selUrl);
        if (m_sel < 0) {
            // the feed was removed: back to everything
            m_selUrl.clear();
            loadArticles(false);
        }
    }
    linkArticles();
    emit changed();
}

// ------------------------------------------------------------------ actions

void Reader::select(int feed) {
    m_sel = feed >= 0 && feed < m_feeds.size() ? feed : -1;
    m_selUrl = m_sel >= 0 ? m_feeds.at(m_sel).url : QString();
    m_managing = false;
    m_search.clear();
    emit searchReset();
    loadArticles(false);
}

void Reader::setStatus(int status) {
    m_status = status;
    loadArticles(false);
}

void Reader::applySearch(const QString &q) {
    m_search = q.trimmed();
    loadArticles(false);
}

void Reader::toggleRead(int row) {
    if (row < 0 || row >= m_articles.size())
        return;
    const bool read = !m_articles.at(row).read;
    setRead(row, read);
    postRead(row, read);
}

void Reader::open(int row) {
    if (row < 0 || row >= m_articles.size())
        return;
    const Article &a = m_articles.at(row);
    if (!a.hasLink) {
        emit toast("This article does not have a valid link.");
        return;
    }
    platform::openUrl(a.url);
    if (!a.read) {
        setRead(row, true);
        postRead(row, true);
    }
}

void Reader::markAllRead() {
    const QByteArray body = m_sel >= 0 ? Api::form({{"feed", m_selUrl}}) : QByteArray("");
    m_api.post("/read-all", body, [this](const ApiResult &r) {
        if (!r.ok) {
            emit toast(r.error);
            return;
        }
        loadFeeds();
        loadArticles(false);
    });
}

void Reader::retry() {
    loadFeeds();
    loadArticles(false);
}

void Reader::openManage() {
    m_managing = true;
    m_changed = false;
    emit changed();
}

void Reader::closeManage() {
    m_managing = false;
    emit changed();
    if (m_changed)
        loadArticles(false);
}

void Reader::addFeed(const QString &url) {
    const QString u = url.trimmed();
    if (u.isEmpty() || m_adding)
        return;
    m_adding = true;
    emit changed();
    m_api.post("/feeds", Api::form({{"url", u}}), [this](const ApiResult &r) {
        m_adding = false;
        emit changed();
        if (!r.ok) {
            emit toast(r.error);
            return;
        }
        emit toast("Feed added");
        emit addSucceeded();
        m_changed = true;
        loadFeeds();
    });
}

void Reader::removeFeed(int feed) {
    if (feed < 0 || feed >= m_feeds.size())
        return;
    m_api.request("DELETE", "/feeds?url=" + Api::enc(m_feeds.at(feed).url), {},
                  [this](const ApiResult &r) {
        if (!r.ok) {
            emit toast(r.error);
            return;
        }
        emit toast("Feed removed");
        m_changed = true;
        loadFeeds();
    });
}

QVariantMap Reader::feed(int feed) const {
    if (feed < 0 || feed >= m_feeds.size())
        return {};
    const Feed &f = m_feeds.at(feed);
    // an untitled feed shows its URL as the title; don't freeze that in
    return {{"title", f.title == f.url ? QString() : f.title},
            {"url", f.url}, {"category", f.category}};
}

void Reader::editFeed(int feed, const QString &title, const QString &url,
                      const QString &category) {
    if (feed < 0 || feed >= m_feeds.size() || url.trimmed().isEmpty())
        return;
    const QString old = m_feeds.at(feed).url;
    const QByteArray body = Api::form({{"url", old}, {"new_url", url.trimmed()},
                                       {"title", title}, {"category", category}});
    m_api.request("PUT", "/feeds", body, [this, old](const ApiResult &r) {
        if (!r.ok) {
            emit toast(r.error);
            return;
        }
        const QJsonObject o = r.json.toObject();
        if (m_selUrl == old)
            m_selUrl = o.value("feed_url").toString();
        m_changed = true;
        // saved, but the new URL did not load: say why
        const QString err = o.value("fetch_error").toString();
        if (!err.isEmpty())
            emit toast("Saved, but the feed failed: " + err);
        else
            emit toast("Feed updated, " + QString::number(o.value("added").toInt()) + " new");
        loadFeeds();
    });
}

void Reader::importOpml(const QString &opml) {
    if (opml.trimmed().isEmpty())
        return;
    m_api.post("/opml", Api::form({{"opml", opml}}), [this](const ApiResult &r) {
        if (!r.ok) {
            emit toast(r.error);
            return;
        }
        const QJsonObject o = r.json.toObject();
        const int added = o.value("added").toInt();
        const int failed = int(o.value("errors").toArray().size());
        if (added > 0)
            m_changed = true;
        QString t = QString::number(added) + " feed(s) added";
        if (failed > 0)
            t += ", " + QString::number(failed) + " failed";
        emit toast(t);
        loadFeeds();
    });
}

void Reader::exportOpml() {
    m_api.get("/opml", [this](const ApiResult &r) {
        if (!r.ok) {
            emit toast(r.error);
            return;
        }
        platform::copyText(QString::fromUtf8(r.raw));
        emit toast("OPML backup copied to clipboard");
    });
}

QString Reader::snapshot() const {
    QJsonArray arts;
    for (int i = 0; i < m_articles.size(); ++i) {
        Article &a = const_cast<ArticleModel &>(m_articles).at(i);
        arts.append(QJsonObject{{"id", a.id}, {"title", a.title}, {"preview", a.preview},
                                {"ago", a.ago}, {"read", a.read}, {"hasLink", a.hasLink},
                                {"newLine", a.newLine}, {"feedTitle", a.feedTitle}});
    }
    QJsonArray feeds;
    for (int i = 0; i < m_feeds.size(); ++i)
        feeds.append(QJsonObject{{"title", m_feeds.at(i).title}, {"url", m_feeds.at(i).url},
                                 {"unread", m_feeds.at(i).unread}, {"error", m_feeds.at(i).error}});
    return QString::fromUtf8(QJsonDocument(QJsonObject{
        {"unread", m_unread}, {"selected", m_sel}, {"status", m_status}, {"search", m_search},
        {"refreshing", m_refreshing}, {"listState", m_listState}, {"listError", m_listError},
        {"managing", m_managing}, {"toast", m_lastToast}, {"articles", arts}, {"feeds", feeds}}).toJson(QJsonDocument::Compact));
}
