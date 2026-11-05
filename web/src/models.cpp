#include "models.h"

#include <QDateTime>
#include <QJsonObject>
#include <QTextDocumentFragment>
#include <QUrl>

// ------------------------------------------------------------------ formatting

namespace fmt {
QString preview(const QString &html) {
    // Long-form feeds put whole posts in the summary; only the start is read.
    if (html.isEmpty())
        return {};
    QString t = QTextDocumentFragment::fromHtml(html.left(4000)).toPlainText();
    t.remove(QChar(0xFFFC));  // where images were
    t = t.simplified();
    return t.size() > 400 ? t.left(400) : t;
}

QString ago(const QString &iso) {
    if (iso.isEmpty())
        return {};
    QDateTime t = QDateTime::fromString(iso, Qt::ISODateWithMs);
    if (!t.isValid())
        t = QDateTime::fromString(iso, Qt::ISODate);
    if (!t.isValid())
        return {};
    const qint64 m = t.secsTo(QDateTime::currentDateTimeUtc()) / 60;
    if (m < 1) return QStringLiteral("now");
    if (m < 60) return QString::number(m) + "m";
    const qint64 h = m / 60;
    if (h < 24) return QString::number(h) + "h";
    const qint64 d = h / 24;
    if (d < 30) return QString::number(d) + "d";
    if (d < 365) return QString::number(d / 30) + "mo";
    return QString::number(d / 365) + "y";
}

QString initial(const QString &title) {
    const QString t = title.trimmed();
    return t.isEmpty() ? QStringLiteral("?") : t.left(1).toUpper();
}

bool isLink(const QString &url) {
    const QUrl u(url, QUrl::StrictMode);
    return u.isValid() && !u.host().isEmpty()
        && (u.scheme() == QLatin1String("http") || u.scheme() == QLatin1String("https"));
}
}

static QString str(const QJsonObject &o, const char *k) {
    const QJsonValue v = o.value(QLatin1String(k));
    return v.isString() ? v.toString() : v.isNull() || v.isUndefined() ? QString() : v.toVariant().toString();
}

// ------------------------------------------------------------------ feeds

int FeedModel::rowCount(const QModelIndex &parent) const {
    return parent.isValid() ? 0 : int(m_rows.size());
}

QVariant FeedModel::data(const QModelIndex &index, int role) const {
    if (!index.isValid() || index.row() >= m_rows.size())
        return {};
    const Feed &f = m_rows[index.row()];
    switch (role) {
    case UrlRole: return f.url;
    case TitleRole: return f.title;
    case CategoryRole: return f.category;
    case FaviconRole: return f.faviconUrl;
    case ErrorRole: return f.error;
    case UnreadRole: return f.unread;
    case InitialRole: return fmt::initial(f.title);
    case IndexRole: return index.row();
    }
    return {};
}

QHash<int, QByteArray> FeedModel::roleNames() const {
    return {{UrlRole, "feedUrl"}, {TitleRole, "title"}, {CategoryRole, "category"},
            {FaviconRole, "faviconUrl"}, {ErrorRole, "error"}, {UnreadRole, "unread"},
            {InitialRole, "initial"}, {IndexRole, "feedIndex"}};
}

void FeedModel::reset(const QJsonArray &rows) {
    beginResetModel();
    m_rows.clear();
    m_rows.reserve(rows.size());
    for (const QJsonValue &v : rows) {
        const QJsonObject o = v.toObject();
        Feed f;
        f.url = str(o, "feed_url");
        f.title = str(o, "title");
        f.category = str(o, "category");
        f.faviconUrl = str(o, "favicon_url");
        f.error = str(o, "error");
        f.unread = o.value(QLatin1String("unread")).toInt();
        m_rows.push_back(f);
    }
    endResetModel();
}

int FeedModel::find(const QString &url) const {
    for (int i = 0; i < m_rows.size(); ++i)
        if (m_rows[i].url == url)
            return i;
    return -1;
}

