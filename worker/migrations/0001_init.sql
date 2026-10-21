-- The reader's schema, on D1.
--
-- One database rather than the two attached SQLite files the Nim reader used:
-- D1 has no ATTACH, and the reason for the split (vacuuming the article store
-- on its own) is D1's problem now, not ours.

CREATE TABLE IF NOT EXISTS users (
  did TEXT PRIMARY KEY,
  indexed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS web_sessions (
  token TEXT PRIMARY KEY,
  user_did TEXT NOT NULL,
  expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_web_sessions_expiry ON web_sessions(expires_at);

-- AT Protocol OAuth requests between /auth/authorize and /auth/callback. The
-- row holds the PKCE verifier and the DPoP key for one sign-in, and is deleted
-- when the callback consumes it.
CREATE TABLE IF NOT EXISTS oauth_states (
  state TEXT PRIMARY KEY,
  data TEXT NOT NULL,
  expires_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS feeds (
  feed_url TEXT PRIMARY KEY,
  title TEXT,
  site_url TEXT,
  description TEXT,
  feed_type TEXT,
  last_fetched_at DATETIME,
  last_error TEXT,
  subscriber_count INTEGER NOT NULL DEFAULT 0,
  error_count INTEGER NOT NULL DEFAULT 0,
  favicon_url TEXT
);

CREATE TABLE IF NOT EXISTS subscriptions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_did TEXT NOT NULL,
  feed_url TEXT NOT NULL,
  title TEXT,
  category TEXT,
  added_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(user_did, feed_url)
);
CREATE INDEX IF NOT EXISTS idx_subscriptions_feed_user ON subscriptions(feed_url, user_did);

CREATE TABLE IF NOT EXISTS articles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  feed_url TEXT NOT NULL,
  guid TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  url TEXT,
  author TEXT,
  summary TEXT,
  content TEXT,
  full_content TEXT,
  published DATETIME,
  updated DATETIME,
  fetched_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(feed_url, guid)
);
CREATE INDEX IF NOT EXISTS idx_articles_url ON articles(url);
CREATE INDEX IF NOT EXISTS idx_articles_feed_published ON articles(feed_url, published);

CREATE TABLE IF NOT EXISTS read_state (
  user_did TEXT NOT NULL,
  article_id INTEGER NOT NULL,
  is_read INTEGER NOT NULL DEFAULT 0,
  read_at DATETIME,
  PRIMARY KEY (user_did, article_id)
);

CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(
  title, summary, content, author, content=articles, content_rowid=id
);
CREATE TRIGGER IF NOT EXISTS articles_ai AFTER INSERT ON articles BEGIN
  INSERT INTO articles_fts(rowid, title, summary, content, author)
  VALUES (new.id, new.title, new.summary, new.content, new.author);
END;
CREATE TRIGGER IF NOT EXISTS articles_ad AFTER DELETE ON articles BEGIN
  INSERT INTO articles_fts(articles_fts, rowid, title, summary, content, author)
  VALUES ('delete', old.id, old.title, old.summary, old.content, old.author);
END;
CREATE TRIGGER IF NOT EXISTS articles_au AFTER UPDATE OF title, summary, content, author ON articles BEGIN
  INSERT INTO articles_fts(articles_fts, rowid, title, summary, content, author)
  VALUES ('delete', old.id, old.title, old.summary, old.content, old.author);
  INSERT INTO articles_fts(rowid, title, summary, content, author)
  VALUES (new.id, new.title, new.summary, new.content, new.author);
END;
