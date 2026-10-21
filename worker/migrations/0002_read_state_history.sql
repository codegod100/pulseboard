-- Read state keyed on (feed_url, guid) rather than on the article's surrogate
-- id, so it survives an article being stored again under a new id. Imported
-- data (scripts/import_modal.py) lands here, and every ingest copies matching
-- rows into read_state, so an article read on the old reader is read here too
-- as soon as its feed is fetched.
CREATE TABLE IF NOT EXISTS read_state_history (
  user_did TEXT NOT NULL,
  feed_url TEXT NOT NULL,
  guid TEXT NOT NULL,
  is_read INTEGER NOT NULL DEFAULT 0,
  read_at DATETIME,
  PRIMARY KEY (user_did, feed_url, guid)
);
