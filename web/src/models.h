// The feed list and the article list, as models the QML views draw.
#pragma once

#include <QAbstractListModel>
#include <QJsonArray>
#include <QSortFilterProxyModel>
#include <QVector>

struct Feed {
    QString url, title, category, faviconUrl, error;
    int unread = 0;
};

struct Article {
    int id = 0;
    QString feedUrl, feedTitle, title, url, preview, published, ago;
    bool read = false;
    bool hasLink = false;   // the URL is http(s)
    bool newLine = false;   // the red "new since last fetch" line sits above it
};

class FeedModel : public QAbstractListModel {
    Q_OBJECT
public:
    enum Role { UrlRole = Qt::UserRole + 1, TitleRole, CategoryRole, FaviconRole,
                ErrorRole, UnreadRole, InitialRole, IndexRole };
    using QAbstractListModel::QAbstractListModel;

    int rowCount(const QModelIndex &parent = {}) const override;
    QVariant data(const QModelIndex &index, int role) const override;
    QHash<int, QByteArray> roleNames() const override;

    void reset(const QJsonArray &rows);
    int find(const QString &url) const;
    const Feed &at(int i) const { return m_rows[i]; }
    int size() const { return int(m_rows.size()); }
    void addUnread(int i, int delta);

private:
    QVector<Feed> m_rows;
};

// Manage feeds' filter box: a feed shows when its title or URL contains the text.
class FeedFilter : public QSortFilterProxyModel {
    Q_OBJECT
    Q_PROPERTY(QString text READ text WRITE setText NOTIFY textChanged)
public:
    using QSortFilterProxyModel::QSortFilterProxyModel;
    QString text() const { return m_text; }
    void setText(const QString &t);
signals:
    void textChanged();
protected:
    bool filterAcceptsRow(int row, const QModelIndex &parent) const override;
private:
    QString m_text;
};

class ArticleModel : public QAbstractListModel {
    Q_OBJECT
public:
    enum Role { IdRole = Qt::UserRole + 1, FeedTitleRole, TitleRole, UrlRole, PreviewRole,
                PublishedRole, AgoRole, ReadRole, HasLinkRole, NewLineRole };
    using QAbstractListModel::QAbstractListModel;

    int rowCount(const QModelIndex &parent = {}) const override;
    QVariant data(const QModelIndex &index, int role) const override;
    QHash<int, QByteArray> roleNames() const override;

    // Replace the rows. With markNew, the red line goes above the first row
    // that was already on screen, when something new sits above it.
    void reset(const QJsonArray &rows, bool markNew);
    Article &at(int i) { return m_rows[i]; }
    int size() const { return int(m_rows.size()); }
    void setRead(int i, bool read);
    void retime();  // recompute "3h" and friends

private:
    QVector<Article> m_rows;
    QVector<int> m_seen;
    bool m_hasSeen = false;
};

namespace fmt {
QString preview(const QString &html);   // the start of some HTML as plain text
QString ago(const QString &iso);        // "now", "5m", "3h", "2d", "4mo", "1y"
QString initial(const QString &title);  // for a favicon placeholder
bool isLink(const QString &url);        // http(s)
}
