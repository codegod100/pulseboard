// The app's state and everything it does; the QML is only the look of it.
#pragma once

#include "api.h"
#include "models.h"

#include <QObject>
#include <QQmlEngine>

class Reader : public QObject {
    Q_OBJECT
    QML_ELEMENT
    QML_SINGLETON

    Q_PROPERTY(FeedModel *feeds READ feeds CONSTANT)
    Q_PROPERTY(FeedFilter *feedFilter READ feedFilter CONSTANT)
    Q_PROPERTY(ArticleModel *articles READ articles CONSTANT)

    Q_PROPERTY(int unread READ unread NOTIFY changed)
    Q_PROPERTY(int selected READ selected NOTIFY changed)
    Q_PROPERTY(QString selectedTitle READ selectedTitle NOTIFY changed)
    Q_PROPERTY(int selectedUnread READ selectedUnread NOTIFY changed)
    Q_PROPERTY(int feedCount READ feedCount NOTIFY changed)
    Q_PROPERTY(int status READ status NOTIFY changed)
    Q_PROPERTY(QString search READ search NOTIFY changed)   // the search applied to the list, or ""
    Q_PROPERTY(bool refreshing READ refreshing NOTIFY changed)
    Q_PROPERTY(int listState READ listState NOTIFY changed)
    Q_PROPERTY(QString listError READ listError NOTIFY changed)
    Q_PROPERTY(QString feedsError READ feedsError NOTIFY changed)
    Q_PROPERTY(bool managing READ managing NOTIFY changed)
    Q_PROPERTY(bool adding READ adding NOTIFY changed)

public:
    enum ListState { Loading, Ready, Failed };
    Q_ENUM(ListState)
    enum Status { Unread, All, Read };
    Q_ENUM(Status)

    explicit Reader(QObject *parent = nullptr);

    FeedModel *feeds() { return &m_feeds; }
    FeedFilter *feedFilter() { return &m_filter; }
    ArticleModel *articles() { return &m_articles; }
    int unread() const { return m_unread; }
    int selected() const { return m_sel; }
    QString selectedTitle() const;
    int selectedUnread() const;
    int feedCount() const { return m_feeds.size(); }
    int status() const { return m_status; }
    QString search() const { return m_search; }
    bool refreshing() const { return m_refreshing; }
    int listState() const { return m_listState; }
    QString listError() const { return m_listError; }
    QString feedsError() const { return m_feedsError; }
    bool managing() const { return m_managing; }
    bool adding() const { return m_adding; }

    Q_INVOKABLE void refresh() { startRefresh(false); }
    Q_INVOKABLE void select(int feed);            // -1 for every feed
    Q_INVOKABLE void setStatus(int status);
    Q_INVOKABLE void applySearch(const QString &q);
    Q_INVOKABLE void clearSearch() { applySearch({}); }
    Q_INVOKABLE void toggleRead(int row);
    Q_INVOKABLE void open(int row);               // follow the link, mark it read
    Q_INVOKABLE void hoverLink(const QString &url); // the link under the pointer, "" for none
    Q_INVOKABLE void leaveLink(const QString &url); // the pointer left the row with this link
    Q_INVOKABLE void markAllRead();               // the feed shown, or everything
    Q_INVOKABLE void retry();

    Q_INVOKABLE void openManage();
    Q_INVOKABLE void closeManage();
    Q_INVOKABLE void addFeed(const QString &url);
    Q_INVOKABLE void removeFeed(int feed);
    Q_INVOKABLE QVariantMap feed(int feed) const; // for the edit dialog
    Q_INVOKABLE void editFeed(int feed, const QString &title, const QString &url,
                              const QString &category);
    Q_INVOKABLE void importOpml(const QString &opml);
    Q_INVOKABLE void exportOpml();

    // For the browser test: the state as JSON.
    Q_INVOKABLE QString snapshot() const;

signals:
    void changed();
    void toast(const QString &text);
    void addSucceeded();   // the add box can empty itself
    void searchReset();    // the search box can empty itself

private:
    void loadFeeds();
    void loadArticles(bool markNew);
    void startRefresh(bool quiet);
    void postRead(int row, bool read);
    void setRead(int row, bool read);
    void linkArticles();
    void gotFeeds(const ApiResult &r);
    void gotArticles(int serial, const ApiResult &r);

    Api m_api;
    FeedModel m_feeds;
    FeedFilter m_filter;
    ArticleModel m_articles;
    QVector<int> m_artFeed;  // each row's feed index, for the per-feed counts

    int m_unread = 0;
    int m_sel = -1;
    QString m_hoverUrl;      // what hoverLink last gave the page
    QString m_selUrl;        // so the selection survives a reload of the feeds
    int m_status = Unread;
    QString m_search;
    bool m_refreshing = false;
    bool m_booted = false;   // the refresh on opening has started
    int m_serial = 0;        // the article request whose answer we want
    int m_listState = Loading;
    QString m_listError, m_feedsError;
    bool m_managing = false, m_changed = false, m_adding = false;
    QString m_lastToast;     // for snapshot()
};
