// AT Protocol OAuth, just enough of it to learn who someone is.
//
// Resolve the handle to a DID and the DID to its PDS, find the PDS's
// authorization server, then a pushed authorization request with PKCE and
// DPoP (ES256, signed with the vendored p256-m). On the callback the code is
// exchanged for tokens, the `sub` is checked against the DID the handle
// resolved to, and the tokens are revoked at once. Pulseboard keeps only the
// DID. Ported from the Python server's oauth.py.
#pragma once

#include "store.h"
#include "util.h"

#include <QJsonObject>
#include <QString>

namespace oauth {

struct Outcome {
    bool ok = false;
    // A problem the person can fix by trying again (or with another handle).
    // When false, something broke on the way (a server, the network).
    bool userError = true;
    QString error;
    QString value;  // authorize: where to send the browser; callback: the DID
};

QJsonObject clientMetadata(const QString &origin);

Outcome authorize(Store &store, const QString &origin, const QString &rawHandle);
Outcome callback(Store &store, const QString &origin, const util::Pairs &params);

}  // namespace oauth
