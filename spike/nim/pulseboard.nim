## A small RSS reader.
##
##   nim c -r -d:ssl pulseboard.nim
##   PULSEBOARD_DB=~/.local/share/pulseboard/db PULSEBOARD_PORT=8080 ./pulseboard
##
## Authentication is AT Protocol OAuth. The official Node client performs
## discovery, PKCE, PAR and DPoP; this server keeps only the verified DID in an
## opaque browser session and immediately revokes the OAuth credential.
##
## PULSEBOARD_WEB must point at the Flutter web build. The reader refuses to start
## without it so deployments cannot silently serve a different client.
##
## The pieces underneath -- fetching, parsing, storage, search, full-text
## extraction -- are the same modules the larger port built and tested.

import std/[asyncdispatch, asynchttpserver, base64, httpclient, json, options,
            os, osproc, strformat, strutils, sysrand, threadpool, times, uri]
import reader/[articlestore, feedfetcher, feedparser, feedstore, pulseboarddb,
                opml, scraper, sqlite]

const
  DefaultPort = 8080
  ## A session ends after this long without use. Every authenticated request
  ## pushes the expiry forward, so a reader who opens the app regularly is
  ## never sent back to sign in.
  SessionIdleLimit = 30 * 24 * 60 * 60
  ## Renewal writes the users database, which deploy snapshots on every
  ## change, so it happens at most this often per session.
  SessionRenewEvery = 24 * 60 * 60
  ## The cookie only carries the token; the server row decides whether it is
  ## still good. It is kept far longer than the idle limit so a sliding
  ## session is never cut short by the browser dropping the cookie. Browsers
  ## cap Max-Age at 400 days.
  SessionCookieMaxAge = 400 * 24 * 60 * 60

type Reader = ref object
  db: PulseboardDb
  webRoot: string  ## required Flutter web bundle
  oauthHelper: string
  oauthMetadata: JsonNode

proc cookieValue(header, name: string): string =
  for part in header.split(';'):
    let kv = part.strip()
    let i = kv.find('=')
    if i > 0 and kv[0 ..< i] == name: return kv[i + 1 .. ^1]
  ""

proc runOauth(helper, command, payload: string): tuple[output: string,
                                                        exitCode: int] =
  ## The helper makes network requests during authorize/callback. In particular,
  ## an authorization server fetches our public client metadata while the
  ## authorize command is in flight. Running it on the HTTP event-loop thread
  ## deadlocks that fetch against this same server.
  let invocation = "node " & quoteShell(helper) & " " & quoteShell(command)
  let res = execCmdEx(invocation, input = payload)
  (res.output, res.exitCode)

proc oauth(r: Reader, command: string, payload: JsonNode): Future[JsonNode] {.async.} =
  let work = spawn runOauth(r.oauthHelper, command, $payload)
  while not work.isReady:
    await sleepAsync(5)
  let res = ^work
  if res.exitCode != 0:
    raise newException(IOError, res.output.strip)
  return parseJson(res.output)

proc newSessionToken(): string =
  var bytes = newSeq[byte](32)
  if not urandom(bytes):
    raise newException(IOError, "system randomness unavailable")
  encode(bytes).replace("+", "-").replace("/", "_").strip(chars = {'='})

proc createSession(r: Reader, did: string): string =
  result = newSessionToken()
  r.db.db.run("INSERT OR IGNORE INTO users (did) VALUES (?)", p(did))
  # Adopt data from versions that used a single synthetic user. This runs only
  # while that legacy row exists, so the first verified account becomes its
  # owner and later accounts remain isolated.
  if r.db.db.queryText("SELECT did FROM users WHERE did = 'local'").isSome:
    r.db.db.run("UPDATE OR IGNORE articles.subscriptions SET user_did = ? WHERE user_did = 'local'", p(did))
    r.db.db.run("DELETE FROM articles.subscriptions WHERE user_did = 'local'")
    r.db.db.run("UPDATE OR IGNORE articles.read_state SET user_did = ? WHERE user_did = 'local'", p(did))
    r.db.db.run("DELETE FROM articles.read_state WHERE user_did = 'local'")
    r.db.db.run("UPDATE OR IGNORE articles.read_state_history SET user_did = ? WHERE user_did = 'local'", p(did))
    r.db.db.run("DELETE FROM articles.read_state_history WHERE user_did = 'local'")
    r.db.db.run("DELETE FROM users WHERE did = 'local'")
  r.db.db.run(
    "INSERT INTO web_sessions (token, user_did, expires_at) VALUES (?, ?, ?)",
    p(result), p(did), p((getTime().toUnix + SessionIdleLimit).int64))

