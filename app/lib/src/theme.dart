import 'package:flutter/material.dart';

/// Pulseboard follows the Flatkit dashboard kit: a cool grey page with white
/// cards, hairline borders and a soft 1px shadow, small rounded corners, a
/// slate (#2e3e4e) side navigation and Flatkit's teal primary. Type is the
/// kit's Source Sans stack throughout; small labels are uppercase and spaced.
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
    required this.aside,
    required this.asideFg,
  });

  /// Page background.
  final Color bg;
  final Color fg;

  /// Card, field and menu background.
  final Color surface;

  /// Hairline border on cards and fields.
  final Color border;
  final Color muted;
  final Color faint;
  final Color accent;
  final Color accentInk;
  final Color danger;

  /// Side navigation background and text.
  final Color aside;
  final Color asideFg;

  static const light = PulseboardColors(
    bg: Color(0xFFF1F2F4),
    fg: Color(0xFF3B4D5F),
    surface: Color(0xFFFFFFFF),
    border: Color(0x3378828C),
    muted: Color(0xFF8A96A3),
    faint: Color(0xFFDDE2E7),
    accent: Color(0xFF0CC2AA),
    accentInk: Color(0xFFFFFFFF),
    danger: Color(0xFFF44455),
    aside: Color(0xFF2E3E4E),
    asideFg: Color(0xFFE8ECEF),
  );

  static const dark = PulseboardColors(
    bg: Color(0xFF2A2B3C),
    fg: Color(0xFFDCE1E6),
    surface: Color(0xFF2E3E4E),
    border: Color(0x33FFFFFF),
    muted: Color(0xFF94A2B0),
    faint: Color(0xFF45566A),
    accent: Color(0xFF0CC2AA),
    accentInk: Color(0xFFFFFFFF),
    danger: Color(0xFFF44455),
    aside: Color(0xFF232433),
    asideFg: Color(0xFFDCE1E6),
  );

  static PulseboardColors of(BuildContext context) =>
      Theme.of(context).extension<PulseboardColors>()!;

  @override
  PulseboardColors copyWith() => this;

  @override
  PulseboardColors lerp(ThemeExtension<PulseboardColors>? other, double t) =>
      t < 0.5 ? this : (other as PulseboardColors? ?? this);
}

/// Flatkit's corner radius for cards, buttons, fields and dialogs.
const kRadius = 4.0;
const kBorderRadius = BorderRadius.all(Radius.circular(kRadius));

/// Flatkit's card shadow: a single soft pixel under the hairline border.
const kCardShadow = [
  BoxShadow(color: Color(0x0D000000), offset: Offset(0, 1), blurRadius: 1),
];

/// Flatkit's typeface, bundled under fonts/, and the stack behind it.
const kSans = 'Source Sans 3';
const kSansFallback = <String>[
  'Source Sans Pro',
  'Helvetica Neue',
  'Helvetica',
  'Arial',
  'sans-serif',
];

ThemeData pulseboardTheme(Brightness brightness) {
  final c = brightness == Brightness.dark
      ? PulseboardColors.dark
      : PulseboardColors.light;

  TextStyle sans(
    double size, {
    FontWeight weight = FontWeight.w400,
    Color? color,
    double height = 1.5,
  }) => TextStyle(
    fontFamily: kSans,
    fontFamilyFallback: kSansFallback,
    fontSize: size,
    fontWeight: weight,
    color: color ?? c.fg,
    height: height,
  );

  final fieldBorder = OutlineInputBorder(
    borderRadius: kBorderRadius,
    borderSide: BorderSide(color: c.border),
  );

  return ThemeData(
    brightness: brightness,
    fontFamily: kSans,
    scaffoldBackgroundColor: c.bg,
    canvasColor: c.bg,
    dividerColor: c.border,
    colorScheme: ColorScheme.fromSeed(
      seedColor: c.accent,
      brightness: brightness,
    ).copyWith(surface: c.surface, primary: c.accent, error: c.danger),
    extensions: [c],
    textTheme: TextTheme(
      displaySmall: sans(28, weight: FontWeight.w300, height: 1.3),
      headlineSmall: sans(22, weight: FontWeight.w400, height: 1.3),
      titleMedium: sans(15, weight: FontWeight.w600),
      bodyLarge: sans(17, weight: FontWeight.w600, height: 1.4),
      bodyMedium: sans(14),
      bodySmall: sans(12, color: c.muted),
      labelLarge: sans(
        12,
        weight: FontWeight.w600,
      ).copyWith(letterSpacing: 0.6),
    ),
    appBarTheme: AppBarTheme(
      backgroundColor: c.surface,
      foregroundColor: c.fg,
      elevation: 1,
      scrolledUnderElevation: 1,
      shadowColor: const Color(0x14000000),
      surfaceTintColor: Colors.transparent,
      centerTitle: false,
      titleTextStyle: sans(17, weight: FontWeight.w600),
    ),
    iconTheme: IconThemeData(color: c.fg, size: 20),
    visualDensity: VisualDensity.standard,
    progressIndicatorTheme: ProgressIndicatorThemeData(color: c.accent),
    dividerTheme: DividerThemeData(color: c.border, thickness: 1, space: 1),
    drawerTheme: DrawerThemeData(
      backgroundColor: c.aside,
      shape: const RoundedRectangleBorder(),
    ),
    dialogTheme: DialogThemeData(
      backgroundColor: c.surface,
      surfaceTintColor: Colors.transparent,
      shape: const RoundedRectangleBorder(borderRadius: kBorderRadius),
      titleTextStyle: sans(18, weight: FontWeight.w600),
    ),
    listTileTheme: ListTileThemeData(
      contentPadding: const EdgeInsets.symmetric(horizontal: 16),
      minVerticalPadding: 10,
      selectedColor: c.accent,
      selectedTileColor: c.accent.withValues(alpha: 0.08),
      titleTextStyle: sans(14, weight: FontWeight.w600),
      subtitleTextStyle: sans(12, color: c.muted),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: c.accent,
        foregroundColor: c.accentInk,
        disabledBackgroundColor: c.faint,
        disabledForegroundColor: c.muted,
        shape: const RoundedRectangleBorder(borderRadius: kBorderRadius),
        padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 16),
        textStyle: sans(13, weight: FontWeight.w600),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: c.fg,
        backgroundColor: c.surface,
        side: BorderSide(color: c.border),
        shape: const RoundedRectangleBorder(borderRadius: kBorderRadius),
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        textStyle: sans(13, weight: FontWeight.w600),
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        foregroundColor: c.accent,
        shape: const RoundedRectangleBorder(borderRadius: kBorderRadius),
        textStyle: sans(13, weight: FontWeight.w600),
      ),
    ),
    snackBarTheme: SnackBarThemeData(
      backgroundColor: c.aside,
      contentTextStyle: sans(13, color: c.asideFg),
      behavior: SnackBarBehavior.floating,
      shape: const RoundedRectangleBorder(borderRadius: kBorderRadius),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: c.surface,
      border: fieldBorder,
      enabledBorder: fieldBorder,
      focusedBorder: fieldBorder.copyWith(
        borderSide: BorderSide(color: c.accent),
      ),
      hintStyle: sans(14, color: c.muted),
      contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 13),
    ),
  );
}
