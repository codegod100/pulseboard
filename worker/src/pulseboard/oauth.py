"""AT Protocol OAuth, just enough of it to learn who someone is.

The Nim reader shelled out to the official Node client for this. A Worker has
no Node, so this is the same flow written out: resolve the handle to a DID and
the DID to its PDS, find the PDS's authorization server, then a pushed
authorization request with PKCE and DPoP. On the callback the code is exchanged
for tokens, the `sub` is checked against the DID the handle resolved to, and
the tokens are revoked at once. Pulseboard keeps only the DID.

Signing is behind `crypto` (WebCrypto in the Worker, the `cryptography`
package in tests), so this module is plain Python:

    await crypto.generate_key() -> private JWK (dict, P-256)
    await crypto.sign(private_jwk, data: bytes) -> 64-byte r||s signature
"""

import base64
import hashlib
import json
import re
import secrets
import time
from urllib.parse import urlencode, urlsplit, urlunsplit

STATE_TTL = 10 * 60
SCOPE = "atproto"

_HANDLE = re.compile(
    r"^([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$"
)


class OAuthError(Exception):
    """Something the person can fix by trying again (or with another handle)."""


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def client_metadata(origin: str) -> dict:
    return {
        "client_id": f"{origin}/oauth-client-metadata.json",
        "client_name": "Pulseboard",
        "client_uri": origin,
        "redirect_uris": [f"{origin}/auth/callback"],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "scope": SCOPE,
        "token_endpoint_auth_method": "none",
        "application_type": "web",
        "dpop_bound_access_tokens": True,
    }


def public_jwk(private: dict) -> dict:
    return {k: private[k] for k in ("kty", "crv", "x", "y")}


async def _get_json(http, url: str) -> dict:
    res = await http.request("GET", url, headers={"Accept": "application/json"})
    if res.status != 200:
        raise OAuthError(f"{url} answered HTTP {res.status}")
    try:
        doc = json.loads(res.body)
    except ValueError:
        raise OAuthError(f"{url} did not return JSON") from None
    if not isinstance(doc, dict):
        raise OAuthError(f"{url} did not return a JSON object")
    return doc


# --- identity ----------------------------------------------------------------


def normalize_handle(raw: str) -> str:
    handle = raw.strip().lstrip("@").lower()
    if handle.startswith("at://"):
        handle = handle[5:]
    if not _HANDLE.match(handle) or len(handle) > 253:
        raise OAuthError("That does not look like a handle.")
    return handle


async def resolve_handle(http, handle: str) -> str:
    """DNS TXT `_atproto.<handle>` first (over DoH), then the well-known file."""
    try:
        res = await http.request(
            "GET",
            "https://cloudflare-dns.com/dns-query?" + urlencode({"name": f"_atproto.{handle}", "type": "TXT"}),
            headers={"Accept": "application/dns-json"},
        )
        if res.status == 200:
            for answer in json.loads(res.body).get("Answer") or []:
                data = str(answer.get("data", "")).strip('"')
                if data.startswith("did="):
                    return data[4:]
    except Exception:
        pass
    try:
        res = await http.request("GET", f"https://{handle}/.well-known/atproto-did")
        if res.status == 200:
            did = res.body.decode("utf-8", errors="replace").strip()
            if did.startswith("did:"):
                return did
    except Exception:
        pass
    raise OAuthError(f"Couldn't find an account for {handle}.")


async def resolve_did(http, did: str) -> dict:
    if did.startswith("did:plc:"):
        return await _get_json(http, f"https://plc.directory/{did}")
    if did.startswith("did:web:"):
        host = did[len("did:web:"):]
        if ":" in host or "/" in host:
            raise OAuthError("did:web with a path is not supported")
        return await _get_json(http, f"https://{host}/.well-known/did.json")
    raise OAuthError(f"Unsupported DID method: {did}")


def pds_endpoint(doc: dict) -> str:
    for svc in doc.get("service") or []:
        if str(svc.get("id", "")).endswith("#atproto_pds"):
            url = str(svc.get("serviceEndpoint", ""))
            if url.startswith("https://"):
                return url.rstrip("/")
    raise OAuthError("That account has no PDS.")


async def authorization_server(http, pds: str) -> dict:
    resource = await _get_json(http, f"{pds}/.well-known/oauth-protected-resource")
    servers = resource.get("authorization_servers") or []
    if not servers:
        raise OAuthError("That PDS names no authorization server.")
    issuer = str(servers[0]).rstrip("/")
    meta = await _get_json(http, f"{issuer}/.well-known/oauth-authorization-server")
    if str(meta.get("issuer", "")).rstrip("/") != issuer:
        raise OAuthError("Authorization server metadata does not match its issuer.")
    for key in ("authorization_endpoint", "token_endpoint", "pushed_authorization_request_endpoint"):
        if not str(meta.get(key, "")).startswith("https://"):
            raise OAuthError(f"Authorization server has no {key}.")
    return meta


# --- DPoP --------------------------------------------------------------------