proc sessionUser(r: Reader, req: Request): string =
  let token = cookieValue(req.headers.getOrDefault("Cookie").string,
                          "pulseboard_session")
  if token.len == 0: return ""
  let now = getTime().toUnix
  result = r.db.db.queryText(
    "SELECT user_did FROM web_sessions WHERE token = ? AND expires_at > ?",
    p(token), p(now)).get("")
  if result.len > 0:
    r.db.db.run(
      "UPDATE web_sessions SET expires_at = ? WHERE token = ? AND expires_at < ?",
      p((now + SessionIdleLimit).int64), p(token),
      p((now + SessionIdleLimit - SessionRenewEvery).int64))

proc clearSession(r: Reader, req: Request) =
  let token = cookieValue(req.headers.getOrDefault("Cookie").string,
                          "pulseboard_session")
  if token.len > 0:
    r.db.db.run("DELETE FROM web_sessions WHERE token = ?", p(token))

proc jsonResponse(req: Request, code: HttpCode, node: JsonNode) {.async.} =
  await req.respond(code, $node, newHttpHeaders({
    "Content-Type": "application/json",
    # The reader may be opened from a local web page or a native client.
    "Access-Control-Allow-Origin": "*",
  }))

proc fail(req: Request, code: HttpCode, msg: string) {.async.} =
  await jsonResponse(req, code, %*{"error": msg})

proc escapeHtml(s: string): string =
  for c in s:
    case c
    of '&': result.add "&amp;"
    of '<': result.add "&lt;"
    of '>': result.add "&gt;"
    of '"': result.add "&quot;"
    of '\'': result.add "&#39;"
    else: result.add c

const AuthPageStyle = """
:root{--bg:#fafaf7;--fg:#0a0a0a;--surface:#f0efe9;--muted:#6b6b6b;
--accent:#00754a;--accent-ink:#ecfff4;--danger:#c82014;color-scheme:light dark}
@media (prefers-color-scheme:dark){:root{--bg:#0a0a0a;--fg:#f5f5ef;
--surface:#161616;--muted:#9a9a9a;--danger:#ff5a4d}}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:grid;place-items:center;padding:16px;
background:var(--bg);color:var(--fg);
font:15px/1.5 "JetBrains Mono","IBM Plex Mono",ui-monospace,monospace}
main{width:100%;max-width:380px;background:var(--surface);
border:2px solid var(--fg);box-shadow:6px 6px 0 var(--fg);padding:28px 24px}
.brand{display:flex;align-items:center;gap:10px;margin:0 0 20px;
font-size:20px;font-weight:700;letter-spacing:-.02em}
.brand img{width:28px;height:28px;border:2px solid var(--fg)}
p{margin:0 0 16px;color:var(--muted)}
label{display:block;font-size:12px;font-weight:700;text-transform:uppercase;
letter-spacing:.06em;margin-bottom:6px}
input{display:block;width:100%;font:inherit;padding:10px 12px;margin-bottom:16px;
background:var(--bg);color:var(--fg);border:2px solid var(--fg);border-radius:0}
input:focus{outline:2px solid var(--accent);outline-offset:2px}
button,.button{display:block;width:100%;font:inherit;font-weight:700;
text-align:center;text-decoration:none;padding:10px 12px;cursor:pointer;
background:var(--accent);color:var(--accent-ink);border:2px solid var(--fg);
box-shadow:3px 3px 0 var(--fg)}
button:active,.button:active{transform:translate(3px,3px);box-shadow:none}
.error{color:var(--danger);border-left:3px solid var(--danger);padding-left:10px}
small{display:block;margin-top:16px;color:var(--muted);font-size:12px}
"""

