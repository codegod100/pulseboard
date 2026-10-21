# Pulseboard's web client: an ultra app (LPython compiled to wasm).
#
# The Worker serves this page and the JSON API from the same origin, so every
# request carries the session cookie. A 401 sends the browser to /auth/login
# (see api() in index.html).
#
# LPython's wasm backend has no runtime strings or lists, so the model is
# parallel i32 arrays. Feeds and articles stay in ultra's JSON store and the
# view reads their fields by handle; text the user types lives in string
# handles.

from lpython import i32, Const
from numpy import empty, int32
from ultra import (el, end, text, text_ref, num, cls, cls_if, attr, attr_ref,
                   key, autofocus, on_click, on_enter, on_escape, on_input, value_ref,
                   after, div, span,
                   s_new, s_set, s_add, s_add_ref, s_add_num, s_copy, s_clear,
                   s_free, s_len, s_eq, s_has, store_i32, load_i32,
                   j_ok, j_err, j_idx, j_int, j_len, j_str, j_free)
from ui import (btn, btn_open, input_open, tabs_list_open, tab, dialog_open,
                dialog_footer_open)

# ---------------------------------------------------------------- imports
# Pulseboard's own JS imports, supplied by index.html.

@jscall
def api(method: str, url: i32, body: i32, msg: i32) -> i32:
    """Request url (a string handle) with an optional form body (a string
    handle, or 0 for none). Returns a JSON handle at once and sends
    update(msg, handle) when the response is in."""
    pass

@jscall
def s_add_enc(h: i32, src: i32) -> None:
    """Append src to h, URI-encoded for a query string or form body."""
    pass

@jscall
def j_fmt(h: i32, path: str, kind: i32, dst: i32) -> i32:
    """Format the string at path into dst. kind: FMT_PREVIEW, FMT_AGO,
    FMT_INITIAL, FMT_LINK. Returns 1 when there was something to write (for
    FMT_LINK, when the value is an http(s) URL)."""
    pass

@jscall
def copy_text(h: i32) -> None:
    pass

@jscall
def narrow() -> i32:
    """1 when the feed list is a drawer (a phone-width window)."""
    pass

# Calls whose result is dropped need a home: LPython's wasm backend fails on a
# bare expression statement that returns a value.

def req(method: str, u: i32, b: i32, msg: i32) -> None:
    r: i32 = api(method, u, b, msg)


def jstr(h: i32, path: str, dst: i32) -> None:
    r: i32 = j_str(h, path, dst)


def jfmt(h: i32, path: str, kind: i32, dst: i32) -> None:
    r: i32 = j_fmt(h, path, kind, dst)

FMT_PREVIEW: Const[i32] = 0
FMT_AGO: Const[i32] = 1
FMT_INITIAL: Const[i32] = 2
FMT_LINK: Const[i32] = 3

# ---------------------------------------------------------------- Msg

FEEDS_DONE: Const[i32] = 1
UNREAD_DONE: Const[i32] = 2
ARTS_DONE: Const[i32] = 3
REFRESH: Const[i32] = 4
REFRESH_DONE: Const[i32] = 5
SELECT: Const[i32] = 6
STATUS: Const[i32] = 7
SEARCH_INPUT: Const[i32] = 8
SEARCH_GO: Const[i32] = 9
SEARCH_CLEAR: Const[i32] = 10
TOGGLE_READ: Const[i32] = 11
OPENED: Const[i32] = 12
READ_DONE: Const[i32] = 13
NO_LINK: Const[i32] = 14
MARK_ALL_ASK: Const[i32] = 15
MARK_ALL_YES: Const[i32] = 16
MARK_ALL_DONE: Const[i32] = 17
DIALOG_CLOSE: Const[i32] = 18
DRAWER: Const[i32] = 19
MANAGE: Const[i32] = 20
MANAGE_CLOSE: Const[i32] = 21
ADD_INPUT: Const[i32] = 22
ADD_GO: Const[i32] = 23
ADD_DONE: Const[i32] = 24
FILTER_INPUT: Const[i32] = 25
REMOVE_ASK: Const[i32] = 26
REMOVE_YES: Const[i32] = 27
REMOVE_DONE: Const[i32] = 28
IMPORT_ASK: Const[i32] = 29
IMPORT_INPUT: Const[i32] = 30
IMPORT_GO: Const[i32] = 31
IMPORT_DONE: Const[i32] = 32
EXPORT: Const[i32] = 33
EXPORT_DONE: Const[i32] = 34
TOAST_HIDE: Const[i32] = 35
RETRY: Const[i32] = 36
NOTHING: Const[i32] = 37

