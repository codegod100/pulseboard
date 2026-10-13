import 'package:flatkit/flatkit.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
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

    // No url_launcher `Link` here: on the web it puts a DOM anchor in the page
    // for every row, and Flutter repositions all of them each frame while
    // scrolling, which made scrolling visibly slower. Right-click and
    // long-press open our own menu with "Open in new tab" instead.
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
        onSecondaryTap: toggleMenu,
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
                          article.title.isEmpty ? '(untitled)' : article.title,
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

  // `_blank` keeps an installed PWA open when an article is followed.
  void _open() {
    final u = uri;
    if (u != null) launchUrl(u, webOnlyWindowName: '_blank');
  }
}
