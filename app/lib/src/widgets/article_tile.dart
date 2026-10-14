import 'package:flatkit/flatkit.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:url_launcher/link.dart';
import 'package:url_launcher/url_launcher.dart';

import '../models/models.dart';
import '../theme.dart';
import 'common.dart';

/// One row in the article list: a bold title and dim excerpt under a quiet
/// metadata line. Hover and press tint the row at once, flatkit-style.
class ArticleTile extends StatelessWidget {
  const ArticleTile({
    super.key,
    required this.article,
    required this.uri,
    required this.onTap,
    this.onToggleRead,
  });

  final Article article;
  final Uri? uri;
  final VoidCallback onTap;
  final VoidCallback? onToggleRead;

  @override
  Widget build(BuildContext context) {
    final c = PulseboardColors.of(context);
    final text = Theme.of(context).textTheme;
    final read = article.isRead;

    // A url_launcher `Link` on every row puts a DOM anchor in the page for
    // each one, and Flutter repositions all of them each frame while
    // scrolling, which made scrolling visibly slower. So on the web only the
    // row under the mouse gets a Link, laid over its text: the browser's own
    // right-click menu (Open link in new tab, Copy link address) then works,
    // with at most one anchor in the page. Long-press opens our own menu.
    return KitMenu(
      items: () => [
        KitMenuItem('Open in new tab', onSelected: uri == null ? null : _open),
        KitMenuItem(
          'Copy link',
          onSelected: uri == null
              ? null
              : () => Clipboard.setData(ClipboardData(text: uri.toString())),
        ),
      ],
      builder: (context, toggleMenu, _) => GestureDetector(
        // On the web the browser shows its link menu on right-click, so ours
        // would only stack under it.
        onSecondaryTap: kIsWeb ? null : toggleMenu,
        onLongPress: toggleMenu,
        child: Pressable(
          onPressed: () {
            onTap();
            _open();
          },
          builder: (context, s) => Container(
            padding: const EdgeInsets.fromLTRB(20, 18, 10, 18),
            decoration: BoxDecoration(
              color: s.pressed
                  ? KitTheme.of(context).pressed
                  : (s.hovered ? KitTheme.of(context).hover : null),
              border: Border(bottom: BorderSide(color: c.border, width: 1)),
            ),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.center,
              children: [
                Expanded(
                  child: _withHoverLink(
                    hovered: s.hovered,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            Container(
                              width: 7,
                              height: 7,
                              decoration: BoxDecoration(
                                color: read ? c.faint : c.accent,
                                shape: BoxShape.circle,
                              ),
                            ),
                            const SizedBox(width: 7),
                            Expanded(
                              child: Text(
                                article.feedTitle,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: text.bodySmall?.copyWith(
                                  letterSpacing: 0.25,
                                ),
                              ),
                            ),
                            if (article.published != null) ...[
                              const SizedBox(width: 12),
                              Text(
                                relativeTime(article.published),
                                style: text.bodySmall?.copyWith(
                                  letterSpacing: 0.25,
                                ),
                              ),
                            ],
                          ],
                        ),
                        const SizedBox(height: 10),
                        Opacity(
                          opacity: read ? 0.55 : 1,
                          child: Text(
                            article.title.isEmpty
                                ? '(untitled)'
                                : article.title,
                            maxLines: 3,
                            overflow: TextOverflow.ellipsis,
                            style: text.bodyLarge?.copyWith(
                              fontWeight: read
                                  ? FontWeight.w400
                                  : FontWeight.w600,
                              height: 1.35,
                            ),
                          ),
                        ),
                        if (article.summary.isNotEmpty) ...[
                          const SizedBox(height: 9),
                          Text(
                            summaryPreview(article.summary),
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                            style: text.bodyMedium?.copyWith(
                              color: read
                                  ? c.muted.withValues(alpha: 0.78)
                                  : c.muted,
                              height: 1.5,
                            ),
                          ),
                        ],
                      ],
                    ),
                  ),
                ),
                if (onToggleRead != null)
                  KitIconButton(
                    read ? Icons.mark_email_unread_outlined : Icons.check,
                    tooltip: read ? 'Mark unread' : 'Mark read',
                    color: c.muted,
                    onPressed: onToggleRead,
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  /// Lays an invisible Link over [child] while the mouse is on the row. It
  /// never follows the link itself (its followLink is not called), so a
  /// left click still goes through Pressable; it is only there so the
  /// browser sees a real anchor under the pointer.
  Widget _withHoverLink({required bool hovered, required Widget child}) {
    final u = uri;
    return Stack(
      fit: StackFit.passthrough,
      children: [
        child,
        if (kIsWeb && hovered && u != null)
          Positioned.fill(
            child: Link(
              uri: u,
              target: LinkTarget.blank,
              builder: (context, _) => const SizedBox.expand(),
            ),
          ),
      ],
    );
  }

  // `_blank` keeps an installed PWA open when an article is followed.
  void _open() {
    final u = uri;
    if (u != null) launchUrl(u, webOnlyWindowName: '_blank');
  }
}