# which dialog is up
DLG_NONE: Const[i32] = 0
DLG_MARK_ALL: Const[i32] = 1
DLG_REMOVE: Const[i32] = 2
DLG_IMPORT: Const[i32] = 3

# article list state
LOADING: Const[i32] = 0
READY: Const[i32] = 1
FAILED: Const[i32] = 2

ST_UNREAD: Const[i32] = 0
ST_ALL: Const[i32] = 1
ST_READ: Const[i32] = 2

MAX_FEEDS: Const[i32] = 1024
MAX_ARTS: Const[i32] = 256
LIMIT: Const[i32] = 100

# ---------------------------------------------------------------- Model

# feeds: the /feeds response, an element handle per feed, its URL as a string
# handle (to compare and to put in queries) and its unread count
feeds_doc: i32 = 0
n_feeds: i32 = 0
feed_h: i32[1024] = empty(1024, dtype=int32)
feed_url: i32[1024] = empty(1024, dtype=int32)
feed_unread: i32[1024] = empty(1024, dtype=int32)
feeds_error: i32 = 0     # string handle, empty when fine
unread: i32 = 0

# articles: the /articles response and per-row columns
arts_doc: i32 = 0
arts_req: i32 = 0        # the request whose answer we are waiting for
arts_mark_new: i32 = 0
arts_state: i32 = 0
arts_error: i32 = 0
n_arts: i32 = 0
art_h: i32[256] = empty(256, dtype=int32)
art_id: i32[256] = empty(256, dtype=int32)
art_read: i32[256] = empty(256, dtype=int32)
art_feed: i32[256] = empty(256, dtype=int32)   # index into feeds, or -1
art_link: i32[256] = empty(256, dtype=int32)   # 1 when the URL is http(s)
# ids on screen before the last fetch, to find where new rows end
n_seen: i32 = 0
seen: i32[256] = empty(256, dtype=int32)
has_seen: i32 = 0
boundary: i32 = -1       # the red line goes before this row

# filters
sel: i32 = -1            # selected feed, -1 for all
sel_url: i32 = 0         # its URL, so it survives a reload of the feed list
status: i32 = 0
search: i32 = 0          # the input
search_on: i32 = 0       # the search applied to the list

refreshing: i32 = 0
booted: i32 = 0          # the refresh on page load has started
quiet: i32 = 0
drawer: i32 = 0
collapsed: i32 = 0       # wide screens: feed list hidden, remembered
managing: i32 = 0
changed: i32 = 0
dialog: i32 = 0
target: i32 = -1         # feed index the remove dialog is about

add_url: i32 = 0
adding: i32 = 0
filter: i32 = 0
opml: i32 = 0

toast: i32 = 0
toast_on: i32 = 0
toast_seq: i32 = 0

url: i32 = 0             # scratch: request URLs and bodies
body: i32 = 0
tmp: i32 = 0             # scratch: text read out of JSON for the view
tmp2: i32 = 0


def init() -> None:
    global collapsed
    global feeds_error, arts_error, sel_url, search, add_url, filter, opml
    global toast, url, body, tmp, tmp2
    collapsed = load_i32("pulseboard.sidebar.collapsed", 0)
    feeds_error = s_new()
    arts_error = s_new()
    sel_url = s_new()
    search = s_new()
    add_url = s_new()
    filter = s_new()
    opml = s_new()
    toast = s_new()
    url = s_new()
    body = s_new()
    tmp = s_new()
    tmp2 = s_new()
    load_feeds()
    # Show what is stored, then (once that list is in, so there is something
    # to compare against) have the reader fetch the feeds, so the page opens
    # on whatever arrived since the last visit. See got_articles().
    load_articles(0)

# ---------------------------------------------------------------- requests

def load_feeds() -> None:
    s_set(url, "/feeds")
    req("GET", url, 0, FEEDS_DONE)
    s_set(url, "/unread")
    req("GET", url, 0, UNREAD_DONE)


