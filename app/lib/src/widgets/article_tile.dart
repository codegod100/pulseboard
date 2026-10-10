import 'package:flutter/material.dart';
import 'package:url_launcher/link.dart';

import '../models/models.dart';
import '../theme.dart';
import 'common.dart';

/// One row in the article list: a bold title and muted excerpt under a quiet
/// metadata line, separated by Flatkit's hairline dividers.
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

    return Link(
      // Keep a real anchor in the web DOM so the browser can offer its native
      // link context menu, including "Open link in new tab". `_blank` also
      // ensures a normal click leaves an installed PWA open.
      uri: uri,
      target: LinkTarget.blank,
      builder: (context, followLink) => Material(
        color: c.surface,
        child: InkWell(
          onTap: () {
            onTap();
            followLink?.call();
          },
          child: Container(
            padding: const EdgeInsets.fromLTRB(20, 18, 10, 18),
            decoration: BoxDecoration(
              border: Border(bottom: BorderSide(color: c.border)),
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
                          stripHtml(article.summary),
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
                  IconButton(
                    visualDensity: VisualDensity.compact,
                    tooltip: read ? 'Mark unread' : 'Mark read',
                    icon: Icon(
                      read ? Icons.mark_email_unread_outlined : Icons.check,
                      size: 18,
                      color: c.muted,
                    ),
                    onPressed: onToggleRead,
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
