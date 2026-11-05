// Requests to the reader's JSON API, which shares the page's origin, so the
// session cookie rides along with every one.
#pragma once

#include <QJsonValue>
#include <QNetworkAccessManager>
#include <QObject>
#include <functional>

struct ApiResult {
    bool ok = false;
    QString error;      // set when !ok
    QJsonValue json;    // the body, when it was JSON
    QByteArray raw;     // the body as it came
};

class Api : public QObject {
    Q_OBJECT
public:
    using Callback = std::function<void(const ApiResult &)>;

    explicit Api(QObject *parent = nullptr);

    // path is absolute on the reader ("/feeds?url=…"); body, when not null,
    // goes as a form. A 401 sends the browser to the sign-in page instead of
    // calling back.
    void request(const QByteArray &method, const QString &path,
                 const QByteArray &body, Callback cb);
    void get(const QString &path, Callback cb) { request("GET", path, {}, std::move(cb)); }
    void post(const QString &path, const QByteArray &body, Callback cb) {
        request("POST", path, body.isNull() ? QByteArray("") : body, std::move(cb));
    }

    // "a=b&c=d", each value URI-encoded
    static QByteArray form(std::initializer_list<std::pair<const char *, QString>> fields);
    static QString enc(const QString &s);

private:
    QNetworkAccessManager m_net;
    QUrl m_base;
};