def load_articles(mark_new: i32) -> None:
    global arts_req, arts_mark_new, arts_state
    if search_on == 1:
        s_set(url, "/articles?q=")
        s_add_enc(url, search)
    else:
        s_set(url, "/articles?status=")
        if status == ST_ALL:
            s_add(url, "all")
        elif status == ST_READ:
            s_add(url, "read")
        else:
            s_add(url, "unread")
        if sel >= 0:
            s_add(url, "&feed=")
            s_add_enc(url, sel_url)
    s_add(url, "&limit=")
    s_add_num(url, LIMIT)
    arts_mark_new = mark_new
    arts_state = LOADING
    arts_req = api("GET", url, 0, ARTS_DONE)


def start_refresh(is_quiet: i32) -> None:
    global refreshing, quiet
    if refreshing == 1:
        return
    refreshing = 1
    quiet = is_quiet
    s_set(url, "/refresh")
    s_clear(body)
    req("POST", url, body, REFRESH_DONE)


def post_read(i: i32, read: i32) -> None:
    s_set(url, "/read")
    s_set(body, "id=")
    s_add_num(body, art_id[i])
    if read == 0:
        s_add(body, "&undo=1")
    req("POST", url, body, READ_DONE)


def show_toast() -> None:
    global toast_on, toast_seq
    toast_on = 1
    toast_seq += 1
    after(3500, TOAST_HIDE, toast_seq)


def toast_error(doc: i32) -> None:
    j_err(doc, toast)
    show_toast()


def find_feed(h: i32) -> i32:
    i: i32
    for i in range(n_feeds):
        if s_eq(feed_url[i], h) == 1:
            return i
    return -1


def set_read(i: i32, read: i32) -> None:
    """Flip one row locally, keeping the counts in step."""
    global unread
    d: i32 = 1
    f: i32 = art_feed[i]
    if art_read[i] == read:
        return
    art_read[i] = read
    if read == 1:
        d = -1
    unread += d
    if unread < 0:
        unread = 0
    if f >= 0:
        feed_unread[f] = feed_unread[f] + d
        if feed_unread[f] < 0:
            feed_unread[f] = 0

# ---------------------------------------------------------------- responses

def got_feeds(doc: i32) -> None:
    global feeds_doc, n_feeds, sel
    i: i32
    if j_ok(doc) == 0:
        j_err(doc, feeds_error)
        j_free(doc)
        return
    s_clear(feeds_error)
    for i in range(n_feeds):
        j_free(feed_h[i])
        s_free(feed_url[i])
    if feeds_doc != 0:
        j_free(feeds_doc)
    feeds_doc = doc
    n_feeds = j_len(doc, "")
    if n_feeds > MAX_FEEDS:
        n_feeds = MAX_FEEDS
    for i in range(n_feeds):
        feed_h[i] = j_idx(doc, i)
        feed_unread[i] = j_int(feed_h[i], "unread")
        feed_url[i] = s_new()
        jstr(feed_h[i], "feed_url", feed_url[i])
    if sel >= 0:
        sel = find_feed(sel_url)
        if sel < 0:
            # the feed was removed: back to everything
            s_clear(sel_url)
            load_articles(0)
    link_articles()


def link_articles() -> None:
    """Point each row at its feed, for the sidebar counts."""
    i: i32
    for i in range(n_arts):
        jstr(art_h[i], "feed_url", tmp)
        art_feed[i] = find_feed(tmp)


def was_seen(id: i32) -> bool:
    i: i32
    for i in range(n_seen):
        if seen[i] == id:
            return True
    return False


def got_articles(doc: i32) -> None:
    global arts_doc, n_arts, arts_state, boundary, n_seen, has_seen, booted
    i: i32
    first_seen: i32 = -1
    if doc != arts_req:
        j_free(doc)   # an older request, overtaken by a newer one
        return
    if booted == 0:
        booted = 1
        start_refresh(1)
    if j_ok(doc) == 0:
        j_err(doc, arts_error)
        arts_state = FAILED
        j_free(doc)
        return
    for i in range(n_arts):
        j_free(art_h[i])
    if arts_doc != 0:
        j_free(arts_doc)
    arts_doc = doc
    n_arts = j_len(doc, "")
    if n_arts > MAX_ARTS:
        n_arts = MAX_ARTS
    boundary = -1
    for i in range(n_arts):
        art_h[i] = j_idx(doc, i)
        art_id[i] = j_int(art_h[i], "id")
        art_read[i] = j_int(art_h[i], "is_read")
        art_link[i] = j_fmt(art_h[i], "url", FMT_LINK, tmp)
        if arts_mark_new == 1 and has_seen == 1 and first_seen < 0:
            if was_seen(art_id[i]):
                first_seen = i
    # only draw the line when something new sits above something seen
    if first_seen > 0:
        boundary = first_seen
    n_seen = n_arts
    for i in range(n_arts):
        seen[i] = art_id[i]
    has_seen = 1
    link_articles()
    arts_state = READY


