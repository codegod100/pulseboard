#include "html.h"

#include "util.h"

#include <QList>
#include <QPair>
#include <QSet>
#include <memory>
#include <vector>

namespace html {

namespace {

constexpr int MIN_CONTENT_LENGTH = 200;

const QStringList CONTENT_PATTERNS = {
    "post-content", "entry-content", "article-content", "article-body", "article__body",
    "article__content", "story-body", "story-content", "content-body", "post-body",
    "post-entry", "entry-body", "blog-content", "blog-post", "wp-content",
    "main-content", "page-content", "body-content"};
const QSet<QString> UNWANTED_TAGS = {
    "script", "style", "nav", "header", "footer", "aside", "noscript", "iframe", "form",
    "svg", "button", "input", "textarea", "select", "object", "embed", "frame",
    "frameset", "link", "meta", "base", "template", "math", "head", "title"};
const QSet<QString> UNWANTED_ROLES = {"complementary", "banner", "contentinfo", "navigation"};
const QStringList UNWANTED_CLASS_PATTERNS = {
    "comment", "sidebar", "advertisement", "ad-banner", "social-share", "share-button",
    "newsletter", "popup", "cookie", "paywall", "related-post", "related-article",
    "taboola", "outbrain", "disqus"};
// Narrower than the class list: an id of "header" is reliably the page
// header, while a class of "header" is often the article's own.
const QStringList UNWANTED_ID_PATTERNS = {"comment", "sidebar", "footer", "header", "nav", "disqus"};
const QSet<QString> VOID_ELEMENTS = {"br", "hr", "img", "input", "meta", "link", "area",
                                     "base", "col", "embed", "source", "track", "wbr"};
const QSet<QString> ALLOWED_ATTRS = {
    "href", "src", "alt", "title", "class", "id", "width", "height", "type", "controls",
    "preload", "poster", "cite", "datetime", "colspan", "rowspan", "loading", "decoding",
    "itemprop", "role", "aria-label", "aria-hidden"};
const QSet<QString> IMG_ALLOWED_ATTRS = {"alt", "width", "height", "class"};
// Content that never belongs in the output even as text; dropped while parsing.
const QSet<QString> RAW_TEXT = {"script", "style", "noscript", "template"};
// The tokenizer reads these as raw text up to their end tag (as HTMLParser does).
const QSet<QString> CDATA_CONTENT = {"script", "style"};

// Closing one of these implicitly closes an open <p> (and so on): enough of
// HTML's optional-end-tag rules to keep sloppy markup from nesting forever.
const QHash<QString, QSet<QString>> IMPLIED_END = {
    {"p", {"p"}}, {"li", {"li"}}, {"dt", {"dt", "dd"}}, {"dd", {"dt", "dd"}},
    {"tr", {"tr", "td", "th"}}, {"td", {"td", "th"}}, {"th", {"td", "th"}},
    {"option", {"option"}}};
const QSet<QString> BLOCK = {
    "address", "article", "aside", "blockquote", "div", "dl", "fieldset", "figure",
    "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "main", "nav",
    "ol", "pre", "section", "table", "ul"};

using Attrs = QList<QPair<QString, QString>>;

QString attr(const Attrs &a, const QString &key) {
    for (const auto &[k, v] : a)
        if (k == key)
            return v;
    return {};
}

// A node is an element (tag set) or a text run (tag empty).
struct Node {
    QString tag;
    Attrs attrs;
    QString text;
    std::vector<std::unique_ptr<Node>> children;
    Node *parent = nullptr;
    bool isText() const { return tag.isEmpty(); }
};

// --- tokenizer + tree builder ---------------------------------------------------

class Builder {
public:
    Node root;
    Builder() { root.tag = QStringLiteral("#root"); cur = &root; }

    void feed(const QString &s);

private:
    Node *cur;
    int skip = 0;

    void closeTo(const QString &tag) {
        for (Node *n = cur; n != &root; n = n->parent) {
            if (n->tag == tag) {
                cur = n->parent;
                return;
            }
        }
    }

    Node *add(const QString &tag, const Attrs &attrs) {
        auto node = std::make_unique<Node>();
        node->tag = tag;
        node->attrs = attrs;
        node->parent = cur;
        Node *raw = node.get();
        cur->children.push_back(std::move(node));
        return raw;
    }

