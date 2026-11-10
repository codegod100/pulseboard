// Sanitising feed markup and extracting articles from pages.
//
// Ported from the Python server's htmlclean.py (itself from the Nim reader's
// scraper). Two things are deliberate:
//
// * The output is sanitised HTML, not text. Paragraphs, headings, lists, code
//   blocks and images are what make a long article readable.
// * Nothing is trusted. Attributes are allowed rather than denied, `script`,
//   `style`, `iframe` and friends never survive, and links that are not
//   http(s) are flattened to their text, because this is markup from a
//   stranger's server heading for the reader's browser.
#pragma once

#include <QString>

namespace html {

// Run arbitrary HTML through the whitelist. Feed content needs this as much
// as scraped content does.
QString sanitizeFragment(const QString &markup);

// Pull the readable article out of a page. On failure returns an empty
// string and sets `error` (rather than return a nav menu that a caller
// cannot tell apart from a short article).
QString extractArticle(const QString &page, QString *error);

}  // namespace html
