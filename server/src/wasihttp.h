// HTTP in and out over wasi:http 0.2, in Qt types.
//
// The component exports wasi:http/incoming-handler (main.cpp turns each
// incoming request into a `Request` and sends back a `Response`) and imports
// wasi:http/outgoing-handler, which `fetch` and `fetchAll` use for feeds,
// AT Protocol sign-in and Neon. There is no event loop to hand back to:
// fetchAll drives its requests itself with wasi:io/poll until all are done.
#pragma once

#include <QByteArray>
#include <QList>
#include <QPair>
#include <QString>

namespace http {

// Header names are kept lowercase, which is how wasi:http hands them over.
struct Headers {
    QList<QPair<QByteArray, QByteArray>> list;

    QByteArray get(const QByteArray &name) const;
    bool has(const QByteArray &name) const;
    void set(const QByteArray &name, const QByteArray &value);
    void add(const QByteArray &name, const QByteArray &value);
};

struct Request {
    QByteArray method;     // GET, POST, ...
    QByteArray path;       // percent-encoded, without the query
    QByteArray query;      // without the '?'
    QByteArray scheme;     // http or https, as the host saw it
    QByteArray authority;  // host[:port]
    Headers headers;
    QByteArray body;
};

struct Response {
    int status = 200;
    Headers headers;
    QByteArray body;
    // Outgoing only: why there is no response (DNS, refused, timed out...).
    // Empty when the server answered, whatever the status.
    QString error;
};

struct Outgoing {
    QByteArray method = "GET";
    QString url;
    Headers headers;
    QByteArray body;
    int timeoutMs = 15000;
    bool followRedirects = true;
    // Requests to other people's servers. With PULSEBOARD_TEST_UPSTREAM set
    // (tests only), these go there instead, with the URL in a header.
    bool external = true;
};

Response fetch(const Outgoing &req);
// At most `concurrency` in flight at once; results in the order given.
QList<Response> fetchAll(const QList<Outgoing> &reqs, int concurrency = 8);

void sleepMs(int ms);
QByteArray randomBytes(int n);
qint64 unixTime();

}  // namespace http
