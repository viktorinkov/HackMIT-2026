import 'dart:convert';

/// Every signal the instrument puts on the wire, and the parser that turns one serial line
/// into one of them. See `PROTOCOL.md` and `SIGNALS.md`: the docs named in this app are
/// kept off main, in `hardware/docs/` on the `hardware-component` branch.
///
/// Nothing here corrects, smooths or scales a reading. A value is either what the board said
/// or null.

/// The LED colours, in the order of the sweep, which is also the order of their forward drops.
const colours = ['ir', 'red', 'yellow', 'green', 'blue', 'violet'];
const classificationColours = ['red', 'yellow', 'green'];

/// One 1 Hz data line.
class Reading {
  const Reading({
    required this.t,
    required this.transMv,
    required this.scatMv,
    this.absT,
    this.absS,
    this.tempC,
    this.sweep = const {},
    this.sweepScatter = const {},
    this.darkTransMv,
    this.darkScatMv,
    this.stirPct = 0,
    this.swept = false,
  });

  /// Seconds since t = 0, or null before a run starts (the firmware sends -1).
  final double? t;

  /// Transmission sensor, straight through the vial. Whole mV as the board reports them.
  final double transMv;

  /// Scatter sensor, 90 degrees off the beam.
  final double scatMv;

  /// log10(blank / now) on each channel. Null until a blank is taken.
  final double? absT;
  final double? absS;

  /// DS18B20, degrees C. Null when no probe answered at boot. -127.0 and 85.0 are the
  /// library's error sentinels and are reported as they arrive.
  final double? tempC;

  /// Transmission mV under each LED, and the scatter sensor's view of the same sweep.
  /// A colour is null until the first sweep, and absent from the map if this firmware
  /// does not sweep it.
  final Map<String, double?> sweep;
  final Map<String, double?> sweepScatter;

  /// Both sensors with every LED off, from the sweep.
  final double? darkTransMv;
  final double? darkScatMv;

  final int stirPct;

  /// True on the line a sweep ran in: that line's [transMv] and [scatMv] are disturbed.
  final bool swept;

  bool get isClassificationSweep =>
      swept &&
      classificationColours.every(
        (colour) => sweep[colour] != null && sweep[colour]!.isFinite,
      );

  Map<String, dynamic> toPillSweep() => {
    'swept': swept,
    'sweep': {
      for (final colour in classificationColours) colour: sweep[colour],
    },
  };

  bool get running => t != null;
  bool get blanked => absT != null || absS != null;
  bool get stirring => stirPct > 0;

  /// Cloudier liquid scatters more light onto the 90-degree sensor, so [absS] goes negative
  /// as turbidity rises. This is the same number with the sign flipped, not a correction.
  double? get cloudiness => absS == null ? null : -absS!;
}

/// The health line, `{"diag":{...}}`: what the MCU can tell about its own electronics.
/// Every field is optional, because a board may be running firmware older than this app.
class Diag {
  const Diag({
    this.firmware,
    this.version,
    this.build,
    this.resetReason,
    this.uptimeMs,
    this.heapBytes,
    this.heapMinBytes,
    this.loopMaxUs,
    this.gated = false,
    this.darkTransMv,
    this.darkScatMv,
    this.diodeMv = const {},
    this.noiseTransMv,
    this.noiseScatMv,
    this.probePresent,
    this.probeCount,
    this.probeAddress,
    this.radioChannel,
    this.radioSendFailures,
    this.radioDriftCorrections,
    this.motorTransBeforeMv,
    this.motorTransAfterMv,
    this.motorScatBeforeMv,
    this.motorScatAfterMv,
    this.motorStirPct,
  });

  final String? firmware;
  final String? version;
  final String? build;

  /// `esp_reset_reason()` as a string: POWERON, BROWNOUT, SW, PANIC, ...
  final String? resetReason;
  final int? uptimeMs;
  final int? heapBytes;
  final int? heapMinBytes;

  /// Worst loop period the firmware has seen since boot.
  final int? loopMaxUs;

  /// Reserved: true when the firmware sampled with the motor gated off. Always false today.
  final bool gated;

  final double? darkTransMv;
  final double? darkScatMv;

  /// Forward-drop node voltage per LED, from the MCU's own ADC. Healthy is
  /// IR < red < yellow < green < blue < violet; see `BASELINES.md`.
  final Map<String, double> diodeMv;

  /// Spread of consecutive 100 ms means on a still sensor, peak to peak.
  final double? noiseTransMv;
  final double? noiseScatMv;

  final bool? probePresent;
  final int? probeCount;
  final String? probeAddress;

  final int? radioChannel;
  final int? radioSendFailures;
  final int? radioDriftCorrections;

  /// Both sensors' means for 1 s before and after the last stirrer toggle, measured by the
  /// firmware itself.
  final double? motorTransBeforeMv;
  final double? motorTransAfterMv;
  final double? motorScatBeforeMv;
  final double? motorScatAfterMv;
  final int? motorStirPct;

  double? get motorTransShiftMv => _shift(motorTransBeforeMv, motorTransAfterMv);
  double? get motorScatShiftMv => _shift(motorScatBeforeMv, motorScatAfterMv);

  static double? _shift(double? before, double? after) =>
      (before == null || after == null) ? null : after - before;
}

