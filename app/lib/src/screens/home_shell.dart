import 'package:flutter/material.dart';

import '../api/client.dart';
import '../app_state.dart';
import '../models/models.dart';
import '../theme.dart';
import '../widgets/common.dart';
import 'articles_screen.dart';
import 'feed_manager_screen.dart';

/// Articles, with the feed list in a drawer.
///
/// One screen rather than a tab bar: the reader has exactly one thing to
/// look at, and choosing a feed is navigation within it rather than a
/// separate destination.
class HomeShell extends StatefulWidget {
  const HomeShell({super.key});

  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> {
  Feed _selected = Feed.all(0);
  bool _refreshing = false;
  bool _managingFeeds = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      AppScope.read(context).load();
    });
  }

  Future<void> _refresh() async {
    setState(() => _refreshing = true);
    try {
      final result = await AppScope.read(context).refresh();
      if (!mounted) return;
      showToast(
        context,
        result.errors.isEmpty
            ? '${result.added} new'
            : '${result.added} new, ${result.errors.length} feed(s) failed',
      );
    } on ApiException catch (e) {
      if (mounted) showToast(context, e.message);
    } finally {
      if (mounted) setState(() => _refreshing = false);
    }
  }

  Future<void> _markAllRead() async {
    final scope = _selected.isAll ? 'everything' : _selected.title;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('Mark $scope read?'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Mark read'),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    await AppScope.read(context).markAllRead(feedUrl: _selected.feedUrl);
  }

  void _manageFeeds() => setState(() => _managingFeeds = true);

  void _closeManageFeeds(bool changed) {
    if (!changed) {
      setState(() => _managingFeeds = false);
      return;
    }
    final currentExists =
        _selected.isAll ||
        AppScope.read(context).feeds.any((f) => f.feedUrl == _selected.feedUrl);
    setState(() {
      _managingFeeds = false;
      if (!currentExists) _selected = Feed.all(0);
    });
  }

  @override
  Widget build(BuildContext context) {
    if (_managingFeeds) {
      return FeedManagerScreen(onClose: _closeManageFeeds);
    }
    final app = AppScope.of(context);
    final c = PulseboardColors.of(context);

    return Scaffold(
      appBar: AppBar(
        title: Text(_selected.isAll ? 'Pulseboard' : _selected.title),
        actions: [
          IconButton(
            tooltip: 'Manage feeds',
            icon: const Icon(Icons.rss_feed),
            onPressed: _manageFeeds,
          ),
          IconButton(
            tooltip: 'Mark all read',
            icon: const Icon(Icons.done_all),
            onPressed: _markAllRead,
          ),
          IconButton(
            tooltip: 'Refresh',
            icon: _refreshing
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.refresh),
            onPressed: _refreshing ? null : _refresh,
          ),
        ],
      ),
      drawer: Drawer(
        // Flatkit's slate side navigation: light text on the dark aside, with
        // the selected feed picked out in the primary teal.
        child: ListTileTheme(
          textColor: c.asideFg,
          iconColor: c.asideFg,
          selectedColor: c.accent,
          selectedTileColor: Colors.white.withValues(alpha: 0.05),
          child: IconTheme(
            data: IconThemeData(color: c.asideFg, size: 20),
            child: SafeArea(
              child: Column(
                children: [
                  ListTile(
                    contentPadding: const EdgeInsets.fromLTRB(20, 8, 8, 8),
                    title: Text(
                      'FEEDS',
                      style: Theme.of(context).textTheme.labelLarge?.copyWith(
                        color: c.asideFg.withValues(alpha: 0.6),
                        letterSpacing: 1.2,
                      ),
                    ),
                    trailing: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        IconButton(
                          icon: const Icon(Icons.tune),
                          tooltip: 'Manage feeds',
                          color: c.asideFg,
                          onPressed: () {
                            Navigator.of(context).pop();
                            _manageFeeds();
                          },
                        ),
                      ],
                    ),
                  ),
                  if (app.error != null)
                    Padding(
                      padding: const EdgeInsets.all(16),
                      child: Text(
                        app.error!,
                        style: Theme.of(context).textTheme.bodySmall
                            ?.copyWith(color: c.danger),
                      ),
                    ),
                  Expanded(
                    child: ListView(
                      children: [
                        for (final f in app.sidebar)
                          Container(
                            decoration: BoxDecoration(
                              border: Border(
                                left: BorderSide(
                                  color: f.feedUrl == _selected.feedUrl
                                      ? c.accent
                                      : Colors.transparent,
                                  width: 3,
                                ),
                              ),
                            ),
                            child: ListTile(
                              selected: f.feedUrl == _selected.feedUrl,
                              leading: f.isAll
                                  ? const Icon(Icons.inbox_outlined, size: 18)
                                  : FaviconBadge(
                                      url: f.faviconUrl,
                                      seed: f.title,
                                    ),
                              title: Text(
                                f.title,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                              ),
                              trailing: f.unread > 0
                                  ? PulseboardTag(
                                      '${f.unread}',
                                      emphasis: !f.isAll,
                                    )
                                  : null,
                              onTap: () {
                                setState(() => _selected = f);
                                Navigator.of(context).pop();
                              },
                            ),
                          ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
      body: ArticlesScreen(key: ValueKey(_selected.feedUrl), feed: _selected),
    );
  }
}