def got_refresh(doc: i32) -> None:
    global refreshing
    added: i32
    failed: i32
    refreshing = 0
    if j_ok(doc) == 0:
        toast_error(doc)
        j_free(doc)
        return
    added = j_int(doc, "added")
    failed = j_len(doc, "errors")
    j_free(doc)
    load_feeds()
    load_articles(1)
    if quiet == 1 and failed == 0:
        return
    s_set(toast, "")
    s_add_num(toast, added)
    s_add(toast, " new")
    if failed > 0:
        s_add(toast, ", ")
        s_add_num(toast, failed)
        s_add(toast, " feed(s) failed")
    show_toast()


def got_simple(doc: i32, ok_text: str) -> i32:
    """Toast ok_text or the error. Returns 1 on success."""
    ok: i32 = j_ok(doc)
    if ok == 0:
        toast_error(doc)
    elif ok_text != "":
        s_set(toast, ok_text)
        show_toast()
    j_free(doc)
    return ok

# ---------------------------------------------------------------- update

def update(msg: i32, arg: i32) -> None:
    global unread, sel, status, search_on, drawer, managing, changed, dialog
    global collapsed
    global target, adding, toast_on, boundary
    ok: i32
    added: i32
    failed: i32
    if msg == FEEDS_DONE:
        got_feeds(arg)
    elif msg == UNREAD_DONE:
        if j_ok(arg) == 1:
            unread = j_int(arg, "count")
        j_free(arg)
    elif msg == ARTS_DONE:
        got_articles(arg)
    elif msg == REFRESH:
        start_refresh(0)
    elif msg == REFRESH_DONE:
        got_refresh(arg)
    elif msg == SELECT:
        sel = arg
        if arg >= 0:
            s_copy(sel_url, feed_url[arg])
        else:
            s_clear(sel_url)
        drawer = 0
        managing = 0
        search_on = 0
        s_clear(search)
        load_articles(0)
    elif msg == STATUS:
        status = arg
        load_articles(0)
    elif msg == SEARCH_INPUT:
        s_copy(search, arg)
    elif msg == SEARCH_GO:
        search_on = 0
        if s_len(search) > 0:
            search_on = 1
        load_articles(0)
    elif msg == SEARCH_CLEAR:
        s_clear(search)
        search_on = 0
        load_articles(0)
    elif msg == TOGGLE_READ:
        set_read(arg, 1 - art_read[arg])
        post_read(arg, art_read[arg])
    elif msg == OPENED:
        # the browser follows the link itself; this only marks the row read
        if art_read[arg] == 0:
            set_read(arg, 1)
            post_read(arg, 1)
    elif msg == READ_DONE:
        if j_ok(arg) == 0:
            # put the counts and rows back as the server has them
            toast_error(arg)
            load_feeds()
            load_articles(0)
        j_free(arg)
    elif msg == NO_LINK:
        s_set(toast, "This article does not have a valid link.")
        show_toast()
    elif msg == MARK_ALL_ASK:
        dialog = DLG_MARK_ALL
    elif msg == MARK_ALL_YES:
        dialog = DLG_NONE
        s_set(url, "/read-all")
        s_clear(body)
        if sel >= 0:
            s_set(body, "feed=")
            s_add_enc(body, sel_url)
        req("POST", url, body, MARK_ALL_DONE)
    elif msg == MARK_ALL_DONE:
        if got_simple(arg, "") == 1:
            load_feeds()
            load_articles(0)
    elif msg == DIALOG_CLOSE:
        dialog = DLG_NONE
    elif msg == DRAWER:
        # one button: a drawer on phones, a collapsible column on wider screens
        if narrow() == 1:
            drawer = 1 - drawer
        else:
            drawer = 0
            collapsed = 1 - collapsed
            store_i32("pulseboard.sidebar.collapsed", collapsed)
    elif msg == MANAGE:
        managing = 1
        changed = 0
        drawer = 0
    elif msg == MANAGE_CLOSE:
        managing = 0
        if changed == 1:
            load_articles(0)
    elif msg == ADD_INPUT:
        s_copy(add_url, arg)
    elif msg == ADD_GO:
        if s_len(add_url) > 0 and adding == 0:
            adding = 1
            s_set(url, "/feeds")
            s_set(body, "url=")
            s_add_enc(body, add_url)
            req("POST", url, body, ADD_DONE)
    elif msg == ADD_DONE:
        adding = 0
        if got_simple(arg, "Feed added") == 1:
            s_clear(add_url)
            changed = 1
            load_feeds()
    elif msg == FILTER_INPUT:
        s_copy(filter, arg)
    elif msg == REMOVE_ASK:
        target = arg
        dialog = DLG_REMOVE
    elif msg == REMOVE_YES:
        dialog = DLG_NONE
        if target >= 0 and target < n_feeds:
            s_set(url, "/feeds?url=")
            s_add_enc(url, feed_url[target])
            req("DELETE", url, 0, REMOVE_DONE)
    elif msg == REMOVE_DONE:
        if got_simple(arg, "Feed removed") == 1:
            changed = 1
            load_feeds()
    elif msg == IMPORT_ASK:
        s_clear(opml)
        dialog = DLG_IMPORT
    elif msg == IMPORT_INPUT:
        s_copy(opml, arg)
    elif msg == IMPORT_GO:
        dialog = DLG_NONE
        if s_len(opml) > 0:
            s_set(url, "/opml")
            s_set(body, "opml=")
            s_add_enc(body, opml)
            req("POST", url, body, IMPORT_DONE)
    elif msg == IMPORT_DONE:
        if j_ok(arg) == 0:
            toast_error(arg)
        else:
            added = j_int(arg, "added")
            failed = j_len(arg, "errors")
            if added > 0:
                changed = 1
            s_set(toast, "")
            s_add_num(toast, added)
            s_add(toast, " feed(s) added")
            if failed > 0:
                s_add(toast, ", ")
                s_add_num(toast, failed)
                s_add(toast, " failed")
            show_toast()
            load_feeds()
        j_free(arg)
    elif msg == EXPORT:
        s_set(url, "/opml")
        req("GET", url, 0, EXPORT_DONE)
    elif msg == EXPORT_DONE:
        if j_ok(arg) == 0:
            toast_error(arg)
        else:
            jstr(arg, "", tmp)
            copy_text(tmp)
            s_set(toast, "OPML backup copied to clipboard")
            show_toast()
        j_free(arg)
    elif msg == TOAST_HIDE:
        if arg == toast_seq:
            toast_on = 0
    elif msg == RETRY:
        load_feeds()
        load_articles(0)