proc authPage(req: Request, code: HttpCode, title, body: string) {.async.} =
  ## Every page the reader renders itself sits in front of a login, so they
  ## share one card that looks like the client they lead into.
  await req.respond(code, "<!doctype html>\n<html lang=\"en\"><head>" &
    "<meta charset=\"utf-8\">" &
    "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">" &
    "<title>" & escapeHtml(title) & "</title>" &
    "<link rel=\"icon\" href=\"/favicon.png\">" &
    "<style>" & AuthPageStyle & "</style></head><body><main>" &
    "<h1 class=\"brand\"><img src=\"/favicon.png\" alt=\"\">Pulseboard</h1>" &
    body & "</main></body></html>",
    newHttpHeaders({"Content-Type": "text/html; charset=utf-8"}))

proc loginPage(req: Request, code = Http200, identity = "",
               error = "") {.async.} =
  var body = ""
  if error.len > 0:
    body.add "<p class=\"error\" role=\"alert\">" & escapeHtml(error) & "</p>"
  else:
    body.add "<p>Sign in with your Bluesky or other AT Protocol account.</p>"
  body.add """<form action="/auth/authorize" method="get">
<label for="identity">Handle</label>
<input id="identity" name="identity" required autofocus autocapitalize="none"
spellcheck="false" placeholder="you.bsky.social" autocomplete="username" value="""" &
    escapeHtml(identity) & """">
<button type="submit">Continue</button></form>
<small>Only your DID is kept. Access to your account is revoked right after
sign-in.</small>"""
  await authPage(req, code, "Sign in to Pulseboard", body)

proc contentTypeFor(path: string): string =
  ## Enough types for a Flutter web build. A wrong type here is not cosmetic:
  ## a browser will refuse to execute JavaScript served as text/plain.
  let ext = path.splitFile.ext.toLowerAscii
  case ext
  of ".html": "text/html; charset=utf-8"
  of ".js", ".mjs": "text/javascript; charset=utf-8"
  of ".css": "text/css; charset=utf-8"
  of ".json": "application/json"
  of ".wasm": "application/wasm"
  of ".png": "image/png"
  of ".jpg", ".jpeg": "image/jpeg"
  of ".svg": "image/svg+xml"
  of ".ico": "image/x-icon"
  of ".woff2": "font/woff2"
  of ".woff": "font/woff"
  of ".ttf": "font/ttf"
  of ".otf": "font/otf"
  of ".map": "application/json"
  else: "application/octet-stream"

proc serveStatic(r: Reader, req: Request, rel: string): Future[bool] {.async.} =
  ## Serve `rel` from the web root, if it is there. Returns false when it is
  ## not, so the caller can fall through.
  if r.webRoot.len == 0: return false
  # Resolve and confirm the result is still inside the root: "../" in a
  # request path is how a static file server turns into a file server for
  # the whole disk.
  let full = absolutePath(r.webRoot / rel)
  let root = absolutePath(r.webRoot)
  if not full.startsWith(root) or not fileExists(full): return false
  var headers = newHttpHeaders({"Content-Type": contentTypeFor(full)})
  # Flutter's bootstrap, manifest and Pulseboard's service worker keep stable
  # filenames.
  # Revalidate them so a deploy cannot leave an installed app on yesterday's
  # shell. Other assets get a short browser cache; the persistent service
  # worker is rechecked by the browser and updated on the next deploy.
  let ext = full.splitFile.ext.toLowerAscii
  if ext in [".html", ".js", ".mjs", ".json"]:
    headers["Cache-Control"] = "no-cache"
  else:
    headers["Cache-Control"] = "public, max-age=86400"
  await req.respond(Http200, readFile(full), headers)
  return true

