"""The login and error pages the Worker renders itself. They sit in front of
the app, so they share one card that looks like the client they lead into."""

from html import escape

STYLE = """
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


def page(title: str, body: str) -> str:
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(title)}</title>"
        '<link rel="icon" href="/favicon.png">'
        f"<style>{STYLE}</style></head><body><main>"
        '<h1 class="brand"><img src="/favicon.png" alt="">Pulseboard</h1>'
        f"{body}</main></body></html>"
    )


def login_page(identity: str = "", error: str = "") -> str:
    if error:
        body = f'<p class="error" role="alert">{escape(error)}</p>'
    else:
        body = "<p>Sign in with your Bluesky or other AT Protocol account.</p>"
    body += f"""<form action="/auth/authorize" method="get">
<label for="identity">Handle</label>
<input id="identity" name="identity" required autofocus autocapitalize="none"
spellcheck="false" placeholder="you.bsky.social" autocomplete="username" value="{escape(identity, quote=True)}">
<button type="submit">Continue</button></form>
<small>Only your DID is kept. Access to your account is revoked right after
sign-in.</small>"""
    return page("Sign in to Pulseboard", body)


def retry_page() -> str:
    return page(
        "Sign in again",
        "<p>That sign-in expired or was cancelled.</p>"
        '<a class="button" href="/auth/login">Sign in again</a>',
    )
