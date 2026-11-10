#include "oauth.h"

#include "p256-m.h"
#include "wasihttp.h"

#include <QCryptographicHash>
#include <QJsonArray>
#include <QJsonDocument>
#include <QRegularExpression>
#include <QUrl>

namespace oauth {

namespace {

constexpr qint64 STATE_TTL = 10 * 60;
const QString SCOPE = QStringLiteral("atproto");

Outcome failure(const QString &why, bool userError = true) {
    Outcome o;
    o.error = why;
    o.userError = userError;
    return o;
}

QString value(const util::Pairs &params, const char *key) {
    for (const auto &[k, v] : params)
        if (k == QLatin1StringView(key))
            return v;
    return {};
}

// --- keys --------------------------------------------------------------------

QJsonObject generateKey() {
    uint8_t priv[32], pub[64];
    if (p256_gen_keypair(priv, pub) != P256_SUCCESS)
        return {};
    auto enc = [](const uint8_t *p) {
        return util::b64url(QByteArray(reinterpret_cast<const char *>(p), 32));
    };
    return {{"kty", "EC"}, {"crv", "P-256"}, {"x", enc(pub)}, {"y", enc(pub + 32)}, {"d", enc(priv)}};
}

QJsonObject publicJwk(const QJsonObject &key) {
    return {{"kty", key["kty"]}, {"crv", key["crv"]}, {"x", key["x"]}, {"y", key["y"]}};
}

QByteArray sign(const QJsonObject &key, const QByteArray &data) {
    const QByteArray d = util::b64urlDecode(key["d"].toString());
    const QByteArray hash = QCryptographicHash::hash(data, QCryptographicHash::Sha256);
    uint8_t sig[64];
    if (d.size() != 32
        || p256_ecdsa_sign(sig, reinterpret_cast<const uint8_t *>(d.constData()),
                           reinterpret_cast<const uint8_t *>(hash.constData()), size_t(hash.size()))
               != P256_SUCCESS)
        return {};
    return QByteArray(reinterpret_cast<const char *>(sig), 64);
}

QByteArray compact(const QJsonObject &o) {
    return QJsonDocument(o).toJson(QJsonDocument::Compact);
}

// --- HTTP helpers --------------------------------------------------------------

struct Got {
    bool ok = false;
    bool userError = true;
    QString error;
    QJsonObject doc;
};

Got getJson(const QString &url) {
    http::Outgoing req;
    req.url = url;
    req.headers.set("accept", "application/json");
    const http::Response res = http::fetch(req);
    Got g;
    if (!res.error.isEmpty()) {
        g.userError = false;
        g.error = QStringLiteral("%1: %2").arg(url, res.error);
        return g;
    }
    if (res.status != 200) {
        g.error = QStringLiteral("%1 answered HTTP %2").arg(url).arg(res.status);
        return g;
    }
    QJsonParseError perr;
    const QJsonDocument doc = QJsonDocument::fromJson(res.body, &perr);
    if (perr.error != QJsonParseError::NoError) {
        g.error = QStringLiteral("%1 did not return JSON").arg(url);
        return g;
    }
    if (!doc.isObject()) {
        g.error = QStringLiteral("%1 did not return a JSON object").arg(url);
        return g;
    }
    g.ok = true;
    g.doc = doc.object();
    return g;
}

QString str(const QJsonValue &v) {
    if (v.isString())
        return v.toString();
    if (v.isDouble())
        return v.toVariant().toString();
    return {};
}

// --- identity ------------------------------------------------------------------

bool normalizeHandle(const QString &raw, QString *handle) {
    static const QRegularExpression valid(QStringLiteral(
        "^([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\\.)+[a-zA-Z]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$"));
    QString h = raw.trimmed();
    while (h.startsWith(u'@'))
        h.remove(0, 1);
    h = h.toLower();
    if (h.startsWith(u"at://"))
        h = h.mid(5);
    if (!valid.match(h).hasMatch() || h.size() > 253)
        return false;
    *handle = h;
    return true;
}

// DNS TXT `_atproto.<handle>` first (over DoH), then the well-known file.
QString resolveHandle(const QString &handle) {
    http::Outgoing dns;
    dns.url = QStringLiteral("https://cloudflare-dns.com/dns-query?")
              + QString::fromLatin1(util::encodeQuery({{"name", "_atproto." + handle}, {"type", "TXT"}}));
    dns.headers.set("accept", "application/dns-json");
    const http::Response res = http::fetch(dns);
    if (res.error.isEmpty() && res.status == 200) {
        for (const QJsonValue &a : QJsonDocument::fromJson(res.body).object().value("Answer").toArray()) {
            QString data = str(a.toObject().value("data"));
            while (data.startsWith(u'"'))
                data.remove(0, 1);
            while (data.endsWith(u'"'))
                data.chop(1);
            if (data.startsWith(u"did="))
                return data.mid(4);
        }
    }
    http::Outgoing wk;
    wk.url = QStringLiteral("https://%1/.well-known/atproto-did").arg(handle);
    const http::Response w = http::fetch(wk);
    if (w.error.isEmpty() && w.status == 200) {
        const QString did = QString::fromUtf8(w.body).trimmed();
        if (did.startsWith(u"did:"))
            return did;
    }
    return {};
}

Got resolveDid(const QString &did) {
    if (did.startsWith(u"did:plc:"))
        return getJson(QStringLiteral("https://plc.directory/") + did);
    if (did.startsWith(u"did:web:")) {
        const QString host = did.mid(8);
        if (host.contains(u':') || host.contains(u'/')) {
            Got g;
            g.error = QStringLiteral("did:web with a path is not supported");
            return g;
        }
        return getJson(QStringLiteral("https://%1/.well-known/did.json").arg(host));
    }
    Got g;
    g.error = QStringLiteral("Unsupported DID method: ") + did;
    return g;
}

QString pdsEndpoint(const QJsonObject &doc) {
    for (const QJsonValue &v : doc.value("service").toArray()) {
        const QJsonObject svc = v.toObject();
        if (str(svc.value("id")).endsWith(u"#atproto_pds")) {
            QString url = str(svc.value("serviceEndpoint"));
            if (url.startsWith(u"https://")) {
                while (url.endsWith(u'/'))
                    url.chop(1);
                return url;
            }
        }
    }
    return {};
}

QString stripSlash(QString s) {
    while (s.endsWith(u'/'))
        s.chop(1);
    return s;
}

Got authorizationServer(const QString &pds) {
    Got resource = getJson(pds + QStringLiteral("/.well-known/oauth-protected-resource"));
    if (!resource.ok)
        return resource;
    const QJsonArray servers = resource.doc.value("authorization_servers").toArray();
    if (servers.isEmpty()) {
        Got g;
        g.error = QStringLiteral("That PDS names no authorization server.");
        return g;
    }
    const QString issuer = stripSlash(str(servers.first()));
    Got meta = getJson(issuer + QStringLiteral("/.well-known/oauth-authorization-server"));
    if (!meta.ok)
        return meta;
    if (stripSlash(str(meta.doc.value("issuer"))) != issuer) {
        Got g;
        g.error = QStringLiteral("Authorization server metadata does not match its issuer.");
        return g;
    }
    for (const char *key : {"authorization_endpoint", "token_endpoint", "pushed_authorization_request_endpoint"}) {
        if (!str(meta.doc.value(QLatin1StringView(key))).startsWith(u"https://")) {
            Got g;
            g.error = QStringLiteral("Authorization server has no %1.").arg(QLatin1StringView(key));
            return g;
        }
    }
    return meta;
}

// --- DPoP ------------------------------------------------------------------------

QString dpopProof(const QJsonObject &key, const QString &method, const QString &url, const QString &nonce) {
    const QUrl u(url);
    const QString htu = u.toString(QUrl::RemoveQuery | QUrl::RemoveFragment | QUrl::FullyEncoded);
    const QJsonObject header{{"typ", "dpop+jwt"}, {"alg", "ES256"}, {"jwk", publicJwk(key)}};
    QJsonObject payload{{"jti", util::token(16)}, {"htm", method}, {"htu", htu},
                        {"iat", http::unixTime()}};
    if (!nonce.isEmpty())
        payload["nonce"] = nonce;
    const QString input = util::b64url(compact(header)) + u'.' + util::b64url(compact(payload));
    return input + u'.' + util::b64url(sign(key, input.toUtf8()));
}

struct Posted {
    http::Response res;
    QString nonce;
};

// POST a form with a DPoP proof, retrying once with the server's nonce.
Posted dpopPost(const QJsonObject &key, const QString &url, const util::Pairs &form, QString nonce) {
    http::Response res;
    for (int attempt = 0; attempt < 2; ++attempt) {
        http::Outgoing req;
        req.method = "POST";
        req.url = url;
        req.followRedirects = false;
        req.headers.set("content-type", "application/x-www-form-urlencoded");
        req.headers.set("accept", "application/json");
        req.headers.set("dpop", dpopProof(key, QStringLiteral("POST"), url, nonce).toUtf8());
        req.body = util::encodeQuery(form);
        res = http::fetch(req);
        const QString fresh = QString::fromUtf8(res.headers.get("dpop-nonce"));
        if ((res.status == 400 || res.status == 401) && !fresh.isEmpty() && fresh != nonce) {
            const QString err = QJsonDocument::fromJson(res.body).object().value("error").toString();
            if (err == u"use_dpop_nonce") {
                nonce = fresh;
                continue;
            }
        }
        return {res, fresh.isEmpty() ? nonce : fresh};
    }
    return {res, nonce};
}

}  // namespace

QJsonObject clientMetadata(const QString &origin) {
    return {
        {"client_id", origin + QStringLiteral("/oauth-client-metadata.json")},
        {"client_name", "Pulseboard"},
        {"client_uri", origin},
        {"redirect_uris", QJsonArray{origin + QStringLiteral("/auth/callback")}},
        {"grant_types", QJsonArray{"authorization_code", "refresh_token"}},
        {"response_types", QJsonArray{"code"}},
        {"scope", SCOPE},
        {"token_endpoint_auth_method", "none"},
        {"application_type", "web"},
        {"dpop_bound_access_tokens", true},
    };
}

Outcome authorize(Store &store, const QString &origin, const QString &rawHandle) {
    QString handle;
    if (!normalizeHandle(rawHandle, &handle))
        return failure(QStringLiteral("That does not look like a handle."));
    const QString did = resolveHandle(handle);
    if (did.isEmpty())
        return failure(QStringLiteral("Couldn't find an account for %1.").arg(handle));
    const Got doc = resolveDid(did);
    if (!doc.ok)
        return failure(doc.error, doc.userError);
    bool known = false;
    for (const QJsonValue &a : doc.doc.value("alsoKnownAs").toArray())
        known |= str(a).toLower() == QStringLiteral("at://") + handle;
    if (!known)
        return failure(QStringLiteral("%1 and its DID do not agree.").arg(handle));
    const QString pds = pdsEndpoint(doc.doc);
    if (pds.isEmpty())
        return failure(QStringLiteral("That account has no PDS."));
    const Got meta = authorizationServer(pds);
    if (!meta.ok)
        return failure(meta.error, meta.userError);

    const QJsonObject key = generateKey();
    if (key.isEmpty())
        return failure(QStringLiteral("no randomness for a key"), false);
    const QString verifier = util::token(48);
    const QString state = util::token(24);
    const QJsonObject client = clientMetadata(origin);
    const QString clientId = client["client_id"].toString();
    const QString redirect = client["redirect_uris"].toArray().first().toString();
    const QString challenge = util::b64url(QCryptographicHash::hash(verifier.toUtf8(), QCryptographicHash::Sha256));
    const Posted par = dpopPost(key, str(meta.doc["pushed_authorization_request_endpoint"]),
                                {{"client_id", clientId},
                                 {"redirect_uri", redirect},
                                 {"response_type", "code"},
                                 {"scope", SCOPE},
                                 {"state", state},
                                 {"code_challenge", challenge},
                                 {"code_challenge_method", "S256"},
                                 {"login_hint", handle}},
                                {});
    if (!par.res.error.isEmpty())
        return failure(par.res.error, false);
    if (par.res.status != 200 && par.res.status != 201)
        return failure(QStringLiteral("Pushed authorization request failed: HTTP %1 %2")
                           .arg(par.res.status).arg(QString::fromUtf8(par.res.body.left(200))));
    const QString requestUri = str(QJsonDocument::fromJson(par.res.body).object().value("request_uri"));
    if (requestUri.isEmpty())
        return failure(QStringLiteral("Authorization server returned no request_uri."));

    QJsonObject saved{
        {"did", did},
        {"issuer", stripSlash(str(meta.doc["issuer"]))},
        {"token_endpoint", str(meta.doc["token_endpoint"])},
        {"revocation_endpoint", str(meta.doc["revocation_endpoint"])},
        {"verifier", verifier},
        {"key", key},
        {"nonce", par.nonce.isEmpty() ? QJsonValue() : QJsonValue(par.nonce)},
    };
    store.putOAuthState(state, QString::fromUtf8(compact(saved)), http::unixTime() + STATE_TTL);
    Outcome o;
    o.ok = true;
    o.value = str(meta.doc["authorization_endpoint"]) + u'?'
              + QString::fromLatin1(util::encodeQuery({{"client_id", clientId}, {"request_uri", requestUri}}));
    return o;
}

Outcome callback(Store &store, const QString &origin, const util::Pairs &params) {
    const QString state = value(params, "state");
    const std::optional<QString> raw = state.isEmpty() ? std::nullopt
                                                       : store.takeOAuthState(state, http::unixTime());
    if (!raw)
        return failure(QStringLiteral("That sign-in expired or was already used."));
    if (!value(params, "error").isEmpty()) {
        const QString desc = value(params, "error_description");
        return failure(desc.isEmpty() ? value(params, "error") : desc);
    }
    const QJsonObject data = QJsonDocument::fromJson(raw->toUtf8()).object();
    if (stripSlash(value(params, "iss")) != data["issuer"].toString())
        return failure(QStringLiteral("The response came from the wrong authorization server."));
    const QString code = value(params, "code");
    if (code.isEmpty())
        return failure(QStringLiteral("No authorization code in the response."));

    const QJsonObject client = clientMetadata(origin);
    const QString clientId = client["client_id"].toString();
    const QJsonObject key = data["key"].toObject();
    const Posted tok = dpopPost(key, data["token_endpoint"].toString(),
                                {{"grant_type", "authorization_code"},
                                 {"code", code},
                                 {"redirect_uri", client["redirect_uris"].toArray().first().toString()},
                                 {"code_verifier", data["verifier"].toString()},
                                 {"client_id", clientId}},
                                data["nonce"].toString());
    if (!tok.res.error.isEmpty())
        return failure(tok.res.error, false);
    if (tok.res.status != 200)
        return failure(QStringLiteral("Token request failed: HTTP %1").arg(tok.res.status));
    const QJsonObject tokens = QJsonDocument::fromJson(tok.res.body).object();
    const QString did = data["did"].toString();
    if (str(tokens["sub"]) != did)
        return failure(QStringLiteral("The account that signed in is not the one asked for."));
    if (!str(tokens["scope"]).split(u' ', Qt::SkipEmptyParts).contains(SCOPE))
        return failure(QStringLiteral("The authorization server did not grant the atproto scope."));

    // Pulseboard needs a verified identity, not ongoing access to the PDS.
    const QString revocation = data["revocation_endpoint"].toString();
    if (!revocation.isEmpty()) {
        QString nonce = tok.nonce;
        for (const char *kind : {"refresh_token", "access_token"}) {
            const QString t = str(tokens[QLatin1StringView(kind)]);
            if (t.isEmpty())
                continue;
            nonce = dpopPost(key, revocation,
                             {{"token", t}, {"token_type_hint", QString::fromLatin1(kind)}, {"client_id", clientId}},
                             nonce)
                        .nonce;
        }
    }
    Outcome o;
    o.ok = true;
    o.value = did;
    return o;
}

}  // namespace oauth
