import 'package:flutter/material.dart';

/// Design tokens exported from Figma (file lPyn5YG33z3lPlWiaKjsK9, page "Peel").
class PeelColors {
  static const canvas = Color(0xFFFFFCF7);
  static const surface = Color(0xFFFFFFFF);
  static const ink = Color(0xFF2B2118);
  static const muted = Color(0xFF66584C);
  static const soft = Color(0xFFFFF0D9);
  static const line = Color(0xFFE6DCCF);
  static const orange = Color(0xFFFF9F1C);
  static const deep = Color(0xFFB94700);
  static const success = Color(0xFF326446);
  static const successSoft = Color(0xFFEDF5EC);
  static const error = Color(0xFFA33627);
  static const errorSoft = Color(0xFFFFF0EA);
  static const teal = Color(0xFF276B65);
  static const tealSoft = Color(0xFFE5F3EF);
  static const camera = Color(0xFF302820);
}

class PeelSpace {
  static const double x4 = 4;
  static const double x8 = 8;
  static const double x12 = 12;
  static const double x16 = 16;
  static const double x24 = 24;
}

class PeelRadii {
  static const r12 = BorderRadius.all(Radius.circular(12));
  static const r16 = BorderRadius.all(Radius.circular(16));
  static const r24 = BorderRadius.all(Radius.circular(24));
}

class PeelText {
  static const brand = TextStyle(
    fontFamily: 'Inter',
    fontWeight: FontWeight.w600,
    fontSize: 64,
    height: 68 / 64,
    color: PeelColors.ink,
  );
  static const title = TextStyle(
    fontFamily: 'Inter',
    fontWeight: FontWeight.w600,
    fontSize: 32,
    height: 40 / 32,
    color: PeelColors.ink,
  );
  static const heading = TextStyle(
    fontFamily: 'Inter',
    fontWeight: FontWeight.w600,
    fontSize: 22,
    height: 28 / 22,
    color: PeelColors.ink,
  );
  static const label = TextStyle(
    fontFamily: 'Inter',
    fontWeight: FontWeight.w600,
    fontSize: 16,
    height: 24 / 16,
    color: PeelColors.ink,
  );
  static const body = TextStyle(
    fontFamily: 'Inter',
    fontWeight: FontWeight.w400,
    fontSize: 16,
    height: 24 / 16,
    color: PeelColors.ink,
  );
  static const caption = TextStyle(
    fontFamily: 'Inter',
    fontWeight: FontWeight.w400,
    fontSize: 14,
    height: 20 / 14,
    color: PeelColors.muted,
  );
}

ThemeData buildPeelTheme() {
  const scheme = ColorScheme(
    brightness: Brightness.light,
    primary: PeelColors.orange,
    onPrimary: PeelColors.ink,
    primaryContainer: PeelColors.soft,
    onPrimaryContainer: PeelColors.ink,
    secondary: PeelColors.deep,
    onSecondary: PeelColors.surface,
    secondaryContainer: PeelColors.soft,
    onSecondaryContainer: PeelColors.deep,
    tertiary: PeelColors.teal,
    onTertiary: PeelColors.surface,
    tertiaryContainer: PeelColors.tealSoft,
    onTertiaryContainer: PeelColors.teal,
    error: PeelColors.error,
    onError: PeelColors.surface,
    errorContainer: PeelColors.errorSoft,
    onErrorContainer: PeelColors.error,
    surface: PeelColors.canvas,
    onSurface: PeelColors.ink,
    onSurfaceVariant: PeelColors.muted,
    outline: PeelColors.line,
    outlineVariant: PeelColors.line,
    surfaceContainerHighest: PeelColors.surface,
  );

  return ThemeData(
    useMaterial3: true,
    fontFamily: 'Inter',
    scaffoldBackgroundColor: PeelColors.canvas,
    colorScheme: scheme,
    textSelectionTheme: const TextSelectionThemeData(
      cursorColor: PeelColors.deep,
      selectionHandleColor: PeelColors.deep,
    ),
  );
}
