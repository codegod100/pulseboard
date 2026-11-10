#include "util.h"

#include "wasihttp.h"

#include <QRegularExpression>
#include <QTimeZone>
#include <cstring>

#include "entities.inc"

namespace util {

QString escape(const QString &s, bool quote) {
    QString out;
    out.reserve(s.size() + 8);
    for (QChar c : s) {
        switch (c.unicode()) {
        case '&': out += QLatin1StringView("&amp;"); break;
        case '<': out += QLatin1StringView("&lt;"); break;
        case '>': out += QLatin1StringView("&gt;"); break;
        case '"':
            if (quote) out += QLatin1StringView("&quot;");
            else out += c;
            break;
        case '\'':
            if (quote) out += QLatin1StringView("&#x27;");
            else out += c;
            break;
        default: out += c;
        }
    }
    return out;
}

std::optional<QString> namedEntity(const QByteArray &name) {
    size_t lo = 0, hi = sizeof(kEntities) / sizeof(kEntities[0]);
    while (lo < hi) {
        const size_t mid = (lo + hi) / 2;
        const int c = std::strcmp(kEntities[mid].name, name.constData());
        if (c == 0)
            return QString::fromUtf8(kEntities[mid].utf8);
        if (c < 0)
            lo = mid + 1;
        else
            hi = mid;
    }
    return std::nullopt;
}

namespace {

// What html.unescape does with a numeric reference.
QString codepoint(uint cp) {
    static const ushort cp1252[32] = {
        0x20ac, 0x81, 0x201a, 0x0192, 0x201e, 0x2026, 0x2020, 0x2021, 0x02c6, 0x2030, 0x0160,
        0x2039, 0x0152, 0x8d, 0x017d, 0x8f, 0x90, 0x2018, 0x2019, 0x201c, 0x201d, 0x2022,
        0x2013, 0x2014, 0x02dc, 0x2122, 0x0161, 0x203a, 0x0153, 0x9d, 0x017e, 0x0178};
    if (cp >= 0x80 && cp <= 0x9f)
        return QString(QChar(cp1252[cp - 0x80]));
    if (cp == 0 || (cp >= 0xd800 && cp <= 0xdfff) || cp > 0x10ffff)
        return QString(QChar(0xfffd));
    if ((cp >= 0x1 && cp <= 0x8) || cp == 0xb || (cp >= 0xe && cp <= 0x1f) || (cp >= 0x7f && cp <= 0x9f)
        || (cp >= 0xfdd0 && cp <= 0xfdef) || (cp & 0xfffe) == 0xfffe)
        return {};
    const char32_t c = cp;
    return QString::fromUcs4(&c, 1);
}

}  // namespace

QString unescape(const QString &s) {
    if (!s.contains(u'&'))
        return s;
    static const QRegularExpression ref(QStringLiteral(
        "&(#[0-9]+;?|#[xX][0-9a-fA-F]+;?|[^\\t\\n\\f <&#;]{1,32};?)"));
    QString out;
    qsizetype last = 0;
    auto it = ref.globalMatch(s);
    while (it.hasNext()) {
        const auto m = it.next();
        out += QStringView(s).mid(last, m.capturedStart() - last);
        last = m.capturedEnd();
        QString r = m.captured(1);
        if (r.startsWith(u'#')) {
            bool ok = false;
            QString digits = r.mid(1);
            if (digits.endsWith(u';'))
                digits.chop(1);
            uint cp = (digits.startsWith(u'x') || digits.startsWith(u'X'))
                          ? digits.mid(1).toUInt(&ok, 16)
                          : digits.toUInt(&ok, 10);
            out += ok ? codepoint(cp) : QString(QChar(0xfffd));
            continue;
        }
        const QByteArray name = r.toUtf8();
        if (auto e = namedEntity(name)) {
            out += *e;
            continue;
        }
        // The longest known prefix (HTML5 allows a few without ';').
        bool found = false;
        for (qsizetype n = name.size() - 1; n > 0; --n) {
            if (auto e = namedEntity(name.left(n))) {
                out += *e + QString::fromUtf8(name.mid(n));
                found = true;
                break;
            }
        }
        if (!found)
            out += u'&' + r;
    }
    out += QStringView(s).mid(last);
    return out;
}

QString b64url(const QByteArray &data) {
    return QString::fromLatin1(data.toBase64(QByteArray::Base64UrlEncoding | QByteArray::OmitTrailingEquals));
}

QByteArray b64urlDecode(const QString &s) {
    return QByteArray::fromBase64(s.toLatin1(), QByteArray::Base64UrlEncoding);
}

QString token(int nbytes) {
    return b64url(http::randomBytes(nbytes));
}

bool isHttpUrl(const QString &url) {
    return url.startsWith(u"http://") || url.startsWith(u"https://");
}

namespace {
QString formDecode(QByteArray s) {
    s.replace('+', ' ');
    return QString::fromUtf8(QByteArray::fromPercentEncoding(s));
}
}  // namespace

Pairs parseQuery(const QByteArray &q) {
    Pairs out;
    for (const QByteArray &part : q.split('&')) {
        if (part.isEmpty())
            continue;
        const qsizetype eq = part.indexOf('=');
        if (eq < 0)
            out.append({formDecode(part), QString()});
        else
            out.append({formDecode(part.left(eq)), formDecode(part.mid(eq + 1))});
    }
    return out;
}

QByteArray percentEncode(const QString &s) {
    QByteArray e = s.toUtf8().toPercentEncoding(" ", "_.-~");
    e.replace(' ', '+');
    return e;
}

QByteArray encodeQuery(const Pairs &pairs) {
    QByteArray out;
    for (const auto &[k, v] : pairs) {
        if (!out.isEmpty())
            out += '&';
        out += percentEncode(k) + '=' + percentEncode(v);
    }
    return out;
}

QString dbTime(const QDateTime &t) {
    if (!t.isValid())
        return {};
    return t.toUTC().toString(QStringLiteral("yyyy-MM-dd HH:mm:ss"));
}

QString isoTime(const QString &s) {
    if (s.isEmpty())
        return {};
    QString t = s;
    // Postgres writes fractions and zones the database never stores; drop them.
    static const QRegularExpression frac(QStringLiteral("\\.\\d+"));
    t.remove(frac);
    if (t.endsWith(QLatin1StringView("+00")))
        t.chop(3);
    if (const qsizetype sp = t.indexOf(u' '); sp >= 0)
        t[sp] = u'T';
    if (!t.endsWith(u'Z'))
        t += u'Z';
    return t;
}

}  // namespace util