proc isPublicWebAsset(path: string): bool =
  ## The application data stays behind the session, but the browser must be
  ## able to install and update the PWA even after that session expires.
  if path in ["manifest.json", "pulseboard_service_worker.js",
              "flutter_bootstrap.js", "flutter.js", "main.dart.js",
              "version.json",
              "favicon.png"]:
    return true
  for prefix in ["assets/", "canvaskit/", "icons/"]:
    if path.startsWith(prefix): return true
  false

proc serveApp(r: Reader, req: Request) {.async.} =
  if not await serveStatic(r, req, "index.html"):
    await fail(req, Http500, "Flutter web bundle is unavailable")

proc toJson(a: Article): JsonNode =
  %*{
    "id": a.id,
    "feed_url": a.feedUrl,
    "feed_title": a.feedTitle,
    "title": a.title,
    "url": a.url,
    "author": a.author,
    "summary": a.summary,
    # Sanitised on the way out, whichever source it came from. Scraped text
    # has already been through the whitelist, but feed content has not, and
    # it is markup from a stranger's server heading for a browser.
    "content": sanitizeFragment(
      if a.fullContent.len > 0: a.fullContent else: a.content),
    # Explicitly ISO 8601. Nim's `$` on a DateTime dumps the struct's fields,
    # which reaches the browser as "Invalid Date".
    "published": (if a.published.isSome:
                    a.published.get.format("yyyy-MM-dd'T'HH:mm:ss'Z'")
                  else: ""),
    "is_read": a.isRead,
  }

proc toJson(s: Subscription, unread: int): JsonNode =
  %*{
    "feed_url": s.feedUrl,
    "title": s.feedTitle,
    "category": s.category,
    "unread": unread,
    "favicon_url": s.faviconUrl,
  }

# --- feed refresh ----------------------------------------------------------

proc refreshFeed(r: Reader, userDid, feedUrl: string): tuple[added: int, err: string] =
  ## Fetch one feed and store what came back.
  ##
  ## A failure is recorded rather than raised: one unreachable feed should
  ## not stop a refresh of the others, and the error belongs on the feed so
  ## the reader can see which one is broken.
  try:
    let parsed = fetchFeed(feedUrl)
    var batch: seq[NewArticle]
    for a in parsed.articles:
      batch.add NewArticle(
        feedUrl: feedUrl, guid: a.guid, title: a.title, url: a.url,
        author: a.author, summary: a.summary, content: a.content,
        published: a.published, updated: a.updated)
    let before = r.db.getUnreadCount(userDid, feedUrl, "")
    r.db.batchUpsertArticles(batch)
    r.db.upsertFeed(Feed(feedUrl: feedUrl, title: parsed.feed.title,
                         siteUrl: parsed.feed.siteUrl,
                         description: parsed.feed.description,
                         feedType: $parsed.feed.kind,
                         faviconUrl: parsed.feed.faviconUrl))
    r.db.markFeedFetched(feedUrl)
    (r.db.getUnreadCount(userDid, feedUrl, "") - before, "")
  except CatchableError as e:
    r.db.markFeedFetchError(feedUrl, e.msg)
    (0, e.msg)

# --- routes ----------------------------------------------------------------

