import 'dart:convert';

import 'package:flatkit/flatkit.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:pulseboard_app/src/api/client.dart';
import 'package:pulseboard_app/src/app_state.dart';
import 'package:pulseboard_app/src/screens/home_shell.dart';
import 'package:pulseboard_app/src/theme.dart';
import 'package:pulseboard_app/src/widgets/article_tile.dart';
import 'package:url_launcher/link.dart';

/// Finds a flatkit control by its tooltip, as [find.byTooltip] does for
/// Material ones.
Finder kitTooltip(String message) => find.byWidgetPredicate(
    (w) => w is KitTooltip && w.message == message);

/// A stand-in for the reader, covering the routes the shell touches.
http.Client fakeReader({
  List<String>? seen,
  bool empty = false,
  List<Map<String, Object?>>? articles,
}) {
  return MockClient((req) async {
    seen?.add('${req.method} ${req.url.path}');
    Map<String, String> q = req.url.queryParameters;
    late final Object body;

    switch (req.url.path) {
      case '/feeds':
        if (req.method == 'GET') {
          body = empty
              ? []
              : [
                  {
                    'feed_url': 'https://a.test/feed',
                    'title': 'Feed A',
                    'category': '',
                    'unread': 2,
                    'favicon_url': '',
                  },
                ];
        } else {
          body = {'feed_url': q['url'] ?? '', 'added': 3};
        }
      case '/unread':
        body = {'count': empty ? 0 : 2};
      case '/articles':
        body = articles ?? (empty
            ? []
            : [
                {
                  'id': 1,
                  'feed_url': 'https://a.test/feed',
                  'feed_title': 'Feed A',
                  'title': 'First article',
                  'url': 'https://a.test/1',
                  'author': 'Alice',
                  'summary': '<p>a <b>summary</b></p>',
                  'content': '<p>body</p>',
                  'published': '2026-09-20T10:00:00Z',
                  'is_read': false,
                },
              ]);
      case '/refresh':
        body = {'added': 4, 'errors': []};
      default:
        body = {'ok': true};
    }
    return http.Response(jsonEncode(body), 200,
        headers: {'content-type': 'application/json'});
  });
}

Future<AppState> pump(WidgetTester tester,
    {
      List<String>? seen,
      bool empty = false,
      List<Map<String, Object?>>? articles,
    }) async {
  final state = AppState(
    client: PulseboardClient(
        baseUrl: 'https://reader.test',
        client: fakeReader(seen: seen, empty: empty, articles: articles)),
  );
  await tester.pumpWidget(AppScope(
    state: state,
    child: MaterialApp(
      theme: pulseboardTheme(Brightness.light),
      builder: (context, child) => PulseboardKit(child: child!),
      home: const HomeShell(),
    ),
  ));
  await tester.pumpAndSettle();
  return state;
}

