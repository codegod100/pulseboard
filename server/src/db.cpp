#include "db.h"

#include "wasihttp.h"

#include <QJsonArray>
#include <QJsonDocument>
#include <QRegularExpression>
#include <QSet>
#include <QUrl>

#include <cstdio>

#include "migrations.inc"  // generated: kMigrations[] = {{name, sql}, ...}

namespace {

// `?` placeholders to $1, $2... No query has a literal `?` in it.
QString numbered(const QString &sql) {
    QString out;
    out.reserve(sql.size() + 16);
    int n = 0;
    for (QChar c : sql) {
        if (c == u'?')
            out += u'$' + QString::number(++n);
        else
            out += c;
    }
    return out;
}

QJsonValue jsonParam(const Param &p) {
    if (!p.isValid() || p.isNull())
        return QJsonValue::Null;
    if (p.typeId() == QMetaType::Bool)
        return p.toBool() ? QStringLiteral("1") : QStringLiteral("0");
    return p.toString();
}

QJsonObject query(const QString &sql, const Params &params) {
    QJsonArray ps;
    for (const Param &p : params)
        ps.append(jsonParam(p));
    return QJsonObject{{"query", numbered(sql)}, {"params", ps}};
}

Rows rowsOf(const QJsonObject &result) {
    Rows out;
    for (const QJsonValue &v : result.value("rows").toArray())
        out.append(v.toObject());
    return out;
}

}  // namespace

Param null() { return QVariant(); }

QString text(const Row &r, const char *key) {
    const QJsonValue v = r.value(QLatin1StringView(key));
    if (v.isString())
        return v.toString();
    if (v.isDouble())
        return QString::number(v.toInteger());
    if (v.isBool())
        return v.toBool() ? QStringLiteral("1") : QStringLiteral("0");
    return {};
}

qint64 integer(const Row &r, const char *key) {
    const QJsonValue v = r.value(QLatin1StringView(key));
    if (v.isDouble())
        return v.toInteger();
    const QString s = v.toString();
    if (s == u"t")
        return 1;
    if (s == u"f")
        return 0;
    return s.toLongLong();
}

bool isNull(const Row &r, const char *key) {
    const QJsonValue v = r.value(QLatin1StringView(key));
    return v.isNull() || v.isUndefined();
}

Db::Db() {
    m_connection = qgetenv("DATABASE_URL");
    m_endpoint = qEnvironmentVariable("NEON_SQL_URL");
    if (m_endpoint.isEmpty() && !m_connection.isEmpty()) {
        const QUrl u(QString::fromUtf8(m_connection));
        m_endpoint = QStringLiteral("https://%1/sql").arg(u.host());
    }
}

QJsonObject Db::post(const QByteArray &body) {
    if (failed())
        return {};
    if (m_connection.isEmpty() || m_endpoint.isEmpty()) {
        m_error = QStringLiteral("DATABASE_URL is not set");
        std::fprintf(stderr, "pulseboard: %s\n", qPrintable(m_error));
        return {};
    }
    http::Outgoing req;
    req.method = "POST";
    req.url = m_endpoint;
    req.external = false;
    req.followRedirects = false;
    req.timeoutMs = 30000;
    req.headers.set("content-type", "application/json");
    req.headers.set("neon-connection-string", m_connection);
    req.headers.set("neon-raw-text-output", "true");
    req.headers.set("neon-array-mode", "false");
    req.body = body;
    const http::Response res = http::fetch(req);
    if (!res.error.isEmpty() || res.status != 200) {
        QString detail = res.error;
        if (detail.isEmpty()) {
            const QJsonObject err = QJsonDocument::fromJson(res.body).object();
            detail = QStringLiteral("HTTP %1: %2").arg(res.status).arg(
                err.value("message").toString(QString::fromUtf8(res.body.left(300))));
        }
        m_error = QStringLiteral("database: ") + detail;
        std::fprintf(stderr, "pulseboard: %s\n  in: %s\n", qPrintable(m_error), body.left(500).constData());
        return {};
    }
    return QJsonDocument::fromJson(res.body).object();
}

Rows Db::all(const QString &sql, const Params &params) {
    return rowsOf(post(QJsonDocument(query(sql, params)).toJson(QJsonDocument::Compact)));
}

std::optional<Row> Db::first(const QString &sql, const Params &params) {
    const Rows rows = all(sql, params);
    if (rows.isEmpty())
        return std::nullopt;
    return rows.first();
}

int Db::run(const QString &sql, const Params &params) {
    const QJsonObject r = post(QJsonDocument(query(sql, params)).toJson(QJsonDocument::Compact));
    return qMax(0, r.value("rowCount").toInt());
}

void Db::batch(const QList<Statement> &statements) {
    if (statements.isEmpty())
        return;
    QJsonArray qs;
    for (const Statement &s : statements)
        qs.append(query(s.sql, s.params));
    post(QJsonDocument(QJsonObject{{"queries", qs}}).toJson(QJsonDocument::Compact));
}

QStringList Db::migrate() {
    QStringList applied;
    run(QStringLiteral("CREATE TABLE IF NOT EXISTS _migrations (name TEXT PRIMARY KEY)"));
    QSet<QString> done;
    for (const Row &r : all(QStringLiteral("SELECT name FROM _migrations")))
        done.insert(text(r, "name"));
    if (failed())
        return applied;
    static const QRegularExpression comment(QStringLiteral("--[^\n]*"));
    for (const auto &m : kMigrations) {
        const QString name = QString::fromUtf8(m.name);
        if (done.contains(name))
            continue;
        // The SQL endpoint takes one statement per query: split the script.
        QList<Statement> stmts;
        QString script = QString::fromUtf8(m.sql);
        script.remove(comment);
        for (const QString &part : script.split(u';')) {
            if (!part.trimmed().isEmpty())
                stmts.append({part.trimmed(), {}});
        }
        stmts.append({QStringLiteral("INSERT INTO _migrations (name) VALUES (?) ON CONFLICT DO NOTHING"), {name}});
        batch(stmts);
        if (failed())
            break;
        applied.append(name);
    }
    return applied;
}