    void start(const QString &tag, const Attrs &attrs, bool selfClosing) {
        if (skip) {
            if (RAW_TEXT.contains(tag) && !selfClosing)
                skip++;
            return;
        }
        if (RAW_TEXT.contains(tag)) {
            if (!selfClosing)
                skip = 1;
            return;
        }
        if (selfClosing) {
            add(tag, attrs);
            return;
        }
        if (IMPLIED_END.contains(tag) && IMPLIED_END.value(tag).contains(cur->tag))
            cur = cur->parent;
        else if (BLOCK.contains(tag) && cur->tag == u"p")
            cur = cur->parent;
        Node *n = add(tag, attrs);
        if (!VOID_ELEMENTS.contains(tag))
            cur = n;
    }

    void end(const QString &tag) {
        if (skip) {
            if (RAW_TEXT.contains(tag))
                skip--;
            return;
        }
        if (VOID_ELEMENTS.contains(tag))
            return;
        closeTo(tag);
    }

    void data(const QString &text) {
        if (skip || text.isEmpty())
            return;
        auto node = std::make_unique<Node>();
        node->text = text;
        node->parent = cur;
        cur->children.push_back(std::move(node));
    }
};

bool isNameStart(QChar c) { return c.isLetter(); }
bool isSpace(QChar c) {
    return c == u' ' || c == u'\t' || c == u'\n' || c == u'\r' || c == u'\f';
}

void Builder::feed(const QString &s) {
    const qsizetype n = s.size();
    qsizetype i = 0;
    QString pending;  // text, unescaped once complete
    auto flush = [&] {
        if (!pending.isEmpty())
            data(util::unescape(pending));
        pending.clear();
    };
    while (i < n) {
        const qsizetype lt = s.indexOf(u'<', i);
        if (lt < 0) {
            pending += QStringView(s).mid(i);
            break;
        }
        pending += QStringView(s).mid(i, lt - i);
        i = lt;
        if (i + 1 >= n) {
            pending += u'<';
            i++;
            break;
        }
        const QChar c = s[i + 1];
        if (s.mid(i, 4) == u"<!--") {
            flush();
            const qsizetype e = s.indexOf(QLatin1StringView("-->"), i + 4);
            i = e < 0 ? n : e + 3;
            continue;
        }
        if (c == u'!' || c == u'?') {
            flush();
            const qsizetype e = s.indexOf(u'>', i + 2);
            i = e < 0 ? n : e + 1;
            continue;
        }
        if (c == u'/') {
            if (i + 2 < n && isNameStart(s[i + 2])) {
                flush();
                qsizetype j = i + 2;
                while (j < n && !isSpace(s[j]) && s[j] != u'>' && s[j] != u'/')
                    j++;
                const QString tag = s.mid(i + 2, j - i - 2).toLower();
                const qsizetype e = s.indexOf(u'>', j);
                i = e < 0 ? n : e + 1;
                end(tag);
                continue;
            }
            // "</>" and "</ junk>" are bogus comments.
            flush();
            const qsizetype e = s.indexOf(u'>', i + 2);
            i = e < 0 ? n : e + 1;
            continue;
        }
        if (!isNameStart(c)) {
            pending += u'<';
            i++;
            continue;
        }
        // A start tag: name, then attributes, up to '>' outside quotes.
        qsizetype j = i + 1;
        while (j < n && !isSpace(s[j]) && s[j] != u'>' && s[j] != u'/')
            j++;
        const QString tag = s.mid(i + 1, j - i - 1).toLower();
        Attrs attrs;
        bool selfClosing = false;
        for (;;) {
            while (j < n && (isSpace(s[j]) || (s[j] == u'/' && j + 1 < n && s[j + 1] != u'>')))
                j++;
            if (j >= n)
                break;
            if (s[j] == u'>') {
                j++;
                break;
            }
            if (s[j] == u'/' && j + 1 < n && s[j + 1] == u'>') {
                selfClosing = true;
                j += 2;
                break;
            }
            qsizetype k = j;
            while (k < n && !isSpace(s[k]) && s[k] != u'=' && s[k] != u'>'
                   && !(s[k] == u'/' && k + 1 < n && s[k + 1] == u'>'))
                k++;
            if (k == j) {  // a stray '=' or the like
                j++;
                continue;
            }
            const QString name = s.mid(j, k - j).toLower();
            QString value;
            j = k;
            while (j < n && isSpace(s[j]))
                j++;
            if (j < n && s[j] == u'=') {
                j++;
                while (j < n && isSpace(s[j]))
                    j++;
                if (j < n && (s[j] == u'"' || s[j] == u'\'')) {
                    const QChar q = s[j];
                    const qsizetype e = s.indexOf(q, j + 1);
                    value = s.mid(j + 1, (e < 0 ? n : e) - j - 1);
                    j = e < 0 ? n : e + 1;
                } else {
                    qsizetype e = j;
                    while (e < n && !isSpace(s[e]) && s[e] != u'>')
                        e++;
                    value = s.mid(j, e - j);
                    j = e;
                }
                value = util::unescape(value);
            }
            // Like a dict: the last value wins, in the first one's place.
            bool replaced = false;
            for (auto &kv : attrs)
                if (kv.first == name) {
                    kv.second = value;
                    replaced = true;
                }
            if (!replaced)
                attrs.append({name, value});
        }
        flush();
        i = j;
        start(tag, attrs, selfClosing);
        if (CDATA_CONTENT.contains(tag) && !selfClosing) {
            // Raw text up to the matching end tag; script/style are dropped anyway.
            const qsizetype e = s.indexOf(QStringLiteral("</") + tag, i, Qt::CaseInsensitive);
            const QString raw = s.mid(i, (e < 0 ? n : e) - i);
            data(raw);  // skipped: RAW_TEXT
            if (e < 0) {
                i = n;
            } else {
                const qsizetype gt = s.indexOf(u'>', e);
                i = gt < 0 ? n : gt + 1;
                end(tag);
            }
        }
    }
    flush();
}

// --- tree helpers -----------------------------------------------------------------

template <typename F>
Node *findFirst(Node *n, F pred) {
    if (!n->isText() && pred(n))
        return n;
    for (auto &c : n->children)
        if (!c->isText())
            if (Node *f = findFirst(c.get(), pred))
                return f;
    return nullptr;
}

template <typename F>
void each(Node *n, F fn) {
    if (n->isText())
        return;
    fn(n);
    for (auto &c : n->children)
        each(c.get(), fn);
}

int textLength(const Node *n) {
    if (n->isText())
        return int(n->text.trimmed().size());
    int sum = 0;
    for (const auto &c : n->children)
        sum += textLength(c.get());
    return sum;
}

bool containsAny(const QString &s, const QStringList &patterns) {
    const QString l = s.toLower();
    for (const QString &p : patterns)
        if (l.contains(p))
            return true;
    return false;
}

Node *byContentClass(Node *root) {
    Node *best = nullptr;
    int bestLen = 0;
    each(root, [&](Node *e) {
        for (const char *key : {"class", "id"}) {
            const QString v = attr(e->attrs, QLatin1StringView(key));
            if (v.isEmpty() || !containsAny(v, CONTENT_PATTERNS))
                continue;
            const int tl = textLength(e);
            if (tl > bestLen && tl >= MIN_CONTENT_LENGTH) {
                best = e;
                bestLen = tl;
            }
        }
    });
    return best;
}

Node *largestTextNode(Node *root) {
    Node *best = nullptr;
    int bestLen = 0;
    each(root, [&](Node *e) {
        if (e->tag != u"div" && e->tag != u"section")
            return;
        const int tl = textLength(e);
        if (tl > bestLen && tl >= MIN_CONTENT_LENGTH) {
            best = e;
            bestLen = tl;
        }
    });
    return best;
}

Node *findArticle(Node *doc) {
    if (Node *n = findFirst(doc, [](Node *e) { return e->tag == u"article"; }))
        return n;
    if (Node *n = findFirst(doc, [](Node *e) { return attr(e->attrs, "role") == u"main"; }))
        return n;
    if (Node *n = findFirst(doc, [](Node *e) { return e->tag == u"main"; }))
        return n;
    if (Node *n = findFirst(doc, [](Node *e) { return attr(e->attrs, "itemprop") == u"articleBody"; }))
        return n;
    if (Node *n = byContentClass(doc))
        return n;
    return largestTextNode(doc);
}

bool isUnwanted(const Node *n) {
    if (n->isText())
        return false;
    if (UNWANTED_TAGS.contains(n->tag))
        return true;
    if (containsAny(attr(n->attrs, "class"), UNWANTED_CLASS_PATTERNS))
        return true;
    if (containsAny(attr(n->attrs, "id"), UNWANTED_ID_PATTERNS))
        return true;
    return UNWANTED_ROLES.contains(attr(n->attrs, "role").toLower());
}

void removeUnwanted(Node *n) {
    auto &c = n->children;
    c.erase(std::remove_if(c.begin(), c.end(), [](const auto &x) { return isUnwanted(x.get()); }),
            c.end());
    for (auto &x : c)
        if (!x->isText())
            removeUnwanted(x.get());
}

// --- rendering ------------------------------------------------------------------

bool reachable(const QString &url) {
    return url.startsWith(u"http://") || url.startsWith(u"https://") || url.startsWith(u"//");
}

QString imgSrc(const Node *n) {
    // Lazy-loaded images put a placeholder in src and the real URL elsewhere.
    for (const char *key : {"src", "data-src", "data-lazy-src"}) {
        const QString v = attr(n->attrs, QLatin1StringView(key));
        if (!v.isEmpty() && reachable(v))
            return v;
    }
    return {};
}

bool safeTag(const QString &tag) {
    bool any = false;
    for (QChar c : tag) {
        if (c == u'-')
            continue;
        if (!c.isLetterOrNumber())
            return false;
        any = true;
    }
    return any;
}

QString renderAttrs(const QString &tag, const Attrs &attrs) {
    const QSet<QString> &allowed = tag == u"img" ? IMG_ALLOWED_ATTRS : ALLOWED_ATTRS;
    QString out;
    for (const auto &[k, v] : attrs)
        if (allowed.contains(k))
            out += u' ' + k + QStringLiteral("=\"") + util::escape(v, true) + u'"';
    return out;
}

void render(QString &out, const Node *n) {
    if (n->isText()) {
        out += util::escape(n->text, false);
        return;
    }
    const QString &tag = n->tag;
    if (tag == u"#root" || tag == u"html" || tag == u"body" || !safeTag(tag)) {
        for (const auto &c : n->children)
            render(out, c.get());
        return;
    }
    if (tag == u"a") {
        const QString href = attr(n->attrs, "href");
        if (!reachable(href)) {
            for (const auto &c : n->children)
                render(out, c.get());
            return;
        }
        out += QStringLiteral("<a href=\"") + util::escape(href, true)
               + QStringLiteral("\" rel=\"noopener noreferrer\">");
        for (const auto &c : n->children)
            render(out, c.get());
        out += QStringLiteral("</a>");
        return;
    }
    if (tag == u"img") {
        const QString src = imgSrc(n);
        if (!src.isEmpty())
            out += QStringLiteral("<img src=\"") + util::escape(src, true) + u'"'
                   + renderAttrs(tag, n->attrs) + u'>';
        return;
    }
    // As the Python server did: without a reachable src these go entirely.
    if ((tag == u"source" || tag == u"video" || tag == u"audio") && !reachable(attr(n->attrs, "src")))
        return;
    out += u'<' + tag + renderAttrs(tag, n->attrs) + u'>';
    if (VOID_ELEMENTS.contains(tag))
        return;
    for (const auto &c : n->children)
        render(out, c.get());
    out += QStringLiteral("</") + tag + u'>';
}

QString renderChildren(const Node *n) {
    QString out;
    for (const auto &c : n->children)
        render(out, c.get());
    return out.trimmed();
}

}  // namespace

QString sanitizeFragment(const QString &markup) {
    if (markup.trimmed().isEmpty())
        return {};
    Builder b;
    b.feed(markup);
    removeUnwanted(&b.root);
    return renderChildren(&b.root);
}

QString extractArticle(const QString &page, QString *error) {
    if (page.trimmed().isEmpty()) {
        *error = QStringLiteral("empty document");
        return {};
    }
    Builder b;
    b.feed(page);
    Node *node = findArticle(&b.root);
    if (!node) {
        *error = QStringLiteral("no article content found");
        return {};
    }
    removeUnwanted(node);
    if (textLength(node) < MIN_CONTENT_LENGTH) {
        *error = QStringLiteral("extracted content too short");
        return {};
    }
    return renderChildren(node);
}

}  // namespace html
