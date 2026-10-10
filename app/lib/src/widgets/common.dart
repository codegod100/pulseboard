import 'package:flatkit/flatkit.dart';
import 'package:flutter/material.dart';

import '../api/client.dart';
import '../theme.dart';

/// Small rounded badge for counts and other metadata.
class PulseboardTag extends StatelessWidget {
  const PulseboardTag(this.label, {super.key, this.emphasis = false});

  final String label;
  final bool emphasis;

  @override
  Widget build(BuildContext context) {
    final c = PulseboardColors.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
      decoration: BoxDecoration(
        color: emphasis ? c.accent : KitTheme.of(context).hover,
        borderRadius: BorderRadius.circular(kitRadius),
      ),
      child: Text(
        label,
        style: Theme.of(context).textTheme.bodySmall?.copyWith(
          color: emphasis ? c.accentInk : c.muted,
          fontWeight: FontWeight.w600,
        ),
      ),
    );
  }
}

/// Renders a future with consistent loading, error and empty states.
///
/// Every screen fetches independently, so retry lives here rather than being
/// re-written per screen.
class AsyncView<T> extends StatelessWidget {
  const AsyncView({
    super.key,
    required this.future,
    required this.builder,
    required this.onRetry,
  });

  final Future<T>? future;
  final Widget Function(BuildContext, T) builder;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<T>(
      future: future,
      builder: (context, snap) {
        if (snap.connectionState == ConnectionState.waiting) {
          return const Center(child: KitSpinner(size: 24));
        }
        if (snap.hasError) {
          final err = snap.error;
          return ErrorView(
            message: err is ApiException
                ? err.message
                : 'Something went wrong.',
            onRetry: onRetry,
          );
        }
        return builder(context, snap.data as T);
      },
    );
  }
}

class ErrorView extends StatelessWidget {
  const ErrorView({super.key, required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final c = PulseboardColors.of(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              '!',
              style: TextStyle(
                fontSize: 40,
                fontWeight: FontWeight.w700,
                color: c.danger,
              ),
            ),
            const SizedBox(height: 8),
            Text(message, textAlign: TextAlign.center),
            const SizedBox(height: 16),
            KitButton('Retry', onPressed: onRetry),
          ],
        ),
      ),
    );
  }
}

class EmptyView extends StatelessWidget {
  const EmptyView({super.key, required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Text(
          message,
          textAlign: TextAlign.center,
          style: Theme.of(context).textTheme.bodySmall,
        ),
      ),
    );
  }
}

/// Feed favicon with a letter fallback, so rows keep their rhythm when a site
/// has no icon or the request fails.
class FaviconBadge extends StatelessWidget {
  const FaviconBadge({
    super.key,
    required this.url,
    required this.seed,
    this.size = 18,
  });

  final String url;
  final String seed;
  final double size;

  @override
  Widget build(BuildContext context) {
    final c = PulseboardColors.of(context);
    final letter = seed.isEmpty ? '?' : seed.characters.first.toUpperCase();
    final fallback = Container(
      width: size,
      height: size,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: c.faint,
        borderRadius: BorderRadius.circular(3),
      ),
      child: Text(
        letter,
        style: TextStyle(
          fontSize: size * 0.6,
          fontWeight: FontWeight.w700,
          color: c.bg,
        ),
      ),
    );
    if (url.isEmpty) return fallback;
    return Image.network(
      url,
      width: size,
      height: size,
      errorBuilder: (_, _, _) => fallback,
      loadingBuilder: (_, child, progress) =>
          progress == null ? child : fallback,
    );
  }
}

/// Compact relative time ("3h", "2d") matching the web app's dense metadata rows.
String relativeTime(DateTime? t) {
  if (t == null) return '';
  final d = DateTime.now().difference(t);
  if (d.inMinutes < 1) return 'now';
  if (d.inMinutes < 60) return '${d.inMinutes}m';
  if (d.inHours < 24) return '${d.inHours}h';
  if (d.inDays < 30) return '${d.inDays}d';
  if (d.inDays < 365) return '${(d.inDays / 30).floor()}mo';
  return '${(d.inDays / 365).floor()}y';
}

void showToast(BuildContext context, String message) {
  ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(content: Text(message)));
}

/// Flatten HTML to the text it reads as.
///
/// For summaries and previews only. Article bodies are rendered as HTML,
/// which is safe because the server sanitises every body it sends.
String stripHtml(String html) => html
    .replaceAll(RegExp(r'<[^>]*>'), ' ')
    .replaceAll('&nbsp;', ' ')
    .replaceAll('&amp;', '&')
    .replaceAll('&lt;', '<')
    .replaceAll('&gt;', '>')
    .replaceAll('&quot;', '"')
    .replaceAll(RegExp(r'\s+'), ' ')
    .trim();
