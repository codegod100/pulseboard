import 'package:flatkit/flatkit.dart';
import 'package:flutter/material.dart';

import '../api/client.dart';
import '../app_state.dart';
import '../models/models.dart';
import '../theme.dart';
import '../widgets/article_tile.dart';
import '../widgets/common.dart';

/// The reading list, scoped by the feed selected in the drawer.
class ArticlesScreen extends StatefulWidget {
  const ArticlesScreen({super.key, required this.feed});

  final Feed feed;

  @override
  State<ArticlesScreen> createState() => _ArticlesScreenState();
}

class _ArticlesScreenState extends State<ArticlesScreen> {
  Future<List<Article>>? _future;
  final _searchController = TextEditingController();
  int? _articlesRevision;

  String _status = 'unread';
  String _search = '';

  /// Rows the reader has just acted on, so a tap reflects immediately
  /// without refetching the list.
  final Map<int, Article> _patched = {};

  /// Ids in the list the reader is looking at, so a fetch can tell which
  /// rows are new. Null until a list has loaded for the current filters.
  Set<int>? _shownIds;

  /// Where the red "new since last fetch" line goes: before this row.
  int? _newBoundary;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final revision = AppScope.of(context).articlesRevision;
    if (_articlesRevision == revision) return;
    _articlesRevision = revision;
    _patched.clear();
    _future = _fetch(markNew: true);
  }

  @override
  void didUpdateWidget(ArticlesScreen old) {
    super.didUpdateWidget(old);
    if (old.feed.feedUrl != widget.feed.feedUrl) _load(markNew: false);
  }

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  /// Fetches the list. With [markNew], rows that were not on screen before
  /// are set apart from the ones the reader has already seen; otherwise the
  /// filters changed and every row counts as already seen.
  Future<List<Article>> _fetch({required bool markNew}) async {
    final previous = markNew ? _shownIds : null;
    final items = await AppScope.read(context).client.articles(
      status: _status,
      feedUrl: widget.feed.feedUrl,
      search: _search,
    );
    _shownIds = {for (final a in items) a.id};
    _newBoundary = null;
    if (previous != null) {
      final firstSeen = items.indexWhere((a) => previous.contains(a.id));
      // Only draw the line when something new sits above something seen.
      if (firstSeen > 0) _newBoundary = firstSeen;
    }
    return items;
  }

  void _load({required bool markNew}) {
    setState(() {
      _patched.clear();
      _future = _fetch(markNew: markNew);
    });
  }

  Future<void> _toggleRead(Article a) async {
    final app = AppScope.read(context);
    setState(() => _patched[a.id] = a.copyWith(isRead: !a.isRead));
    app.adjustUnread(a.isRead ? 1 : -1);
    try {
      await app.client.setRead(a.id, read: !a.isRead);
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _patched[a.id] = a);
      app.adjustUnread(a.isRead ? -1 : 1);
      showToast(context, e.message);
    }
  }

  Uri? _articleUri(Article a) {
    final uri = Uri.tryParse(a.url);
    return uri != null && (uri.scheme == 'http' || uri.scheme == 'https')
        ? uri
        : null;
  }

  void _showInvalidLink() {
    showToast(context, 'This article does not have a valid link.');
  }

  Future<void> _markOpened(Article a) async {
    final app = AppScope.read(context);
    if (a.isRead) return;

    setState(() => _patched[a.id] = a.copyWith(isRead: true));
    app.adjustUnread(-1);
    try {
      await app.client.setRead(a.id, read: true);
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _patched[a.id] = a);
      app.adjustUnread(1);
      showToast(context, e.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
          child: Row(
            children: [
              Expanded(
                child: KitTextField(
                  controller: _searchController,
                  hint: 'Search articles',
                  prefixIcon: Icons.search,
                  trailing: _search.isEmpty
                      ? null
                      : KitIconButton.compact(
                          Icons.close,
                          tooltip: 'Clear search',
                          onPressed: () {
                            _searchController.clear();
                            _search = '';
                            _load(markNew: false);
                          },
                        ),
                  onSubmitted: (v) {
                    _search = v.trim();
                    _load(markNew: false);
                  },
                ),
              ),
              const SizedBox(width: 8),
              // Search spans everything, so the status filter is meaningless
              // while one is active.
              if (_search.isEmpty)
                _StatusFilter(
                  status: _status,
                  onChanged: (s) {
                    _status = s;
                    _load(markNew: false);
                  },
                ),
            ],
          ),
        ),
        Expanded(
          child: AsyncView<List<Article>>(
            future: _future,
            onRetry: () => _load(markNew: false),
            builder: (context, items) {
              if (items.isEmpty) {
                return EmptyView(
                  message: _search.isNotEmpty
                      ? 'Nothing matches "$_search".'
                      : 'Nothing here.',
                );
              }
              return RefreshIndicator(
                onRefresh: () async => _load(markNew: true),
                child: ListView.builder(
                  itemCount: items.length,
                  itemBuilder: (context, i) {
                    final a = _patched[items[i].id] ?? items[i];
                    final uri = _articleUri(a);
                    final tile = ArticleTile(
                      article: a,
                      uri: uri,
                      onToggleRead: () => _toggleRead(a),
                      onTap: uri == null
                          ? _showInvalidLink
                          : () => _markOpened(a),
                    );
                    if (i != _newBoundary) return tile;
                    return Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [const _NewArticlesDivider(), tile],
                    );
                  },
                ),
              );
            },
          ),
        ),
      ],
    );
  }
}

/// The red line between freshly fetched articles and the ones already shown.
class _NewArticlesDivider extends StatelessWidget {
  const _NewArticlesDivider();

  @override
  Widget build(BuildContext context) {
    return Container(
      key: const ValueKey('new-articles-divider'),
      height: 2,
      color: PulseboardColors.of(context).danger,
    );
  }
}

class _StatusFilter extends StatelessWidget {
  const _StatusFilter({required this.status, required this.onChanged});

  final String status;
  final ValueChanged<String> onChanged;

  @override
  Widget build(BuildContext context) => KitSegmented<String>(
    segments: const [('unread', 'Unread'), ('all', 'All'), ('read', 'Read')],
    selected: status,
    onChanged: onChanged,
  );
}
