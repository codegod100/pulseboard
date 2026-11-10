#include "wasihttp.h"

#include "server.h"  // wit-bindgen's C bindings for the `server` world

#include <QUrl>
#include <qt2wasm/runtime.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>

// The app: api.cpp.
http::Response handleRequest(const http::Request &req);

namespace http {

namespace {

constexpr qsizetype MAX_INCOMING_BODY = 8 * 1024 * 1024;
constexpr qsizetype MAX_FETCHED_BODY = 20 * 1024 * 1024;
constexpr uint64_t MS = 1000 * 1000;  // nanoseconds

QByteArray bytes(const uint8_t *p, size_t n) {
    return QByteArray(reinterpret_cast<const char *>(p), qsizetype(n));
}

server_string_t str(const QByteArray &b) {
    return server_string_t{reinterpret_cast<uint8_t *>(const_cast<char *>(b.constData())),
                           size_t(b.size())};
}

// --- headers -----------------------------------------------------------------

Headers readFields(wasi_http_types_own_fields_t own) {
    Headers h;
    server_list_tuple2_field_name_field_value_t entries;
    wasi_http_types_method_fields_entries(wasi_http_types_borrow_fields(own), &entries);
    for (size_t i = 0; i < entries.len; ++i) {
        const auto &e = entries.ptr[i];
        h.list.append({bytes(e.f0.ptr, e.f0.len).toLower(), bytes(e.f1.ptr, e.f1.len)});
    }
    server_list_tuple2_field_name_field_value_free(&entries);
    wasi_http_types_fields_drop_own(own);
    return h;
}

// Headers the host manages itself; setting one is an error.
bool forbidden(const QByteArray &name) {
    static const char *const names[] = {"host", "connection", "keep-alive", "transfer-encoding",
                                        "upgrade", "proxy-connection", "http2-settings"};
    for (const char *n : names)
        if (name == n)
            return true;
    return false;
}

wasi_http_types_own_fields_t makeFields(const Headers &h) {
    wasi_http_types_own_fields_t f = wasi_http_types_constructor_fields();
    auto b = wasi_http_types_borrow_fields(f);
    for (const auto &[name, value] : h.list) {
        const QByteArray n = name.toLower();
        if (forbidden(n))
            continue;
        server_string_t sn = str(n);
        wasi_http_types_field_value_t v{reinterpret_cast<uint8_t *>(const_cast<char *>(value.constData())),
                                        size_t(value.size())};
        wasi_http_types_header_error_t err;
        if (!wasi_http_types_method_fields_append(b, &sn, &v, &err)) {
            std::fprintf(stderr, "pulseboard: header %s refused\n", n.constData());
            wasi_http_types_header_error_free(&err);
        }
    }
    return f;
}

// --- streams -----------------------------------------------------------------

void writeAll(wasi_io_streams_own_output_stream_t out, const QByteArray &body) {
    auto b = wasi_io_streams_borrow_output_stream(out);
    for (qsizetype off = 0; off < body.size(); off += 4096) {
        const qsizetype n = qMin<qsizetype>(4096, body.size() - off);
        server_list_u8_t chunk{reinterpret_cast<uint8_t *>(const_cast<char *>(body.constData() + off)),
                               size_t(n)};
        wasi_io_streams_stream_error_t err;
        if (!wasi_io_streams_method_output_stream_blocking_write_and_flush(b, &chunk, &err)) {
            wasi_io_streams_stream_error_free(&err);
            break;
        }
    }
    wasi_io_streams_output_stream_drop_own(out);
}

// Reads what is there without blocking. Returns false at the end of the stream.
bool drain(wasi_io_streams_own_input_stream_t in, QByteArray &into) {
    auto b = wasi_io_streams_borrow_input_stream(in);
    for (;;) {
        server_list_u8_t chunk;
        wasi_io_streams_stream_error_t err;
        if (!wasi_io_streams_method_input_stream_read(b, 64 * 1024, &chunk, &err)) {
            wasi_io_streams_stream_error_free(&err);
            return false;
        }
        if (chunk.len == 0) {
            server_list_u8_free(&chunk);
            return true;
        }
        into.append(reinterpret_cast<const char *>(chunk.ptr), qsizetype(chunk.len));
        server_list_u8_free(&chunk);
    }
}

QByteArray readAllBlocking(wasi_io_streams_own_input_stream_t in, qsizetype cap) {
    QByteArray out;
    auto b = wasi_io_streams_borrow_input_stream(in);
    for (;;) {
        server_list_u8_t chunk;
        wasi_io_streams_stream_error_t err;
        if (!wasi_io_streams_method_input_stream_blocking_read(b, 64 * 1024, &chunk, &err)) {
            wasi_io_streams_stream_error_free(&err);
            break;
        }
        out.append(reinterpret_cast<const char *>(chunk.ptr), qsizetype(chunk.len));
        server_list_u8_free(&chunk);
        if (out.size() > cap)
            break;
    }
    wasi_io_streams_input_stream_drop_own(in);
    return out;
}

QString describe(const wasi_http_types_error_code_t &e) {
    switch (e.tag) {
    case WASI_HTTP_TYPES_ERROR_CODE_DNS_TIMEOUT: return QStringLiteral("DNS lookup timed out");
    case WASI_HTTP_TYPES_ERROR_CODE_DNS_ERROR: return QStringLiteral("DNS lookup failed");
    case WASI_HTTP_TYPES_ERROR_CODE_DESTINATION_NOT_FOUND: return QStringLiteral("host not found");
    case WASI_HTTP_TYPES_ERROR_CODE_DESTINATION_UNAVAILABLE: return QStringLiteral("host unavailable");
    case WASI_HTTP_TYPES_ERROR_CODE_DESTINATION_IP_PROHIBITED: return QStringLiteral("address prohibited");
    case WASI_HTTP_TYPES_ERROR_CODE_DESTINATION_IP_UNROUTABLE: return QStringLiteral("address unroutable");
    case WASI_HTTP_TYPES_ERROR_CODE_CONNECTION_REFUSED: return QStringLiteral("connection refused");
    case WASI_HTTP_TYPES_ERROR_CODE_CONNECTION_TERMINATED: return QStringLiteral("connection closed");
    case WASI_HTTP_TYPES_ERROR_CODE_CONNECTION_TIMEOUT: return QStringLiteral("connection timed out");
    case WASI_HTTP_TYPES_ERROR_CODE_CONNECTION_READ_TIMEOUT: return QStringLiteral("read timed out");
    case WASI_HTTP_TYPES_ERROR_CODE_CONNECTION_WRITE_TIMEOUT: return QStringLiteral("write timed out");
    case WASI_HTTP_TYPES_ERROR_CODE_TLS_PROTOCOL_ERROR: return QStringLiteral("TLS error");
    case WASI_HTTP_TYPES_ERROR_CODE_TLS_CERTIFICATE_ERROR: return QStringLiteral("TLS certificate error");
    case WASI_HTTP_TYPES_ERROR_CODE_TLS_ALERT_RECEIVED: return QStringLiteral("TLS alert");
    case WASI_HTTP_TYPES_ERROR_CODE_HTTP_RESPONSE_INCOMPLETE: return QStringLiteral("incomplete response");
    case WASI_HTTP_TYPES_ERROR_CODE_HTTP_RESPONSE_TIMEOUT: return QStringLiteral("timed out");
    case WASI_HTTP_TYPES_ERROR_CODE_HTTP_PROTOCOL_ERROR: return QStringLiteral("HTTP protocol error");
    case WASI_HTTP_TYPES_ERROR_CODE_HTTP_REQUEST_URI_INVALID: return QStringLiteral("invalid URL");
    case WASI_HTTP_TYPES_ERROR_CODE_HTTP_REQUEST_DENIED: return QStringLiteral("request denied");
    case WASI_HTTP_TYPES_ERROR_CODE_INTERNAL_ERROR:
        if (e.val.internal_error.is_some)
            return QString::fromUtf8(bytes(e.val.internal_error.val.ptr, e.val.internal_error.val.len));
        return QStringLiteral("internal error");
    default: return QStringLiteral("HTTP error %1").arg(e.tag);
    }
}

// --- outgoing ----------------------------------------------------------------

struct Job {
    enum Phase { Idle, Waiting, Reading, Done } phase = Idle;
    Outgoing req;
    QUrl url;
    int redirects = 0;
    uint64_t deadline = 0;
    wasi_http_types_own_future_incoming_response_t future{};
    wasi_http_types_own_incoming_response_t response{};
    wasi_http_types_own_incoming_body_t body{};
    wasi_io_streams_own_input_stream_t stream{};
    Response res;
};

void closeBody(Job &j) {
    if (j.phase != Job::Reading)
        return;
    wasi_io_streams_input_stream_drop_own(j.stream);
    wasi_http_types_incoming_body_drop_own(j.body);
    wasi_http_types_incoming_response_drop_own(j.response);
}

void fail(Job &j, const QString &why) {
    if (j.phase == Job::Waiting)
        wasi_http_types_future_incoming_response_drop_own(j.future);
    closeBody(j);
    j.res = Response{};
    j.res.status = 0;
    j.res.error = why;
    j.phase = Job::Done;
}

QByteArray methodName(const wasi_http_types_method_t &m) {
    switch (m.tag) {
    case WASI_HTTP_TYPES_METHOD_GET: return "GET";
    case WASI_HTTP_TYPES_METHOD_HEAD: return "HEAD";
    case WASI_HTTP_TYPES_METHOD_POST: return "POST";
    case WASI_HTTP_TYPES_METHOD_PUT: return "PUT";
    case WASI_HTTP_TYPES_METHOD_DELETE: return "DELETE";
    case WASI_HTTP_TYPES_METHOD_CONNECT: return "CONNECT";
    case WASI_HTTP_TYPES_METHOD_OPTIONS: return "OPTIONS";
    case WASI_HTTP_TYPES_METHOD_TRACE: return "TRACE";
    case WASI_HTTP_TYPES_METHOD_PATCH: return "PATCH";
    default: return bytes(m.val.other.ptr, m.val.other.len);
    }
}

wasi_http_types_method_t methodOf(const QByteArray &name, QByteArray &keep) {
    static const char *const known[] = {"GET", "HEAD", "POST", "PUT", "DELETE",
                                        "CONNECT", "OPTIONS", "TRACE", "PATCH"};
    wasi_http_types_method_t m{};
    for (uint8_t i = 0; i < 9; ++i)
        if (name == known[i]) {
            m.tag = i;
            return m;
        }
    keep = name;
    m.tag = WASI_HTTP_TYPES_METHOD_OTHER;
    m.val.other = str(keep);
    return m;
}

void start(Job &j) {
    j.res = Response{};
    if (!j.url.isValid() || (j.url.scheme() != u"http" && j.url.scheme() != u"https")
        || j.url.host().isEmpty()) {
        fail(j, QStringLiteral("invalid URL"));
        return;
    }
    Headers headers = j.req.headers;
    if (!j.req.body.isEmpty() || j.req.method == "POST" || j.req.method == "PUT")
        headers.set("content-length", QByteArray::number(j.req.body.size()));
    QUrl target = j.url;
    static const QByteArray upstream = qgetenv("PULSEBOARD_TEST_UPSTREAM");
    if (j.req.external && !upstream.isEmpty()) {
        headers.set("x-test-original-url", j.url.toEncoded());
        const QUrl up(QString::fromUtf8(upstream));
        target.setScheme(up.scheme());
        target.setHost(up.host());
        target.setPort(up.port());
    }

    auto req = wasi_http_types_constructor_outgoing_request(makeFields(headers));
    auto rb = wasi_http_types_borrow_outgoing_request(req);
    QByteArray keepMethod;
    wasi_http_types_method_t m = methodOf(j.req.method, keepMethod);
    wasi_http_types_method_outgoing_request_set_method(rb, &m);
    wasi_http_types_scheme_t scheme{};
    scheme.tag = target.scheme() == u"https" ? WASI_HTTP_TYPES_SCHEME_HTTPS : WASI_HTTP_TYPES_SCHEME_HTTP;
    wasi_http_types_method_outgoing_request_set_scheme(rb, &scheme);
    QByteArray authority = QUrl::toAce(target.host());
    if (target.port() != -1)
        authority += ':' + QByteArray::number(target.port());
    server_string_t sa = str(authority);
    wasi_http_types_method_outgoing_request_set_authority(rb, &sa);
    QByteArray pq = target.path(QUrl::FullyEncoded).toUtf8();
    if (pq.isEmpty())
        pq = "/";
    if (target.hasQuery())
        pq += '?' + target.query(QUrl::FullyEncoded).toUtf8();
    server_string_t sp = str(pq);
    wasi_http_types_method_outgoing_request_set_path_with_query(rb, &sp);

    wasi_http_types_own_outgoing_body_t body;
    wasi_http_types_method_outgoing_request_body(rb, &body);

    auto options = wasi_http_types_constructor_request_options();
    auto ob = wasi_http_types_borrow_request_options(options);
    wasi_http_types_duration_t t = uint64_t(j.req.timeoutMs) * MS;
    wasi_http_types_method_request_options_set_connect_timeout(ob, &t);
    wasi_http_types_method_request_options_set_first_byte_timeout(ob, &t);
    wasi_http_types_method_request_options_set_between_bytes_timeout(ob, &t);

    wasi_http_outgoing_handler_error_code_t err;
    if (!wasi_http_outgoing_handler_handle(req, &options, &j.future, &err)) {
        const QString why = describe(err);
        wasi_http_outgoing_handler_error_code_free(&err);
        wasi_http_types_outgoing_body_drop_own(body);
        j.phase = Job::Done;
        j.res.status = 0;
        j.res.error = why;
        return;
    }
    wasi_http_types_own_output_stream_t out;
    if (wasi_http_types_method_outgoing_body_write(wasi_http_types_borrow_outgoing_body(body), &out))
        writeAll(out, j.req.body);
    wasi_http_types_error_code_t ferr;
    if (!wasi_http_types_static_outgoing_body_finish(body, nullptr, &ferr))
        wasi_http_types_error_code_free(&ferr);
    j.phase = Job::Waiting;
    j.deadline = wasi_clocks_monotonic_clock_now() + uint64_t(j.req.timeoutMs) * MS * 2;
}

// The response's headers are in; start reading its body, or follow a redirect.
void received(Job &j, wasi_http_types_own_incoming_response_t resp) {
    auto b = wasi_http_types_borrow_incoming_response(resp);
    j.res.status = wasi_http_types_method_incoming_response_status(b);
    j.res.headers = readFields(wasi_http_types_method_incoming_response_headers(b));
    const int s = j.res.status;
    const QByteArray location = j.res.headers.get("location");
    if (j.req.followRedirects && (s == 301 || s == 302 || s == 303 || s == 307 || s == 308)
        && !location.isEmpty() && j.redirects < 10) {
        wasi_http_types_incoming_response_drop_own(resp);
        j.redirects++;
        j.url = j.url.resolved(QUrl::fromEncoded(location));
        if (s == 303 || ((s == 301 || s == 302) && j.req.method == "POST")) {
            j.req.method = "GET";
            j.req.body.clear();
        }
        start(j);
        return;
    }
    j.response = resp;
    if (!wasi_http_types_method_incoming_response_consume(b, &j.body)) {
        wasi_http_types_incoming_response_drop_own(resp);
        j.phase = Job::Done;
        return;
    }
    if (!wasi_http_types_method_incoming_body_stream(wasi_http_types_borrow_incoming_body(j.body), &j.stream)) {
        wasi_http_types_incoming_body_drop_own(j.body);
        wasi_http_types_incoming_response_drop_own(resp);
        j.phase = Job::Done;
        return;
    }
    j.phase = Job::Reading;
}

void step(Job &j) {
    if (j.phase == Job::Waiting) {
        wasi_http_types_option_result_result_own_incoming_response_error_code_void_t got;
        if (!wasi_http_types_method_future_incoming_response_get(
                wasi_http_types_borrow_future_incoming_response(j.future), &got.val)) {
            return;  // not ready
        }
        wasi_http_types_future_incoming_response_drop_own(j.future);
        j.phase = Job::Idle;
        if (got.val.is_err) {
            fail(j, QStringLiteral("response already taken"));
            return;
        }
        if (got.val.val.ok.is_err) {
            const QString why = describe(got.val.val.ok.val.err);
            wasi_http_types_error_code_free(&got.val.val.ok.val.err);
            fail(j, why);
            return;
        }
        received(j, got.val.val.ok.val.ok);
        return;
    }
    if (j.phase == Job::Reading) {
        const bool more = drain(j.stream, j.res.body);
        if (j.res.body.size() > MAX_FETCHED_BODY) {
            fail(j, QStringLiteral("response too large"));
            return;
        }
        if (!more) {
            closeBody(j);
            j.phase = Job::Done;
        }
    }
}

}  // namespace

// --- Headers -------------------------------------------------------------------

QByteArray Headers::get(const QByteArray &name) const {
    const QByteArray n = name.toLower();
    for (const auto &[k, v] : list)
        if (k == n)
            return v;
    return {};
}

bool Headers::has(const QByteArray &name) const {
    const QByteArray n = name.toLower();
    for (const auto &kv : list)
        if (kv.first == n)
            return true;
    return false;
}

void Headers::set(const QByteArray &name, const QByteArray &value) {
    const QByteArray n = name.toLower();
    list.removeIf([&](const auto &kv) { return kv.first == n; });
    list.append({n, value});
}

void Headers::add(const QByteArray &name, const QByteArray &value) {
    list.append({name.toLower(), value});
}

// --- fetching --------------------------------------------------------------------

QList<Response> fetchAll(const QList<Outgoing> &reqs, int concurrency) {
    QList<Job> jobs(reqs.size());
    for (qsizetype i = 0; i < reqs.size(); ++i) {
        jobs[i].req = reqs[i];
        jobs[i].url = QUrl(reqs[i].url);
    }
    qsizetype next = 0;
    for (;;) {
        int active = 0;
        for (const Job &j : jobs)
            active += (j.phase == Job::Waiting || j.phase == Job::Reading);
        while (active < concurrency && next < jobs.size()) {
            start(jobs[next++]);
            active += jobs[next - 1].phase != Job::Done;
        }
        if (active == 0 && next >= jobs.size())
            break;

        // One pollable per job in flight, plus a timer for the nearest deadline.
        QList<wasi_io_poll_own_pollable_t> owned;
        QList<qsizetype> who;
        uint64_t nearest = UINT64_MAX;
        for (qsizetype i = 0; i < jobs.size(); ++i) {
            Job &j = jobs[i];
            if (j.phase == Job::Waiting)
                owned.append(wasi_http_types_method_future_incoming_response_subscribe(
                    wasi_http_types_borrow_future_incoming_response(j.future)));
            else if (j.phase == Job::Reading)
                owned.append(wasi_io_streams_method_input_stream_subscribe(
                    wasi_io_streams_borrow_input_stream(j.stream)));
            else
                continue;
            who.append(i);
            nearest = qMin(nearest, j.deadline);
        }
        owned.append(wasi_clocks_monotonic_clock_subscribe_instant(nearest));
        QList<wasi_io_poll_borrow_pollable_t> borrowed;
        for (auto p : owned)
            borrowed.append(wasi_io_poll_borrow_pollable(p));
        wasi_io_poll_list_borrow_pollable_t in{borrowed.data(), size_t(borrowed.size())};
        server_list_u32_t ready;
        wasi_io_poll_poll(&in, &ready);
        QList<qsizetype> due;
        for (size_t k = 0; k < ready.len; ++k)
            if (ready.ptr[k] < uint32_t(who.size()))
                due.append(who[ready.ptr[k]]);
        server_list_u32_free(&ready);
        // A pollable is a child of its future or stream: drop them first.
        for (auto p : owned)
            wasi_io_poll_pollable_drop_own(p);
        for (qsizetype i : due)
            step(jobs[i]);

        const uint64_t now = wasi_clocks_monotonic_clock_now();
        for (Job &j : jobs)
            if ((j.phase == Job::Waiting || j.phase == Job::Reading) && now >= j.deadline)
                fail(j, QStringLiteral("timed out"));
    }
    QList<Response> out;
    out.reserve(jobs.size());
    for (Job &j : jobs)
        out.append(std::move(j.res));
    return out;
}

Response fetch(const Outgoing &req) {
    return fetchAll({req}, 1).value(0);
}

void sleepMs(int ms) {
    auto p = wasi_clocks_monotonic_clock_subscribe_duration(uint64_t(ms) * MS);
    wasi_io_poll_method_pollable_block(wasi_io_poll_borrow_pollable(p));
    wasi_io_poll_pollable_drop_own(p);
}

QByteArray randomBytes(int n) {
    server_list_u8_t r;
    wasi_random_random_get_random_bytes(uint64_t(n), &r);
    QByteArray out = bytes(r.ptr, r.len);
    server_list_u8_free(&r);
    return out;
}

qint64 unixTime() {
    wasi_clocks_wall_clock_datetime_t t;
    wasi_clocks_wall_clock_now(&t);
    return qint64(t.seconds);
}

}  // namespace http

