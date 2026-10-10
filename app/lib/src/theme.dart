import 'package:flatkit/flatkit.dart';
import 'package:flutter/material.dart';

/// Pulseboard's look comes from flatkit: its [KitColors] palette, its flat
/// controls, and a Material theme with every ripple, highlight and page
/// transition turned off. [PulseboardColors] maps the kit's palette onto the
/// names the app's own widgets use.
class PulseboardColors extends ThemeExtension<PulseboardColors> {
  const PulseboardColors({
    required this.bg,
    required this.fg,
    required this.surface,
    required this.border,
    required this.muted,
    required this.faint,
    required this.accent,
    required this.accentInk,
    required this.danger,
  });

  factory PulseboardColors.fromKit(KitColors k) => PulseboardColors(
    bg: k.background,
    fg: k.text,
    surface: k.surface,
    border: k.border,
    muted: k.textDim,
    faint: k.borderStrong,
    accent: k.accent,
    accentInk: k.onAccent,
    danger: k.danger,
  );

  final Color bg;
  final Color fg;
  final Color surface;
  final Color border;
  final Color muted;
  final Color faint;
  final Color accent;
  final Color accentInk;
  final Color danger;

  static PulseboardColors of(BuildContext context) =>
      Theme.of(context).extension<PulseboardColors>()!;

  @override
  PulseboardColors copyWith() => this;

  @override
  PulseboardColors lerp(ThemeExtension<PulseboardColors>? other, double t) =>
      t < 0.5 ? this : (other as PulseboardColors? ?? this);
}

KitColors kitColors(Brightness brightness) =>
    brightness == Brightness.dark ? KitColors.dark : KitColors.light;

ThemeData pulseboardTheme(Brightness brightness) {
  final k = kitColors(brightness);
  final c = PulseboardColors.fromKit(k);
  final base = KitTheme.material(k);

  TextStyle text(
    double size, {
    FontWeight weight = FontWeight.w400,
    Color? color,
    double height = 1.4,
  }) => TextStyle(
    fontSize: size,
    fontWeight: weight,
    color: color ?? k.text,
    height: height,
  );

  return base.copyWith(
    dividerColor: k.border,
    extensions: [c],
    textTheme: base.textTheme.copyWith(
      headlineSmall: text(20, weight: FontWeight.w600),
      titleMedium: text(14, weight: FontWeight.w600),
      bodyLarge: text(16, weight: FontWeight.w600, height: 1.35),
      bodyMedium: text(14),
      bodySmall: text(12, color: k.textDim),
      labelLarge: text(13, weight: FontWeight.w500),
    ),
    appBarTheme: AppBarTheme(
      backgroundColor: k.surface,
      foregroundColor: k.text,
      elevation: 0,
      scrolledUnderElevation: 0,
      surfaceTintColor: Colors.transparent,
      centerTitle: false,
      shape: Border(bottom: BorderSide(color: k.border)),
      titleTextStyle: text(16, weight: FontWeight.w600),
    ),
    iconTheme: IconThemeData(color: k.text, size: 18),
    progressIndicatorTheme: ProgressIndicatorThemeData(color: k.accent),
    drawerTheme: DrawerThemeData(
      backgroundColor: k.surface,
      shape: Border(right: BorderSide(color: k.border)),
    ),
    listTileTheme: ListTileThemeData(
      dense: true,
      contentPadding: const EdgeInsets.symmetric(horizontal: 12),
      selectedColor: k.text,
      selectedTileColor: k.pressed,
      titleTextStyle: text(14, weight: FontWeight.w500),
      subtitleTextStyle: text(12, color: k.textDim),
    ),
    snackBarTheme: SnackBarThemeData(
      backgroundColor: k.text,
      contentTextStyle: text(13, color: k.background),
      behavior: SnackBarBehavior.floating,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(kitRadius),
      ),
    ),
  );
}

/// Puts flatkit's colours, matching the app's current brightness, and a
/// Material surface above the navigator, so kit dialogs and menus pushed
/// onto it get the same colours and text style as the screens.
class PulseboardKit extends StatelessWidget {
  const PulseboardKit({super.key, required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    final k = kitColors(Theme.of(context).brightness);
    return KitTheme(
      colors: k,
      child: Material(color: k.background, child: child),
    );
  }
}
