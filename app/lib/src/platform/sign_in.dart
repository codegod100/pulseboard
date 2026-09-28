// Sends the browser to the reader's login page.
//
// Only the web build has a page to leave; elsewhere this does nothing.
export 'sign_in_stub.dart' if (dart.library.js_interop) 'sign_in_web.dart';