/// What one line from the board turned out to be.
sealed class Line {
  const Line();
}

class DataLine extends Line {
  const DataLine(this.reading);
  final Reading reading;
}

class DiagLine extends Line {
  const DiagLine(this.diag);
  final Diag diag;
}

/// The board's own '#' messages: "blank stored", "t = 0 marked", "stirrer on".
class NoteLine extends Line {
  const NoteLine(this.text);
  final String text;
}

/// A line that is not part of the protocol: boot ROM output, a fragment from joining
/// mid-line, or another sketch's output. Kept rather than dropped so the app can tell
/// "nothing is arriving" from "something is arriving and it is not 17_stream".
class UnknownLine extends Line {
  const UnknownLine(this.text);
  final String text;
}

/// The firmware prints `null` for a value it does not have, but a build without the printNum
/// guard writes a bare `nan`, which is not JSON. Mapping it to null costs that one field
/// instead of throwing away the whole second.
final _nonFinite = RegExp(r':\s*-?(?:nan|inf(?:inity)?)\b', caseSensitive: false);

/// Parses one line. Returns null only for blank lines. Unknown keys are ignored, so a
/// firmware that adds a field does not break this parser.
Line? parseLine(String raw) {
  final line = raw.trim();
  if (line.isEmpty) return null;
  if (line.startsWith('#')) return NoteLine(line.substring(1).trim());
  if (!line.startsWith('{')) return UnknownLine(line);

  final Object? decoded;
  try {
    decoded = jsonDecode(line.replaceAll(_nonFinite, ':null'));
  } on FormatException {
    return UnknownLine(line);
  }
  if (decoded is! Map<String, dynamic>) return UnknownLine(line);

  final diag = decoded['diag'];
  if (diag is Map) return DiagLine(_diag(diag));

  final trans = _num(decoded['trans']);
  final scat = _num(decoded['scat']);
  if (trans == null || scat == null) return UnknownLine(line);

  final t = _num(decoded['t']);
  final dark = decoded['dark'];
  return DataLine(Reading(
    t: (t == null || t < 0) ? null : t,
    transMv: trans,
    scatMv: scat,
    absT: _num(decoded['absT']),
    absS: _num(decoded['absS']),
    tempC: _num(decoded['tC']),
    sweep: _sweep(decoded['sweep']),
    sweepScatter: _sweep(decoded['sweepS']),
    darkTransMv: dark is Map ? _num(dark['trans']) : null,
    darkScatMv: dark is Map ? _num(dark['scat']) : null,
    stirPct: _num(decoded['stir'])?.round() ?? 0,
    swept: decoded['swept'] == true,
  ));
}

/// Only the colours the board actually sent: a four-colour firmware leaves IR and violet out
/// of the map entirely, which is different from having swept them and got null.
Map<String, double?> _sweep(Object? value) {
  if (value is! Map) return const {};
  return {
    for (final colour in colours)
      if (value.containsKey(colour)) colour: _num(value[colour]),
  };
}

Diag _diag(Map<dynamic, dynamic> d) {
  Map<dynamic, dynamic>? sub(String key) => d[key] is Map ? d[key] as Map : null;
  final dark = sub('dark');
  final noise = sub('noise');
  final probe = sub('probe');
  final radio = sub('radio');
  final motor = sub('motor');
  final diode = sub('diode');
  return Diag(
    firmware: _str(d['fw']),
    version: _str(d['ver']),
    build: _str(d['build']),
    resetReason: _str(d['reset']),
    uptimeMs: _num(d['up'])?.round(),
    heapBytes: _num(d['heap'])?.round(),
    heapMinBytes: _num(d['heapMin'])?.round(),
    loopMaxUs: _num(d['loopMax'])?.round(),
    gated: d['gated'] == true,
    darkTransMv: dark == null ? null : _num(dark['trans']),
    darkScatMv: dark == null ? null : _num(dark['scat']),
    diodeMv: {
      if (diode != null)
        for (final colour in colours)
          if (_num(diode[colour]) != null) colour: _num(diode[colour])!,
    },
    noiseTransMv: noise == null ? null : _num(noise['trans']),
    noiseScatMv: noise == null ? null : _num(noise['scat']),
    probePresent: probe == null ? null : probe['present'] as bool?,
    probeCount: probe == null ? null : _num(probe['count'])?.round(),
    probeAddress: probe == null ? null : _str(probe['addr']),
    radioChannel: radio == null ? null : _num(radio['ch'])?.round(),
    radioSendFailures: radio == null ? null : _num(radio['fail'])?.round(),
    radioDriftCorrections: radio == null ? null : _num(radio['drift'])?.round(),
    motorTransBeforeMv: motor == null ? null : _num(motor['transBefore']),
    motorTransAfterMv: motor == null ? null : _num(motor['transAfter']),
    motorScatBeforeMv: motor == null ? null : _num(motor['scatBefore']),
    motorScatAfterMv: motor == null ? null : _num(motor['scatAfter']),
    motorStirPct: motor == null ? null : _num(motor['stir'])?.round(),
  );
}

double? _num(Object? v) => v is num && v.isFinite ? v.toDouble() : null;
String? _str(Object? v) => v is String && v.isNotEmpty ? v : null;
