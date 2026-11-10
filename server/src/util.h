// Small shared helpers: escaping, encoding, tokens and times.
#pragma once

#include <QByteArray>
#include <QDateTime>
#include <QList>
#include <QPair>
#include <QString>
#include <optional>

namespace util {

// html.escape: & < > always, and " ' when `quote`.
QString escape(const QString &s, bool quote = true);
// html.unescape: named (HTML5) and numeric character references.
QString unescape(const QString &s);
// One named reference, e.g. "nbsp" or "amp;": its text, if HTML5 knows it.
std::optional<QString> namedEntity(const QByteArray &name);

QString b64url(const QByteArray &data);
QByteArray b64urlDecode(const QString &s);
// secrets.token_urlsafe(n): n random bytes, base64url.
QString token(int nbytes);

bool isHttpUrl(const QString &url);

// application/x-www-form-urlencoded, both ways. Order and repeats are kept.
using Pairs = QList<QPair<QString, QString>>;
Pairs parseQuery(const QByteArray &q);
QByteArray encodeQuery(const Pairs &pairs);
QByteArray percentEncode(const QString &s);

// "YYYY-MM-DD HH:MM:SS" (UTC), how the database keeps times.
QString dbTime(const QDateTime &t);
// The database's text for a timestamp as ISO 8601 with Z, for clients.
QString isoTime(const QString &s);

}  // namespace util