proc handle(r: Reader, req: Request) {.async.} =
  let path = req.url.path.strip(chars = {'/'})
  let segs = path.split('/')
  # Query string and form body both, the way Go's FormValue does: a caller
  # should not have to care which one a given route wanted.
  var q: seq[(string, string)] = @[]
  for kv in decodeQuery(req.url.query): q.add kv
  if req.body.len > 0:
    for kv in decodeQuery(req.body): q.add kv
  proc param(name: string, fallback = ""): string =
    for (k, v) in q:
      if k == name: return v
    fallback
  proc intParam(name: string, fallback: int): int =
    let raw = param(name)
    if raw.len == 0: fallback
    else:
      try: parseInt(raw) except ValueError: fallback

  # OAuth endpoints are the only public application surface (besides health).
  if req.reqMethod == HttpGet and path == "oauth-client-metadata.json":
    # The authorization server fetches this while the authorize helper is
    # waiting for its PAR response. Serving it through the same bounded worker
    # pool would deadlock when the pool has only one thread (as on Modal's
    # smallest containers), so cache it before the HTTP server starts.
    await jsonResponse(req, Http200, r.oauthMetadata)
    return

  if req.reqMethod == HttpGet and path == "auth/login":
    await loginPage(req)
    return

  if req.reqMethod == HttpGet and path == "auth/authorize":
    let identity = param("identity").strip
    if identity.len == 0 or identity.startsWith("did:"):
      await loginPage(req, Http400, identity,
                      "Enter a handle, like you.bsky.social.")
      return
    try:
      let result = await r.oauth("authorize", %*{"identity": identity})
      await req.respond(Http303, "", newHttpHeaders({
        "Location": result{"url"}.getStr,
      }))
    except CatchableError as e:
      # The helper's output is a Node error, and in debug builds the message
      # also carries an async traceback: log it, show the reader a sentence.
      echo "auth/authorize failed for ", identity, ": ", e.msg
      await loginPage(req, Http502, identity,
                      "Couldn't start sign-in for that handle. Check it and try again.")
    return

  if req.reqMethod == HttpGet and path == "auth/callback":
    var params = newJArray()
    for (key, value) in q: params.add %*[key, value]
    try:
      let callbackResult = await r.oauth("callback", %*{"params": params})
      if callbackResult.hasKey("error"):
        await authPage(req, Http401, "Sign in again",
          "<p>That sign-in expired or was cancelled.</p>" &
          "<a class=\"button\" href=\"/auth/login\">Sign in again</a>")
        return
      let did = callbackResult{"did"}.getStr
      if not did.startsWith("did:"):
        raise newException(ValueError, "login did not return a DID")
      let token = r.createSession(did)
      await req.respond(Http303, "", newHttpHeaders({
        "Location": "/",
        "Set-Cookie": "pulseboard_session=" & token &
          "; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=" & $SessionCookieMaxAge,
      }))
    except CatchableError as e:
      echo "auth/callback failed: ", e.msg
      await loginPage(req, Http401, error = "Sign-in failed. Please try again.")
    return

  if req.reqMethod == HttpGet and path == "auth/logout":
    r.clearSession(req)
    await req.respond(Http303, "", newHttpHeaders({
      "Location": "/auth/login",
      "Set-Cookie": "pulseboard_session=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0",
    }))
    return

  if req.reqMethod == HttpGet and path == "health":
    await jsonResponse(req, Http200, %*{"ok": true})
    return

  if req.reqMethod == HttpGet and isPublicWebAsset(path):
    if not await serveStatic(r, req, path):
      await fail(req, Http404, "not found")
    return

  let userDid = r.sessionUser(req)
  if userDid.len == 0:
    if segs[0] in ["feeds", "articles", "unread", "opml", "refresh", "read",
                   "read-all", "fetch-content"]:
      await fail(req, Http401, "AT Protocol authentication required")
    else:
      await req.respond(Http307, "", newHttpHeaders({"Location": "/auth/login"}))
    return

  case req.reqMethod
  of HttpGet:
    case segs[0]
    of "":
      await serveApp(r, req)
    of "feeds":
      var items = newJArray()
      for s in r.db.listSubscriptions(userDid, "", 500, 0):
        items.add toJson(s, s.unreadCount)
      await jsonResponse(req, Http200, items)

    of "opml":
      var feeds: seq[OpmlFeed]
      for s in r.db.listSubscriptions(userDid, "", 5000, 0):
        feeds.add OpmlFeed(url: s.feedUrl, title: s.feedTitle, category: s.category)
      await req.respond(Http200, renderOpml(feeds), newHttpHeaders({
        "Content-Type": "application/xml; charset=utf-8",
        "Content-Disposition": "attachment; filename=pulseboard-subscriptions.opml",
      }))

    of "articles":
      if segs.len == 2:
        # One article, with its full text if we have it.
        let id = try: parseInt(segs[1]) except ValueError: 0
        let a = r.db.getArticle(userDid, id)
        if a.isNone:
          await fail(req, Http404, "no such article")
        else:
          await jsonResponse(req, Http200, toJson(a.get))
        return

      let search = param("q")
      let articles =
        if search.len > 0:
          r.db.searchArticles(userDid, search, intParam("limit", 50), 0)
        else:
          r.db.listArticles(
            userDid,
            filter = (if param("status") == "all": afAll
                      elif param("status") == "read": afRead
                      else: afUnread),
            feedUrl = param("feed"),
            limit = intParam("limit", 50))
      var items = newJArray()
      for a in articles: items.add toJson(a)
      await jsonResponse(req, Http200, items)

    of "unread":
      await jsonResponse(req, Http200,
                         %*{"count": r.db.getUnreadCount(userDid, "", "")})
    else:
      # Not an API route: it may be an asset of the web client.
      if not await serveStatic(r, req, path):
        await fail(req, Http404, "not found")

  of HttpPost:
    case segs[0]
    of "opml":
      let source = param("opml")
      if source.len == 0:
        await fail(req, Http400, "OPML required")
        return
      if source.len > 1_000_000:
        await fail(req, Http413, "OPML is too large")
        return
      var imported: seq[OpmlFeed]
      try:
        imported = parseOpml(source)
      except CatchableError as e:
        await fail(req, Http400, "invalid OPML: " & e.msg)
        return
      var added = 0
      var errors = newJArray()
      for feed in imported:
        let exists = r.db.getSubscription(userDid, feed.url).isSome
        r.db.upsertFeed(Feed(feedUrl: feed.url, title: feed.title,
                             siteUrl: feed.siteUrl, description: feed.description))
        r.db.createSubscription(userDid, feed.url, feed.title, feed.category, "", "")
        if not exists: inc added
        let (_, err) = r.refreshFeed(userDid, feed.url)
        if err.len > 0: errors.add %*{"feed_url": feed.url, "error": err}
      await jsonResponse(req, Http200,
                         %*{"imported": imported.len, "added": added, "errors": errors})

    of "feeds":
      let url = param("url")
      if url.len == 0:
        await fail(req, Http400, "url required")
        return
      # Subscribe first so a feed that fails to fetch is still listed, with
      # its error visible, rather than vanishing.
      r.db.upsertFeed(Feed(feedUrl: url, title: url))
      r.db.createSubscription(userDid, url, "", param("category"), "", "")
      let (added, err) = r.refreshFeed(userDid, url)
      if err.len > 0:
        await jsonResponse(req, Http200,
                           %*{"feed_url": url, "added": 0, "error": err})
      else:
        await jsonResponse(req, Http200, %*{"feed_url": url, "added": added})

    of "refresh":
      var total = 0
      var errors = newJArray()
      for s in r.db.listSubscriptions(userDid, "", 500, 0):
        let (added, err) = r.refreshFeed(userDid, s.feedUrl)
        total += added
        if err.len > 0:
          errors.add %*{"feed_url": s.feedUrl, "error": err}
      await jsonResponse(req, Http200, %*{"added": total, "errors": errors})

    of "read":
      let id = intParam("id", 0)
      if id == 0:
        await fail(req, Http400, "id required")
        return
      if param("undo") == "1":
        r.db.markArticleUnread(userDid, id)
      else:
        r.db.markArticleRead(userDid, id)
      await jsonResponse(req, Http200, %*{"id": id})

    of "read-all":
      r.db.markAllRead(userDid, param("feed"))
      await jsonResponse(req, Http200,
                         %*{"unread": r.db.getUnreadCount(userDid, "", "")})

    of "fetch-content":
      # Most feeds ship an excerpt; this pulls the real article.
      let id = intParam("id", 0)
      let a = r.db.getArticle(userDid, id)
      if a.isNone or a.get.url.len == 0:
        await fail(req, Http404, "no such article")
        return
      try:
        let client = newHttpClient(timeout = 20_000,
                                   userAgent = "pulseboard/0.1")
        defer: client.close()
        let text = extractArticle(client.getContent(a.get.url))
        r.db.updateArticleFullContent(id, text)
        await jsonResponse(req, Http200, %*{"id": id, "content": text})
      except CatchableError as e:
        await fail(req, Http502, e.msg)
    else:
      await fail(req, Http404, "not found")

  of HttpDelete:
    if segs[0] == "feeds" and param("url").len > 0:
      r.db.deleteSubscription(userDid, param("url"))
      await jsonResponse(req, Http200, %*{"ok": true})
    else:
      await fail(req, Http400, "url required")

  else:
    await fail(req, Http405, "method not allowed")

