-- HTTP validators from the last successful fetch, sent back as If-None-Match
-- and If-Modified-Since so an unchanged feed costs a 304 instead of a download
-- and a parse.
ALTER TABLE feeds ADD COLUMN etag TEXT;
ALTER TABLE feeds ADD COLUMN last_modified TEXT;