// --- incoming: the export -------------------------------------------------------

extern "C" int p256_generate_random(uint8_t *output, unsigned output_size) {
    server_list_u8_t r;
    wasi_random_random_get_random_bytes(output_size, &r);
    if (r.len != output_size) {
        server_list_u8_free(&r);
        return -1;
    }
    std::memcpy(output, r.ptr, output_size);
    server_list_u8_free(&r);
    return 0;
}

void exports_wasi_http_incoming_handler_handle(
    exports_wasi_http_incoming_handler_own_incoming_request_t request,
    exports_wasi_http_incoming_handler_own_response_outparam_t response_out) {
    qt2wasm::Call call;
    using namespace http;
    Request req;
    {
        auto b = wasi_http_types_borrow_incoming_request(request);
        wasi_http_types_method_t m;
        wasi_http_types_method_incoming_request_method(b, &m);
        req.method = methodName(m);
        wasi_http_types_method_free(&m);
        server_string_t s;
        if (wasi_http_types_method_incoming_request_path_with_query(b, &s)) {
            const QByteArray pq = bytes(s.ptr, s.len);
            server_string_free(&s);
            const qsizetype q = pq.indexOf('?');
            req.path = q < 0 ? pq : pq.left(q);
            req.query = q < 0 ? QByteArray() : pq.mid(q + 1);
        }
        if (req.path.isEmpty())
            req.path = "/";
        wasi_http_types_scheme_t sc;
        if (wasi_http_types_method_incoming_request_scheme(b, &sc)) {
            req.scheme = sc.tag == WASI_HTTP_TYPES_SCHEME_HTTPS ? "https"
                         : sc.tag == WASI_HTTP_TYPES_SCHEME_HTTP ? "http"
                                                                 : bytes(sc.val.other.ptr, sc.val.other.len);
            if (sc.tag == WASI_HTTP_TYPES_SCHEME_OTHER)
                server_string_free(&sc.val.other);
        }
        if (wasi_http_types_method_incoming_request_authority(b, &s)) {
            req.authority = bytes(s.ptr, s.len);
            server_string_free(&s);
        }
        req.headers = readFields(wasi_http_types_method_incoming_request_headers(b));
        if (req.authority.isEmpty())
            req.authority = req.headers.get("host");
        wasi_http_types_own_incoming_body_t body;
        if (wasi_http_types_method_incoming_request_consume(b, &body)) {
            wasi_http_types_own_input_stream_t in;
            if (wasi_http_types_method_incoming_body_stream(wasi_http_types_borrow_incoming_body(body), &in))
                req.body = readAllBlocking(in, MAX_INCOMING_BODY);
            wasi_http_types_incoming_body_drop_own(body);
        }
        wasi_http_types_incoming_request_drop_own(request);
    }

    Response res = handleRequest(req);

    if (req.method != "HEAD")
        res.headers.set("content-length", QByteArray::number(res.body.size()));
    auto out = wasi_http_types_constructor_outgoing_response(makeFields(res.headers));
    auto ob = wasi_http_types_borrow_outgoing_response(out);
    wasi_http_types_method_outgoing_response_set_status_code(ob, uint16_t(res.status));
    wasi_http_types_own_outgoing_body_t body;
    wasi_http_types_method_outgoing_response_body(ob, &body);
    wasi_http_types_result_own_outgoing_response_error_code_t result{};
    result.is_err = false;
    result.val.ok = out;
    wasi_http_types_static_response_outparam_set(response_out, &result);
    wasi_http_types_own_output_stream_t stream;
    if (req.method != "HEAD"
        && wasi_http_types_method_outgoing_body_write(wasi_http_types_borrow_outgoing_body(body), &stream))
        writeAll(stream, res.body);
    wasi_http_types_error_code_t ferr;
    if (!wasi_http_types_static_outgoing_body_finish(body, nullptr, &ferr))
        wasi_http_types_error_code_free(&ferr);
}
