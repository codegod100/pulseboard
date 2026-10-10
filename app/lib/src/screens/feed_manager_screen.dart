import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api/client.dart';
import '../app_state.dart';
import '../models/models.dart';
import '../theme.dart';
import '../widgets/common.dart';

/// A dedicated, visible place to maintain subscriptions and OPML backups.
class FeedManagerScreen extends StatefulWidget {
  const FeedManagerScreen({super.key, required this.onClose});

  final ValueChanged<bool> onClose;

  @override
  State<FeedManagerScreen> createState() => _FeedManagerScreenState();
}

class _FeedManagerScreenState extends State<FeedManagerScreen> {
  final _url = TextEditingController();
  final _filter = TextEditingController();
  bool _adding = false;
  bool _changed = false;

  @override
  void dispose() {
    _url.dispose();
    _filter.dispose();
    super.dispose();
  }

  Future<void> _add() async {
    final url = _url.text.trim();
    if (url.isEmpty || _adding) return;
    setState(() => _adding = true);
    try {
      await AppScope.read(context).addFeed(url);
      _url.clear();
      _changed = true;
      if (mounted) showToast(context, 'Feed added');
    } on ApiException catch (e) {
      if (mounted) showToast(context, e.message);
    } finally {
      if (mounted) setState(() => _adding = false);
    }
  }

  Future<void> _remove(Feed feed) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Remove feed?'),
        content: Text('Stop following ${feed.title}?'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('Keep'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('Remove'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    try {
      await AppScope.read(context).removeFeed(feed.feedUrl);
      _changed = true;
      if (mounted) showToast(context, 'Feed removed');
    } on ApiException catch (e) {
      if (mounted) showToast(context, e.message);
    }
  }

  Future<void> _importOpml() async {
    final source = await showDialog<String>(
      context: context,
      builder: (_) => const _ImportOpmlDialog(),
    );
    if (source == null || source.trim().isEmpty || !mounted) return;
    try {
      final result = await AppScope.read(context).importOpml(source);
      _changed = result.added > 0;
      if (mounted) {
        showToast(
          context,
          '${result.added} feed(s) added${result.errors.isEmpty ? '' : ', ${result.errors.length} failed'}',
        );
      }
    } on ApiException catch (e) {
      if (mounted) showToast(context, e.message);
    }
  }

  Future<void> _exportOpml() async {
    try {
      final opml = await AppScope.read(context).exportOpml();
      await Clipboard.setData(ClipboardData(text: opml));
      if (mounted) showToast(context, 'OPML backup copied to clipboard');
    } on ApiException catch (e) {
      if (mounted) showToast(context, e.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final c = PulseboardColors.of(context);
    final filter = _filter.text.trim().toLowerCase();
    final feeds = app.feeds.where((feed) {
      return filter.isEmpty ||
          feed.title.toLowerCase().contains(filter) ||
          feed.feedUrl.toLowerCase().contains(filter);
    }).toList();

    return Scaffold(
      appBar: AppBar(
        leading: IconButton(
          tooltip: 'Back',
          icon: const Icon(Icons.arrow_back),
          onPressed: () => widget.onClose(_changed),
        ),
        title: const Text('Manage feeds'),
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(
            'Add a subscription',
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 8),
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: TextField(
                  controller: _url,
                  keyboardType: TextInputType.url,
                  textInputAction: TextInputAction.done,
                  onSubmitted: (_) => _add(),
                  decoration: const InputDecoration(
                    hintText: 'https://example.com/feed.xml',
                  ),
                ),
              ),
              const SizedBox(width: 8),
              FilledButton.icon(
                onPressed: _adding ? null : _add,
                icon: _adding
                    ? const SizedBox(
                        width: 16,
                        height: 16,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.add),
                label: const Text('Add'),
              ),
            ],
          ),
          const SizedBox(height: 28),
          Row(
            children: [
              Text(
                'Subscriptions',
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const Spacer(),
              Text(
                '${app.feeds.length}',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ],
          ),
          const SizedBox(height: 8),
          TextField(
            controller: _filter,
            onChanged: (_) => setState(() {}),
            decoration: const InputDecoration(
              prefixIcon: Icon(Icons.search),
              hintText: 'Filter feeds',
            ),
          ),
          const SizedBox(height: 8),
          if (feeds.isEmpty)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 32),
              child: Text(
                filter.isEmpty ? 'No subscriptions yet.' : 'No matching feeds.',
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.bodySmall,
              ),
            )
          else
            ...feeds.map(
              (feed) => Container(
                margin: const EdgeInsets.only(bottom: 8),
                child: Material(
                  color: c.surface,
                  shape: RoundedRectangleBorder(
                    borderRadius: kBorderRadius,
                    side: BorderSide(color: c.border),
                  ),
                  child: ListTile(
                    contentPadding: const EdgeInsets.only(left: 14, right: 4),
                    title: Text(
                      feed.title,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                    subtitle: Text(
                      feed.feedUrl,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                    trailing: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        if (feed.unread > 0) Text('${feed.unread} unread'),
                        IconButton(
                          tooltip: 'Remove ${feed.title}',
                          icon: Icon(Icons.delete_outline, color: c.danger),
                          onPressed: () => _remove(feed),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
          const SizedBox(height: 28),
          Text(
            'Backup & restore',
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            onPressed: _importOpml,
            icon: const Icon(Icons.upload_file),
            label: const Text('Import OPML'),
          ),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            onPressed: _exportOpml,
            icon: const Icon(Icons.content_copy),
            label: const Text('Copy OPML backup'),
          ),
        ],
      ),
    );
  }
}

class _ImportOpmlDialog extends StatefulWidget {
  const _ImportOpmlDialog();

  @override
  State<_ImportOpmlDialog> createState() => _ImportOpmlDialogState();
}

class _ImportOpmlDialogState extends State<_ImportOpmlDialog> {
  final _controller = TextEditingController();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: const Text('Import OPML'),
    content: TextField(
      controller: _controller,
      autofocus: true,
      minLines: 8,
      maxLines: 14,
      decoration: const InputDecoration(hintText: 'Paste your OPML here'),
    ),
    actions: [
      TextButton(
        onPressed: () => Navigator.pop(context),
        child: const Text('Cancel'),
      ),
      TextButton(
        onPressed: () => Navigator.pop(context, _controller.text),
        child: const Text('Import'),
      ),
    ],
  );
}