proc main() {.async.} =
  let dbPath = getEnv("PULSEBOARD_DB", getHomeDir() / ".local/share/pulseboard/pulseboard")
  createDir(dbPath.parentDir)
  let port = try: parseInt(getEnv("PULSEBOARD_PORT", $DefaultPort))
             except ValueError: DefaultPort

  var db = pulseboarddb.open(dbPath)
  db.migrate()
  db.db.run("DELETE FROM web_sessions WHERE expires_at <= ?", p(getTime().toUnix))

  let webRoot = getEnv("PULSEBOARD_WEB")
  let publicUrl = getEnv("PULSEBOARD_PUBLIC_URL")
  let oauthRoot = getEnv("PULSEBOARD_OAUTH_ROOT", dbPath.parentDir / "oauth")
  let oauthHelper = getEnv("PULSEBOARD_OAUTH_HELPER",
                           getAppDir() / "auth/atproto-oauth.mjs")
  if webRoot.len == 0:
    quit("PULSEBOARD_WEB is required and must point at a Flutter web build")
  if not dirExists(webRoot) or not fileExists(webRoot / "index.html"):
    quit(&"PULSEBOARD_WEB points at {webRoot}, which has no index.html")
  if publicUrl.len == 0:
    quit("PULSEBOARD_PUBLIC_URL is required for AT Protocol OAuth")
  if not fileExists(oauthHelper):
    quit(&"AT Protocol OAuth helper is missing: {oauthHelper}")
  putEnv("PULSEBOARD_OAUTH_ROOT", oauthRoot)

  let metadataResult = runOauth(oauthHelper, "metadata", "{}")
  if metadataResult.exitCode != 0:
    quit("AT Protocol OAuth metadata unavailable: " & metadataResult.output.strip)
  let oauthMetadata = try:
      parseJson(metadataResult.output)
    except JsonParsingError as e:
      quit("AT Protocol OAuth metadata is invalid: " & e.msg)

  let reader = Reader(db: db, webRoot: webRoot, oauthHelper: oauthHelper,
                      oauthMetadata: oauthMetadata)

  echo &"pulseboard reading from {dbPath}"
  echo &"serving the client from {webRoot}"
  echo &"AT Protocol callback: {publicUrl}/auth/callback"

  var server = newAsyncHttpServer()
  # Single-threaded server, single Reader: the cast is asserting that, not
  # claiming the Reader is safe to share across threads.
  # Single-threaded server with one Reader. The cast asserts that, rather
  # than claiming the modules underneath are thread-safe -- they are not, and
  # do not need to be.
  proc cb(req: Request) {.async, gcsafe.} =
    {.cast(gcsafe).}:
      await reader.handle(req)
  await server.serve(Port(port), cb, address = "0.0.0.0")

when isMainModule:
  waitFor main()