async def dpop_proof(crypto, key: dict, method: str, url: str, nonce: str | None) -> str:
    parts = urlsplit(url)
    header = {"typ": "dpop+jwt", "alg": "ES256", "jwk": public_jwk(key)}
    payload = {
        "jti": secrets.token_urlsafe(16),
        "htm": method,
        "htu": urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")),
        "iat": int(time.time()),
    }
    if nonce:
        payload["nonce"] = nonce
    signing_input = (
        b64url(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + b64url(json.dumps(payload, separators=(",", ":")).encode())
    )
    sig = await crypto.sign(key, signing_input.encode())
    return signing_input + "." + b64url(sig)


async def dpop_post(http, crypto, key: dict, url: str, form: dict, nonce: str | None):
    """POST a form with a DPoP proof, retrying once with the server's nonce.
    Returns (response, latest nonce)."""
    for _ in range(2):
        proof = await dpop_proof(crypto, key, "POST", url, nonce)
        res = await http.request(
            "POST", url,
            headers={"Content-Type": "application/x-www-form-urlencoded",
                     "Accept": "application/json", "DPoP": proof},
            body=urlencode(form),
        )
        fresh = res.headers.get("dpop-nonce")
        if res.status in (400, 401) and fresh and fresh != nonce:
            try:
                err = json.loads(res.body).get("error")
            except ValueError:
                err = None
            if err == "use_dpop_nonce":
                nonce = fresh
                continue
        return res, fresh or nonce
    return res, nonce


# --- the flow ----------------------------------------------------------------


async def authorize(http, crypto, store, origin: str, raw_handle: str) -> str:
    """Start a sign-in and return the URL to send the browser to."""
    handle = normalize_handle(raw_handle)
    did = await resolve_handle(http, handle)
    doc = await resolve_did(http, did)
    if f"at://{handle}" not in [str(a).lower() for a in doc.get("alsoKnownAs") or []]:
        raise OAuthError(f"{handle} and its DID do not agree.")
    meta = await authorization_server(http, pds_endpoint(doc))

    key = await crypto.generate_key()
    verifier = secrets.token_urlsafe(48)
    state = secrets.token_urlsafe(24)
    client = client_metadata(origin)
    res, nonce = await dpop_post(
        http, crypto, key, meta["pushed_authorization_request_endpoint"],
        {
            "client_id": client["client_id"],
            "redirect_uri": client["redirect_uris"][0],
            "response_type": "code",
            "scope": SCOPE,
            "state": state,
            "code_challenge": b64url(hashlib.sha256(verifier.encode()).digest()),
            "code_challenge_method": "S256",
            "login_hint": handle,
        },
        None,
    )
    if res.status not in (200, 201):
        raise OAuthError(f"Pushed authorization request failed: HTTP {res.status} {res.body[:200]!r}")
    request_uri = json.loads(res.body).get("request_uri")
    if not request_uri:
        raise OAuthError("Authorization server returned no request_uri.")

    await store.put_oauth_state(state, json.dumps({
        "did": did,
        "issuer": meta["issuer"].rstrip("/"),
        "token_endpoint": meta["token_endpoint"],
        "revocation_endpoint": meta.get("revocation_endpoint", ""),
        "verifier": verifier,
        "key": key,
        "nonce": nonce,
    }), int(time.time()) + STATE_TTL)
    return meta["authorization_endpoint"] + "?" + urlencode(
        {"client_id": client["client_id"], "request_uri": request_uri})


async def callback(http, crypto, store, origin: str, params: dict) -> str:
    """Finish a sign-in and return the verified DID."""
    state = params.get("state", "")
    raw = await store.take_oauth_state(state, int(time.time())) if state else None
    if raw is None:
        raise OAuthError("That sign-in expired or was already used.")
    if params.get("error"):
        raise OAuthError(params.get("error_description") or params["error"])
    data = json.loads(raw)
    if params.get("iss", "").rstrip("/") != data["issuer"]:
        raise OAuthError("The response came from the wrong authorization server.")
    code = params.get("code", "")
    if not code:
        raise OAuthError("No authorization code in the response.")

    client = client_metadata(origin)
    key = data["key"]
    res, nonce = await dpop_post(
        http, crypto, key, data["token_endpoint"],
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": client["redirect_uris"][0],
            "code_verifier": data["verifier"],
            "client_id": client["client_id"],
        },
        data.get("nonce"),
    )
    if res.status != 200:
        raise OAuthError(f"Token request failed: HTTP {res.status}")
    tokens = json.loads(res.body)
    if tokens.get("sub") != data["did"]:
        raise OAuthError("The account that signed in is not the one asked for.")
    if SCOPE not in str(tokens.get("scope", "")).split():
        raise OAuthError("The authorization server did not grant the atproto scope.")

    # Pulseboard needs a verified identity, not ongoing access to the PDS.
    if data.get("revocation_endpoint"):
        for kind in ("refresh_token", "access_token"):
            if tokens.get(kind):
                try:
                    _, nonce = await dpop_post(
                        http, crypto, key, data["revocation_endpoint"],
                        {"token": tokens[kind], "token_type_hint": kind,
                         "client_id": client["client_id"]},
                        nonce,
                    )
                except Exception:
                    pass
    return data["did"]
