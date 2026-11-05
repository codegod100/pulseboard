#include "api.h"
#include "platform.h"

#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QNetworkReply>
#include <QNetworkRequest>

Api::Api(QObject *parent) : QObject(parent), m_base(platform::origin()) {}

QString Api::enc(const QString &s) {
    return QString::fromLatin1(QUrl::toPercentEncoding(s));
}

QByteArray Api::form(std::initializer_list<std::pair<const char *, QString>> fields) {
    QByteArray out;
    for (const auto &[k, v] : fields) {
        if (!out.isEmpty())
            out += '&';
        out += k;
        out += '=';
        out += QUrl::toPercentEncoding(v);
    }
    return out;
}

void Api::request(const QByteArray &method, const QString &path,
                  const QByteArray &body, Callback cb) {
    QNetworkRequest req(m_base.resolved(QUrl(path)));
    req.setRawHeader("Accept", "application/json");
    if (!body.isNull())
        req.setHeader(QNetworkRequest::ContentTypeHeader,
                      "application/x-www-form-urlencoded");
    QNetworkReply *reply = body.isNull()
        ? m_net.sendCustomRequest(req, method)
        : m_net.sendCustomRequest(req, method, body);

    QObject::connect(reply, &QNetworkReply::finished, this, [reply, cb = std::move(cb)] {
        reply->deleteLater();
        const int status = reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();
        if (status == 401) {
            // The session is gone: the reader's sign-in page sets a new one
            // and comes back here.
            platform::navigate(QStringLiteral("/auth/login"));
            return;
        }
        ApiResult r;
        if (status == 0) {
            r.error = QStringLiteral("Could not reach the reader.");
            cb(r);
            return;
        }
        r.raw = reply->readAll();
        const QString type = reply->header(QNetworkRequest::ContentTypeHeader).toString();
        bool parsed = true;
        if (type.contains(QLatin1String("json"))) {
            if (r.raw.trimmed().isEmpty()) {
                r.json = QJsonObject();
            } else {
                QJsonParseError err;
                QJsonDocument doc = QJsonDocument::fromJson(r.raw, &err);
                if (err.error != QJsonParseError::NoError) {
                    parsed = false;
                } else {
                    r.json = doc.isArray() ? QJsonValue(doc.array()) : QJsonValue(doc.object());
                }
            }
        }
        if (!parsed) {
            r.error = QStringLiteral("Unexpected response from server.");
        } else if (r.json.isObject() && r.json.toObject().contains(QLatin1String("error"))
                   && !r.json.toObject().value(QLatin1String("error")).isNull()) {
            r.error = r.json.toObject().value(QLatin1String("error")).toVariant().toString();
        } else if (status < 200 || status >= 300) {
            r.error = QStringLiteral("Request failed (%1).").arg(status);
        } else {
            r.ok = true;
        }
        cb(r);
    });
}
