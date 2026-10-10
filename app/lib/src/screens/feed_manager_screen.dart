import 'package:flatkit/flatkit.dart';
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
    final confirmed = await showKitDialog<bool>(
      context,
      (dialogContext) => KitDialog(
        title: 'Remove feed?',
        content: Text('Stop following ${feed.title}?'),
        actions: [
          KitButton(
            'Keep',
            onPressed: () => Navigator.pop(dialogContext, false),
          ),
          KitButton.danger(
            'Remove',
            onPressed: () => Navigator.pop(dialogContext, true),
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
    final source = await showKitDialog<String>(
      context,
      (_) => const _ImportOpmlDialog(),
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
        leading: Center(
          child: KitIconButton(
            Icons.arrow_back,
            tooltip: 'Back',
            onPressed: () => widget.onClose(_changed),
          ),
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
                child: KitTextField(
                  controller: _url,
                  hint: 'https://example.com/feed.xml',
                  onSubmitted: (_) => _add(),
                ),
              ),
              const SizedBox(width: 8),
              if (_adding)
                const SizedBox(
                  width: kitControlHeight,
                  height: kitControlHeight,
                  child: Center(child: KitSpinner()),
                )
              else
                KitButton.primary('Add', icon: Icons.add, onPressed: _add),
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
          KitTextField(
            controller: _filter,
            hint: 'Filter feeds',
            prefixIcon: Icons.search,
            onChanged: (_) => setState(() {}),
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
            KitPanel(
              child: Column(
                children: [
                  for (final (i, feed) in feeds.indexed) ...[
                    if (i > 0) const KitDivider(),
                    Padding(
                      padding: const EdgeInsets.fromLTRB(12, 8, 6, 8),
                      child: Row(
                        children: [
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  feed.title,
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: KitText.heading(context),
                                ),
                                Text(
                                  feed.feedUrl,
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: KitText.dim(context, small: true),
                                ),
                              ],
                            ),
                          ),
                          if (feed.unread > 0)
                            Text(
                              '${feed.unread} unread',
                              style: KitText.dim(context, small: true),
                            ),
                          const SizedBox(width: 4),
                          KitIconButton(
                            Icons.delete_outline,
                            tooltip: 'Remove ${feed.title}',
                            color: c.danger,
                            onPressed: () => _remove(feed),
                          ),
                        ],
                      ),
                    ),
                  ],
                ],
              ),
            ),
          const SizedBox(height: 28),
          Text(
            'Backup & restore',
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              KitButton(
                'Import OPML',
                icon: Icons.upload_file,
                onPressed: _importOpml,
              ),
              KitButton(
                'Copy OPML backup',
                icon: Icons.content_copy,
                onPressed: _exportOpml,
              ),
            ],
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
  Widget build(BuildContext context) {
    final k = KitTheme.of(context);
    final border = OutlineInputBorder(
      borderRadius: BorderRadius.circular(kitRadius),
      borderSide: BorderSide(color: k.border),
    );
    return KitDialog(
      title: 'Import OPML',
      content: TextField(
        controller: _controller,
        autofocus: true,
        minLines: 8,
        maxLines: 14,
        style: KitText.body(context),
        decoration: InputDecoration(
          hintText: 'Paste your OPML here',
          hintStyle: KitText.dim(context),
          filled: true,
          fillColor: k.surface,
          border: border,
          enabledBorder: border,
          focusedBorder: border.copyWith(
            borderSide: BorderSide(color: k.focus, width: 2),
          ),
        ),
      ),
      actions: [
        KitButton('Cancel', onPressed: () => Navigator.pop(context)),
        KitButton.primary(
          'Import',
          onPressed: () => Navigator.pop(context, _controller.text),
        ),
      ],
    );
  }
}