# ---------------------------------------------------------------- view

def icon(name: str) -> None:
    el("span")
    cls("ic")
    cls(name)
    attr("aria-hidden", "true")
    end()


def icon_btn(name: str, label: str, msg: i32, arg: i32) -> None:
    btn_open("ghost", msg, arg)
    cls("icon")
    attr("aria-label", label)
    attr("title", label)
    icon(name)
    end()


def favicon(f: i32) -> None:
    el("span")
    cls("fav")
    jfmt(feed_h[f], "title", FMT_INITIAL, tmp)
    text_ref(tmp)
    if j_str(feed_h[f], "favicon_url", tmp) == 1 and s_len(tmp) > 0:
        el("img")
        attr_ref("src", tmp)
        attr("alt", "")
        attr("loading", "lazy")
        attr("onerror", "this.remove()")
        end()
    end()


def jtext(h: i32, path: str) -> None:
    jstr(h, path, tmp)
    text_ref(tmp)


def view_feed_row(f: i32) -> None:
    el("button")
    key(f + 2)
    cls("feed")
    cls_if("selected", sel == f)
    on_click(SELECT, f)
    favicon(f)
    el("span")
    cls("feed-title")
    jtext(feed_h[f], "title")
    end()
    if feed_unread[f] > 0:
        el("span")
        cls("count")
        num(feed_unread[f])
        end()
    end()