void main() {
  test('a 401 reports the lost session before failing the request', () async {
    var signIns = 0;
    final client = PulseboardClient(
      baseUrl: 'https://reader.test',
      client: MockClient((_) async => http.Response(
          jsonEncode({'error': 'AT Protocol authentication required'}), 401,
          headers: {'content-type': 'application/json'})),
      onUnauthorized: () => signIns++,
    );

    await expectLater(client.articles(), throwsA(isA<ApiException>()));
    await expectLater(client.exportOpml(), throwsA(isA<ApiException>()));
    expect(signIns, 2);
  });

  testWidgets('articles and unread counts load on open', (tester) async {
    final seen = <String>[];
    await pump(tester, seen: seen);

    expect(find.text('First article'), findsOneWidget);
    expect(find.text('Feed A'), findsWidgets);
    // Summaries are HTML in most feeds; the tile shows the text they read as.
    expect(find.textContaining('a summary'), findsOneWidget);
    expect(find.textContaining('<b>'), findsNothing);

    expect(seen, contains('GET /articles'));
    expect(seen, contains('GET /feeds'));
  });

  testWidgets('article links expose a native blank-target anchor',
      (tester) async {
    await pump(tester);

    final link = tester.widget<Link>(
      find.descendant(
        of: find.byType(ArticleTile),
        matching: find.byType(Link),
      ),
    );
    expect(link.uri, Uri.parse('https://a.test/1'));
    expect(link.target, LinkTarget.blank);
  });

  testWidgets('an empty reader says so rather than showing a spinner',
      (tester) async {
    await pump(tester, empty: true);
    expect(find.textContaining('Nothing here'), findsOneWidget);
  });

  testWidgets('the drawer lists feeds with an all-feeds row', (tester) async {
    await pump(tester);
    await tester.tap(find.byTooltip('Open navigation menu'));
    await tester.pumpAndSettle();

    // The server does not send this row; the client adds it.
    expect(find.text('All feeds'), findsOneWidget);
    expect(find.text('Feed A'), findsWidgets);
  });

  testWidgets('refresh reports what arrived', (tester) async {
    final seen = <String>[];
    await pump(tester, seen: seen);

    await tester.tap(kitTooltip('Refresh'));
    await tester.pumpAndSettle();

    expect(seen, contains('POST /refresh'));
    expect(find.textContaining('4 new'), findsOneWidget);
  });

  testWidgets('refresh reloads the visible articles', (tester) async {
    final seen = <String>[];
    final articles = <Map<String, Object?>>[
      {
        'id': 1,
        'feed_url': 'https://a.test/feed',
        'feed_title': 'Feed A',
        'title': 'First article',
        'url': 'https://a.test/1',
        'author': 'Alice',
        'summary': '',
        'content': '',
        'published': '2026-09-20T10:00:00Z',
        'is_read': false,
      },
    ];
    await pump(tester, seen: seen, articles: articles);

    articles
      ..clear()
      ..add({
        'id': 2,
        'feed_url': 'https://a.test/feed',
        'feed_title': 'Feed A',
        'title': 'New article',
        'url': 'https://a.test/2',
        'author': 'Bob',
        'summary': '',
        'content': '',
        'published': '2026-09-24T10:00:00Z',
        'is_read': false,
      });

    await tester.tap(kitTooltip('Refresh'));
    await tester.pumpAndSettle();

    expect(seen.where((request) => request == 'GET /articles'), hasLength(2));
    expect(find.text('First article'), findsNothing);
    expect(find.text('New article'), findsOneWidget);
  });

  testWidgets('a red line separates freshly fetched articles', (tester) async {
    Map<String, Object?> article(int id, String title) => {
          'id': id,
          'feed_url': 'https://a.test/feed',
          'feed_title': 'Feed A',
          'title': title,
          'url': 'https://a.test/$id',
          'author': '',
          'summary': '',
          'content': '',
          'published': '2026-09-2${id}T10:00:00Z',
          'is_read': false,
        };
    final divider = find.byKey(const ValueKey('new-articles-divider'));
    final articles = [article(1, 'Old article')];
    await pump(tester, articles: articles);
    expect(divider, findsNothing);

    articles.insert(0, article(2, 'New article'));
    await tester.tap(kitTooltip('Refresh'));
    await tester.pumpAndSettle();

    expect(divider, findsOneWidget);
    final y = tester.getTopLeft(divider).dy;
    expect(tester.getTopLeft(find.text('New article')).dy, lessThan(y));
    expect(tester.getTopLeft(find.text('Old article')).dy, greaterThan(y));

    // Nothing new on the next fetch, so the line goes away.
    await tester.tap(kitTooltip('Refresh'));
    await tester.pumpAndSettle();
    expect(divider, findsNothing);
  });

  testWidgets('feed management exposes add and removal controls',
      (tester) async {
    await pump(tester);

    await tester.tap(kitTooltip('Manage feeds').first);
    await tester.pumpAndSettle();

    expect(find.text('Manage feeds'), findsOneWidget);
    expect(find.text('Add a subscription'), findsOneWidget);
    expect(find.text('Subscriptions'), findsOneWidget);
    expect(kitTooltip('Remove Feed A'), findsOneWidget);
    expect(find.text('Backup & restore'), findsOneWidget);
  });

  testWidgets('returning from feed management restores the reader',
      (tester) async {
    await pump(tester);

    await tester.tap(kitTooltip('Manage feeds').first);
    await tester.pumpAndSettle();
    await tester.tap(kitTooltip('Back'));
    await tester.pumpAndSettle();

    expect(find.text('First article'), findsOneWidget);
  });

  testWidgets('marking an article read updates the count without a refetch',
      (tester) async {
    final state = await pump(tester);
    expect(state.unread, 2);

    // The per-article button, not the app bar's "Mark all read".
    await tester.tap(kitTooltip('Mark read'));
    await tester.pumpAndSettle();

    // The tile flips locally and the sidebar count follows, rather than the
    // whole list being fetched again.
    expect(state.unread, 1);
  });
}