void FeedModel::addUnread(int i, int delta) {
    if (i < 0 || i >= m_rows.size())
        return;
    m_rows[i].unread = qMax(0, m_rows[i].unread + delta);
    emit dataChanged(index(i), index(i), {UnreadRole});
}

void FeedFilter::setText(const QString &t) {
    if (t == m_text)
        return;
    beginFilterChange();
    m_text = t;
    endFilterChange(QSortFilterProxyModel::Direction::Rows);
    emit textChanged();
}

bool FeedFilter::filterAcceptsRow(int row, const QModelIndex &parent) const {
    if (m_text.isEmpty())
        return true;
    const QModelIndex i = sourceModel()->index(row, 0, parent);
    return i.data(FeedModel::TitleRole).toString().contains(m_text, Qt::CaseInsensitive)
        || i.data(FeedModel::UrlRole).toString().contains(m_text, Qt::CaseInsensitive);
}

// ------------------------------------------------------------------ articles

int ArticleModel::rowCount(const QModelIndex &parent) const {
    return parent.isValid() ? 0 : int(m_rows.size());
}

QVariant ArticleModel::data(const QModelIndex &index, int role) const {
    if (!index.isValid() || index.row() >= m_rows.size())
        return {};
    const Article &a = m_rows[index.row()];
    switch (role) {
    case IdRole: return a.id;
    case FeedTitleRole: return a.feedTitle;
    case TitleRole: return a.title;
    case UrlRole: return a.url;
    case PreviewRole: return a.preview;
    case PublishedRole: return a.published;
    case AgoRole: return a.ago;
    case ReadRole: return a.read;
    case HasLinkRole: return a.hasLink;
    case NewLineRole: return a.newLine;
    }
    return {};
}

QHash<int, QByteArray> ArticleModel::roleNames() const {
    return {{IdRole, "articleId"}, {FeedTitleRole, "feedTitle"}, {TitleRole, "title"},
            {UrlRole, "url"}, {PreviewRole, "preview"}, {PublishedRole, "published"},
            {AgoRole, "ago"}, {ReadRole, "isRead"}, {HasLinkRole, "hasLink"},
            {NewLineRole, "newLine"}};
}

void ArticleModel::reset(const QJsonArray &rows, bool markNew) {
    QVector<Article> next;
    next.reserve(rows.size());
    int firstSeen = -1;
    for (const QJsonValue &v : rows) {
        const QJsonObject o = v.toObject();
        Article a;
        a.id = o.value(QLatin1String("id")).toInt();
        a.feedUrl = str(o, "feed_url");
        a.feedTitle = str(o, "feed_title");
        a.title = fmt::preview(str(o, "title"));
        a.url = str(o, "url");
        a.hasLink = fmt::isLink(a.url);
        a.preview = fmt::preview(str(o, "summary"));
        a.published = str(o, "published");
        a.ago = fmt::ago(a.published);
        a.read = o.value(QLatin1String("is_read")).toBool();
        if (markNew && m_hasSeen && firstSeen < 0 && m_seen.contains(a.id))
            firstSeen = int(next.size());
        next.push_back(a);
    }
    // only draw the line when something new sits above something seen
    if (firstSeen > 0)
        next[firstSeen].newLine = true;
    m_seen.clear();
    for (const Article &a : next)
        m_seen.push_back(a.id);
    m_hasSeen = true;

    beginResetModel();
    m_rows = std::move(next);
    endResetModel();
}

void ArticleModel::setRead(int i, bool read) {
    if (i < 0 || i >= m_rows.size())
        return;
    m_rows[i].read = read;
    emit dataChanged(index(i), index(i), {ReadRole});
}

void ArticleModel::retime() {
    for (Article &a : m_rows)
        a.ago = fmt::ago(a.published);
    if (!m_rows.isEmpty())
        emit dataChanged(index(0), index(int(m_rows.size()) - 1), {AgoRole});
}
