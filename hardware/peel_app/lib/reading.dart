import 'dart:convert';

/// One line of the 17_stream firmware's 1 Hz output, for example:
///
///     {"t":12.0,"trans":1830,"scat":140,"absT":0.1240,"absS":0.0430,"tC":37.02,
///      "sweep":{"red":1200,"yellow":900,"green":2400,"blue":1700},"stir":100,"swept":false}
class Reading {
  const Reading({
    required this.t,
    required this.transMv,
    required this.scatMv,
    this.absT,
    this.absS,
    this.tempC,
    this.sweep = const {},
    this.stirPct = 0,
    this.swept = false,
  });

  /// Seconds since t = 0, or null before a run starts (the firmware sends -1).
  final double? t;
  final double transMv;
  final double scatMv;

  /// Transmission absorbance, log10(blank / now). Null until a blank is taken.
  final double? absT;

  /// The firmware computes the scatter channel the same way, log10(blank / now). Cloudier
  /// liquid scatters MORE light onto the 90-degree sensor, so this goes negative as the tablet
  /// clouds the water. [cloudiness] flips the sign so the curve rises with turbidity.
  final double? absS;
  double? get cloudiness => absS == null ? null : -absS!;

  final double? tempC;

  /// Latest four-colour sweep in mV, keyed red / yellow / green / blue. Null until swept.
  final Map<String, double?> sweep;
  final int stirPct;

  /// True when a sweep ran inside this second, which briefly disturbs the fast channel.
  final bool swept;

  bool get running => t != null;
  bool get blanked => absT != null || absS != null;

  static const colours = ['red', 'yellow', 'green', 'blue'];
}

/// What one serial line turned out to be.
sealed class Line {}

class DataLine extends Line {
  DataLine(this.reading);
  final Reading reading;
}

/// The board's own '#' messages: "blank stored", "t = 0 marked", "stirrer on".
class NoteLine extends Line {
  NoteLine(this.text);
  final String text;
}

// Firmware before the printNum fix wrote a bare `nan` for a dark or unplugged sensor, which is
// not JSON. Mapping it to null costs that one field instead of throwing away the whole second.
final _nonFinite = RegExp(r':\s*-?(?:nan|inf(?:inity)?)\b', caseSensitive: false);

/// Parses one serial line. Returns null for blank lines, boot noise and anything malformed:
/// a USB stream can start mid-line, so the first line after connecting is often a fragment.
Line? parseLine(String raw) {
  final line = raw.trim();
  if (line.isEmpty) return null;
  if (line.startsWith('#')) return NoteLine(line.substring(1).trim());
  if (!line.startsWith('{')) return null;

  final Object? decoded;
  try {
    decoded = jsonDecode(line.replaceAll(_nonFinite, ':null'));
  } on FormatException {
    return null;
  }
  if (decoded is! Map<String, dynamic>) return null;

  final trans = _num(decoded['trans']);
  final scat = _num(decoded['scat']);
  if (trans == null || scat == null) return null;

  final t = _num(decoded['t']);
  final sweep = decoded['sweep'];
  return DataLine(Reading(
    t: (t == null || t < 0) ? null : t,
    transMv: trans,
    scatMv: scat,
    absT: _num(decoded['absT']),
    absS: _num(decoded['absS']),
    tempC: _num(decoded['tC']),
    sweep: {for (final c in Reading.colours) c: sweep is Map ? _num(sweep[c]) : null},
    stirPct: _num(decoded['stir'])?.round() ?? 0,
    swept: decoded['swept'] == true,
  ));
}

double? _num(Object? v) => v is num && v.isFinite ? v.toDouble() : null;
