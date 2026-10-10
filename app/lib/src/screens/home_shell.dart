import 'package:flatkit/flatkit.dart';
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
    final ok = await showKitDialog<bool>(
      context,
      (ctx) => KitDialog(
        title: 'Mark $scope read?',
        content: const SizedBox.shrink(),
        actions: [
          KitButton('Cancel', onPressed: () => Navigator.pop(ctx, false)),
          KitButton.primary(
            'Mark read',
            onPressed: () => Navigator.pop(ctx, true),
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
          KitIconButton(
            Icons.rss_feed,
            tooltip: 'Manage feeds',
            onPressed: _manageFeeds,
          ),
          KitIconButton(
            Icons.done_all,
            tooltip: 'Mark all read',
            onPressed: _markAllRead,
          ),
          if (_refreshing)
            const SizedBox(
              width: kitControlHeight,
              child: Center(child: KitSpinner()),
            )
          else
            KitIconButton(
              Icons.refresh,
              tooltip: 'Refresh',
              onPressed: _refresh,
            ),
          const SizedBox(width: 8),
        ],
      ),
      drawer: Drawer(
        child: SafeArea(
          child: Column(
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 12, 8, 8),
                child: Row(
                  children: [
                    Expanded(
                      child: Text('Feeds', style: KitText.heading(context)),
                    ),
                    KitIconButton(
                      Icons.tune,
                      tooltip: 'Manage feeds',
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
                  padding: const EdgeInsets.symmetric(horizontal: 8),
                  children: [
                    for (final f in app.sidebar)
                      _FeedRow(
                        feed: f,
                        selected: f.feedUrl == _selected.feedUrl,
                        onPressed: () {
                          setState(() => _selected = f);
                          Navigator.of(context).pop();
                        },
                      ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
      body: ArticlesScreen(key: ValueKey(_selected.feedUrl), feed: _selected),
    );
  }
}

/// One feed in the drawer: highlighted the moment the pointer is over it,
/// with the selected feed marked by the accent bar.
class _FeedRow extends StatelessWidget {
  const _FeedRow({
    required this.feed,
    required this.selected,
    required this.onPressed,
  });

  final Feed feed;
  final bool selected;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    final k = KitTheme.of(context);
    return Pressable(
      onPressed: onPressed,
      builder: (context, s) => Container(
        height: 36,
        margin: const EdgeInsets.only(bottom: 1),
        padding: const EdgeInsets.symmetric(horizontal: 10),
        decoration: BoxDecoration(
          color: selected || s.pressed
              ? k.pressed
              : (s.hovered ? k.hover : const Color(0x00000000)),
          borderRadius: BorderRadius.circular(kitRadius),
          border: s.focused ? Border.all(color: k.focus, width: 2) : null,
        ),
        child: Row(
          children: [
            Container(
              width: 3,
              height: 16,
              decoration: BoxDecoration(
                color: selected ? k.accent : const Color(0x00000000),
                borderRadius: BorderRadius.circular(2),
              ),
            ),
            const SizedBox(width: 8),
            if (feed.isAll)
              Icon(Icons.inbox_outlined, size: 18, color: k.text)
            else
              FaviconBadge(url: feed.faviconUrl, seed: feed.title),
            const SizedBox(width: 10),
            Expanded(
              child: Text(
                feed.title,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: KitText.body(context).copyWith(
                  fontWeight: selected ? FontWeight.w600 : FontWeight.w400,
                ),
              ),
            ),
            if (feed.unread > 0)
              PulseboardTag('${feed.unread}', emphasis: !feed.isAll),
          ],
        ),
      ),
    );
  }
}