def view_sidebar() -> None:
    f: i32
    el("nav")
    cls("sidebar")
    cls_if("open", drawer == 1)
    div("sidebar-head")
    el("h2")
    text("Feeds")
    end()
    icon_btn("i-tune", "Manage feeds", MANAGE, 0)
    icon_btn("i-panel", "Hide feeds", DRAWER, 0)
    end()
    if s_len(feeds_error) > 0:
        el("p")
        cls("error-text")
        text_ref(feeds_error)
        end()
    div("feeds")
    el("button")
    key(1)
    cls("feed")
    cls_if("selected", sel < 0)
    on_click(SELECT, -1)
    icon("i-inbox")
    el("span")
    cls("feed-title")
    text("All feeds")
    end()
    if unread > 0:
        el("span")
        cls("count")
        cls("all")
        num(unread)
        end()
    end()
    for f in range(n_feeds):
        view_feed_row(f)
    end()
    end()
    if drawer == 1:
        div("scrim")
        on_click(DRAWER, 0)
        end()


def view_header() -> None:
    el("header")
    cls("topbar")
    el("span")
    cls("menu")
    icon_btn("i-menu", "Show feeds", DRAWER, 0)
    end()
    el("h1")
    if sel >= 0:
        jtext(feed_h[sel], "title")
    else:
        text("Pulseboard")
    end()
    div("actions")
    icon_btn("i-rss", "Manage feeds", MANAGE, 0)
    icon_btn("i-check-all", "Mark all read", MARK_ALL_ASK, 0)
    btn_open("ghost", REFRESH, 0)
    cls("icon")
    cls_if("spinning", refreshing == 1)
    attr("aria-label", "Refresh")
    attr("title", "Refresh")
    icon("i-refresh")
    end()
    end()
    end()


def view_toolbar() -> None:
    div("toolbar")
    div("search")
    icon("i-search")
    input_open("Search articles", search, SEARCH_INPUT)
    attr("type", "search")
    on_enter(SEARCH_GO, 0)
    on_escape(SEARCH_CLEAR, 0)
    end()
    if search_on == 1:
        icon_btn("i-x", "Clear search", SEARCH_CLEAR, 0)
    end()
    # a search spans everything, so the status filter means nothing during one
    if search_on == 0:
        tabs_list_open()
        tab("Unread", status == ST_UNREAD, STATUS, ST_UNREAD)
        tab("All", status == ST_ALL, STATUS, ST_ALL)
        tab("Read", status == ST_READ, STATUS, ST_READ)
        end()
    end()


def view_article(i: i32) -> None:
    h: i32 = art_h[i]
    read: bool = art_read[i] == 1
    el("li")
    key(art_id[i])
    cls("article")
    cls_if("read", read)
    el("a")
    cls("article-link")
    if art_link[i] == 1:
        jstr(h, "url", tmp)
        attr_ref("href", tmp)
        attr("target", "_blank")
        attr("rel", "noopener")
        on_click(OPENED, i)
    else:
        on_click(NO_LINK, 0)
    div("meta")
    span("dot")
    end()
    span("source")
    jtext(h, "feed_title")
    end()
    if j_fmt(h, "published", FMT_AGO, tmp) == 1:
        el("time")
        jstr(h, "published", tmp2)
        attr_ref("datetime", tmp2)
        text_ref(tmp)
        end()
    end()
    el("h3")
    if j_fmt(h, "title", FMT_PREVIEW, tmp) == 1:
        text_ref(tmp)
    else:
        text("(untitled)")
    end()
    if j_fmt(h, "summary", FMT_PREVIEW, tmp) == 1:
        el("p")
        text_ref(tmp)
        end()
    end()
    if read:
        icon_btn("i-unread", "Mark unread", TOGGLE_READ, i)
    else:
        icon_btn("i-check", "Mark read", TOGGLE_READ, i)
    end()


def view_articles() -> None:
    i: i32
    if arts_state == FAILED:
        div("state")
        el("p")
        cls("bang")
        text("!")
        end()
        el("p")
        text_ref(arts_error)
        end()
        btn("Retry", "outline", RETRY, 0)
        end()
        return
    if arts_state == LOADING and n_arts == 0:
        div("state")
        span("spinner")
        end()
        end()
        return
    if n_arts == 0:
        div("state")
        el("p")
        cls("muted")
        if search_on == 1:
            text("Nothing matches \"")
            text_ref(search)
            text("\".")
        else:
            text("Nothing here.")
        end()
        end()
        return
    el("ul")
    cls("articles")
    cls_if("stale", arts_state == LOADING)
    for i in range(n_arts):
        if i == boundary:
            el("li")
            key(-1)
            cls("new-line")
            attr("role", "separator")
            attr("aria-label", "New since last fetch")
            end()
        view_article(i)
    end()


