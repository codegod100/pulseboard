// Postgres (Neon) over its SQL-over-HTTP endpoint: one HTTPS POST per query,
// or per transaction for `batch`. There is no socket API in wasi:http, so
// this is how a component reaches Postgres at all.
//
// DATABASE_URL is the Neon connection string; queries go to
// https://<its host>/sql unless NEON_SQL_URL says otherwise (tests point it
// at a stand-in in front of a local Postgres).
//
// SQL uses `?` placeholders, rewritten to $1, $2... Values come back as text
// (Neon-Raw-Text-Output), so a row is a QJsonObject of strings and nulls.
//
// No exceptions here (Qt for WASI is built without them): the first failure
// is remembered, every later query in the same request returns nothing, and
// the API answers 500 when `failed()` is set.
#pragma once

#include <QJsonObject>
#include <QList>
#include <QString>
#include <QVariant>
#include <optional>

using Row = QJsonObject;
using Rows = QList<Row>;
// A parameter: a string, a number, or null (an empty std::optional).
using Param = QVariant;
using Params = QList<Param>;

struct Statement {
    QString sql;
    Params params;
};

class Db {
public:
    Db();

    Rows all(const QString &sql, const Params &params = {});
    std::optional<Row> first(const QString &sql, const Params &params = {});
    // Rows changed.
    int run(const QString &sql, const Params &params = {});
    // One transaction.
    void batch(const QList<Statement> &statements);

    bool failed() const { return !m_error.isEmpty(); }
    QString error() const { return m_error; }

    // Apply the embedded migrations not yet recorded in _migrations.
    QStringList migrate();

private:
    QJsonObject post(const QByteArray &body);

    QByteArray m_connection;
    QString m_endpoint;
    QString m_error;
};

// Helpers for reading text values.
QString text(const Row &r, const char *key);
qint64 integer(const Row &r, const char *key);
bool isNull(const Row &r, const char *key);
Param null();
