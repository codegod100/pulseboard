import 'dart:js_interop';

@JS('window.location.assign')
external void _assign(String url);

/// A plain same-tab navigation. url_launcher's `_self` goes through
/// `window.open(url, '_self', 'noopener,noreferrer')`, and a browser that
/// honours `noopener` by opening a new window blocks it as a popup: the tab
/// stayed put and the reader was left with an "authentication required" toast.
void goToSignIn() => _assign('/auth/login');