def view_manage() -> None:
    f: i32
    shown: i32 = 0
    el("main")
    cls("manage")
    el("header")
    cls("topbar")
    icon_btn("i-back", "Back", MANAGE_CLOSE, 0)
    el("h1")
    text("Manage feeds")
    end()
    end()
    div("manage-body")

    el("h2")
    text("Add a subscription")
    end()
    div("row")
    input_open("https://example.com/feed.xml", add_url, ADD_INPUT)
    attr("type", "url")
    on_enter(ADD_GO, 0)
    end()
    if adding == 1:
        span("spinner")
        end()
    else:
        btn_open("", ADD_GO, 0)
        icon("i-plus")
        text("Add")
        end()
    end()

    div("subs-head")
    el("h2")
    text("Subscriptions")
    end()
    el("span")
    cls("muted")
    num(n_feeds)
    end()
    end()
    input_open("Filter feeds", filter, FILTER_INPUT)
    attr("type", "search")
    end()
    el("ul")
    cls("subs")
    for f in range(n_feeds):
        jstr(feed_h[f], "title", tmp2)
        if s_has(tmp2, filter) == 1 or s_has(feed_url[f], filter) == 1:
            shown += 1
            el("li")
            key(f + 1)
            favicon(f)
            div("sub-text")
            el("strong")
            text_ref(tmp2)
            end()
            el("span")
            cls("muted")
            text_ref(feed_url[f])
            end()
            end()
            if feed_unread[f] > 0:
                el("span")
                cls("muted")
                cls("sub-unread")
                num(feed_unread[f])
                text(" unread")
                end()
            icon_btn("i-trash", "Remove feed", REMOVE_ASK, f)
            end()
    end()
    if shown == 0:
        el("p")
        cls("muted")
        cls("empty")
        if s_len(filter) > 0:
            text("No matching feeds.")
        else:
            text("No subscriptions yet.")
        end()

    el("h2")
    text("Backup & restore")
    end()
    div("row")
    cls("wrap")
    btn_open("outline", IMPORT_ASK, 0)
    icon("i-upload")
    text("Import OPML")
    end()
    btn_open("outline", EXPORT, 0)
    icon("i-copy")
    text("Copy OPML backup")
    end()
    end()

    end()
    end()


def view_dialog() -> None:
    if dialog == DLG_MARK_ALL:
        if sel >= 0:
            jstr(feed_h[sel], "title", tmp)
            dialog_open("Mark this feed read?", "", DIALOG_CLOSE)
            el("p")
            cls("muted")
            text_ref(tmp)
            end()
        else:
            dialog_open("Mark everything read?", "", DIALOG_CLOSE)
        dialog_footer_open()
        btn("Cancel", "outline", DIALOG_CLOSE, 0)
        btn("Mark read", "", MARK_ALL_YES, 0)
        end()
        end()
    elif dialog == DLG_REMOVE:
        dialog_open("Remove feed?", "", DIALOG_CLOSE)
        el("p")
        cls("muted")
        text("Stop following ")
        jtext(feed_h[target], "title")
        text("?")
        end()
        dialog_footer_open()
        btn("Keep", "outline", DIALOG_CLOSE, 0)
        btn("Remove", "destructive", REMOVE_YES, 0)
        end()
        end()
    elif dialog == DLG_IMPORT:
        dialog_open("Import OPML", "Paste your OPML here.", DIALOG_CLOSE)
        el("textarea")
        cls("input")
        cls("opml")
        attr("rows", "10")
        from_handle_input(opml, IMPORT_INPUT)
        end()
        dialog_footer_open()
        btn("Cancel", "outline", DIALOG_CLOSE, 0)
        btn("Import", "", IMPORT_GO, 0)
        end()
        end()


def from_handle_input(h: i32, msg: i32) -> None:
    # same binding input_open() makes, for a <textarea>
    value_ref(h)
    on_input(msg)


def view() -> None:
    div("app")
    cls_if("collapsed", collapsed == 1)
    if managing == 1:
        view_manage()
    else:
        view_sidebar()
        el("main")
        cls("reader")
        view_header()
        view_toolbar()
        view_articles()
        end()
    end()
    view_dialog()
    if toast_on == 1:
        div("toast")
        attr("role", "status")
        text_ref(toast)
        end()
