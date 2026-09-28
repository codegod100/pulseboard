import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/widgets.dart';

import 'api/client.dart';
import 'models/models.dart';
import 'platform/sign_in.dart';

/// Where the reader is. Override at build time:
///   flutter run --dart-define=PULSEBOARD_BASE_URL=http://10.0.2.2:8080
///
/// 10.0.2.2 is how the Android emulator reaches the host's loopback; a real
/// device needs the machine's LAN address.
///
/// The web build is served *by* the reader, so it leaves this empty and uses
/// relative paths: same origin, which means no CORS preflight and the
/// reader's own cookie on every request.
const kConfiguredBaseUrl = String.fromEnvironment(
  'PULSEBOARD_BASE_URL',
  defaultValue: '',
);

String get kDefaultBaseUrl => kConfiguredBaseUrl.isNotEmpty
    ? kConfiguredBaseUrl
    : (kIsWeb ? '' : 'http://127.0.0.1:8080');

/// Feed list and unread counts, shared across screens.
///
/// Articles are not held here: each screen fetches its own, because the
/// filters differ and a shared list would be wrong for whichever screen did
/// not set them.
class AppState extends ChangeNotifier {
  AppState({
    String? baseUrl,
    PulseboardClient? client,
  }) : client = client ??
            PulseboardClient(
              baseUrl: baseUrl ?? kDefaultBaseUrl,
              onUnauthorized: kIsWeb ? _signInAgain : null,
            );

  /// The session cookie is gone or expired, so every request will keep
  /// failing. The reader serves the login page, and the callback sets a new
  /// cookie and returns to the app.
  ///
  /// There is no "already navigating" latch: several requests failing
  /// together all assign the same URL, which is harmless, whereas a latch
  /// that outlives a navigation that did not happen (or a page restored from
  /// the back/forward cache) silently swallows every later 401.
  static void _signInAgain() => goToSignIn();

  final PulseboardClient client;

  List<Feed> _feeds = const [];
  int _unread = 0;
  int _articlesRevision = 0;
  bool _loading = true;
  String? _error;

  List<Feed> get feeds => _feeds;
  int get unread => _unread;
  int get articlesRevision => _articlesRevision;
  bool get loading => _loading;
  String? get error => _error;

  /// The feed list with an "all feeds" row in front, which is what the
  /// sidebar shows and the server does not send.
  List<Feed> get sidebar => [Feed.all(_unread), ..._feeds];

  Future<void> load() async {
    _loading = true;
    notifyListeners();
    try {
      _feeds = await client.feeds();
      _unread = await client.unreadCount();
      _error = null;
    } on ApiException catch (e) {
      _error = e.message;
    } on Exception {
      _error = 'Could not reach the reader.';
    } finally {
      _loading = false;
      notifyListeners();
    }
  }

  Future<void> addFeed(String url) async {
    await client.addFeed(url);
    await load();
  }

  Future<void> removeFeed(String feedUrl) async {
    await client.removeFeed(feedUrl);
    await load();
  }

  Future<ImportResult> importOpml(String source) async {
    final result = await client.importOpml(source);
    await load();
    return result;
  }

  Future<String> exportOpml() => client.exportOpml();

  Future<RefreshResult> refresh() async {
    final result = await client.refresh();
    await load();
    _articlesRevision++;
    notifyListeners();
    return result;
  }

  Future<void> markAllRead({String feedUrl = ''}) async {
    await client.markAllRead(feedUrl: feedUrl);
    await load();
  }

  /// Nudge the counts after a single article changes, without a round trip.
  void adjustUnread(int delta) {
    _unread = (_unread + delta).clamp(0, 1 << 30);
    notifyListeners();
  }

  @override
  void dispose() {
    client.close();
    super.dispose();
  }
}

class AppScope extends InheritedNotifier<AppState> {
  const AppScope({super.key, required AppState state, required super.child})
    : super(notifier: state);

  static AppState of(BuildContext context) =>
      context.dependOnInheritedWidgetOfExactType<AppScope>()!.notifier!;

  static AppState read(BuildContext context) =>
      context.getInheritedWidgetOfExactType<AppScope>()!.notifier!;
}
