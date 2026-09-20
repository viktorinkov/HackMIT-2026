import 'dart:math';

import 'signals.dart';
import 'thresholds.dart';

/// Pure functions from what the board has said to what is wrong with it.
///
/// Nothing in here touches a port, a file or a clock: [evaluate] is given the history and
/// the current time and returns the list of active faults. Every id comes from
/// `hardware/docs/FAULTS.md` and every number from [Thresholds].

enum Severity {
  /// Worth showing, not wrong: a swept line, for instance.
  info,

  /// The readings are still usable, but something is off.
  warning,

  /// Do not trust the numbers.
  severe,
}

class Fault {
  const Fault(this.id, this.severity, this.message, this.evidence);

  /// The stable id from `docs/FAULTS.md`, for example `MOTOR_COUPLING`.
  final String id;
  final Severity severity;

  /// One line of plain English for someone standing at the bench.
  final String message;

  /// The values that raised it and the threshold they were compared against.
  final Map<String, Object?> evidence;

  @override
  String toString() => '$id (${severity.name}): $message $evidence';
}

class Sample {
  const Sample(this.reading, this.at, this.sinceLast);
  final Reading reading;
  final DateTime at;

  /// Time since the previous data line, or null for the first one.
  final Duration? sinceLast;
}

class Note {
  const Note(this.text, this.at);
  final String text;
  final DateTime at;
}

/// Everything the engine is allowed to look at. The session owns one of these and hands it
/// to [evaluate]; tests build one by hand.
class History {
  final List<Sample> samples = [];
  final List<Note> notes = [];

  /// Lines that are not protocol: boot ROM output, fragments, another sketch's output.
  final List<Note> unknown = [];

  Diag? diag;
  DateTime? diagAt;
  DateTime? connectedAt;
  DateTime? lastLineAt;

  /// When each `# 17_stream ready` banner arrived.
  final List<DateTime> banners = [];

  /// Banners that cannot be the one this connection opened on: a second banner, or a first
  /// one that arrived after readings were already coming in. The phone usually misses the
  /// real boot banner, because the board streams whether anyone is listening or not.
  final List<DateTime> restarts = [];

  /// True when a run was in progress the last time a banner arrived.
  bool resetDuringRun = false;

  /// True once any line has parsed as a data line: the difference between a silent board
  /// and one running the wrong sketch.
  bool get sawData => samples.isNotEmpty;

  Reading? get latest => samples.isEmpty ? null : samples.last.reading;

  void addLine(Line line, DateTime at) {
    lastLineAt = at;
    switch (line) {
      case DataLine(:final reading):
        final previous = samples.isEmpty ? null : samples.last.at;
        samples.add(Sample(reading, at, previous == null ? null : at.difference(previous)));
        if (samples.length > Thresholds.historyLength) samples.removeAt(0);
      case DiagLine(:final diag):
        this.diag = diag;
        diagAt = at;
      case NoteLine(:final text):
        notes.add(Note(text, at));
        if (text.startsWith('17_stream ready')) {
          resetDuringRun = latest?.running ?? false;
          if (banners.isNotEmpty || samples.isNotEmpty) restarts.add(at);
          banners.add(at);
        }
        if (notes.length > Thresholds.historyLength) notes.removeAt(0);
      case UnknownLine(:final text):
        unknown.add(Note(text, at));
        if (unknown.length > 50) unknown.removeAt(0);
    }
  }

  void clear() {
    samples.clear();
    notes.clear();
    unknown.clear();
    banners.clear();
    restarts.clear();
    diag = null;
    diagAt = null;
    lastLineAt = null;
    resetDuringRun = false;
  }

  Iterable<Sample> within(Duration window, DateTime now) =>
      samples.where((s) => now.difference(s.at) <= window);

  /// Swept lines are disturbed by definition, so most rules skip them.
  Iterable<Sample> unswept(Duration window, DateTime now) =>
      within(window, now).where((s) => !s.reading.swept);
}

/// The whole engine. Order is display order: worst first is the caller's job.
List<Fault> evaluate(History h, DateTime now) => [
      ..._stream(h, now),
      ..._reset(h, now),
      ..._sensors(h, now),
      ..._optics(h, now),
      ..._diode(h),
      ..._probe(h, now),
      ..._radio(h, now),
      ..._motor(h, now),
      ..._swept(h),
    ];

// ---------------------------------------------------------------- the stream itself
Iterable<Fault> _stream(History h, DateTime now) sync* {
  final connected = h.connectedAt;
  final last = h.lastLineAt;

  if (connected != null &&
      now.difference(connected) > Thresholds.bannerWithin &&
      h.banners.isEmpty &&
      !h.sawData &&
      h.unknown.isNotEmpty) {
    yield Fault('WRONG_FIRMWARE', Severity.severe,
        'Connected, but this is not 17_stream: no banner and no JSON.', {
      'secondsConnected': now.difference(connected).inSeconds,
      'threshold': '${Thresholds.bannerWithin.inSeconds} s',
      'lastLine': h.unknown.isEmpty ? null : h.unknown.last.text,
      'linesReceived': h.unknown.length,
    });
  }

  // Before the first line, silence is measured from the moment the port opened: a board
  // that says nothing at all is the same problem as one that stops.
  final since = last ?? connected;
  if (since != null && now.difference(since) > Thresholds.streamStale) {
    yield Fault('STREAM_STALE', Severity.severe,
        'Nothing from the board for ${now.difference(since).inSeconds} s.', {
      'silentFor': '${now.difference(since).inSeconds} s',
      'everReceived': h.lastLineAt != null,
      'threshold': '> ${Thresholds.streamStale.inSeconds} s',
    });
  }

  final recent = h.samples.isEmpty ? null : h.samples.last;
  if (recent?.sinceLast != null &&
      recent!.sinceLast! > Thresholds.lineGap &&
      now.difference(recent.at) <= Thresholds.streamStale) {
    yield Fault('LINE_GAP', Severity.info,
        'A line was ${recent.sinceLast!.inMilliseconds} ms late.', {
      'gap': '${recent.sinceLast!.inMilliseconds} ms',
      'threshold': '> ${Thresholds.lineGap.inMilliseconds} ms',
      'note': 'the stirrer start ramp causes one 2.2 s gap',
    });
  }
}

Iterable<Fault> _reset(History h, DateTime now) sync* {
  if (h.restarts.isEmpty) return;
  final at = h.restarts.last;
  if (now.difference(at) > const Duration(seconds: 30)) return;
  final reason = h.diag?.resetReason;
  // A reset the board itself blames on software is not a power problem, and sending someone
  // to the supply for a PANIC or a watchdog wastes their afternoon. Only a board that says
  // BROWNOUT, or one that has not said anything yet, gets the supply diagnosis.
  final supply = reason == null || reason == 'BROWNOUT' || reason == 'POWERON';
  final id = h.resetDuringRun
      ? 'BOARD_RESET_MIDRUN'
      : supply
          ? 'BROWNOUT_RESET'
          : 'BOARD_RESET';
  yield Fault(
      id,
      Severity.severe,
      h.resetDuringRun
          ? 'The board restarted during a run: the blank and t = 0 are gone.'
          : supply
              ? 'The board restarted: the supply probably sagged.'
              : 'The board restarted, and reports $reason: the firmware, not the supply.',
      {
        'banners': h.banners.length,
        'restarts': h.restarts.length,
        'resetReason': reason,
        'threshold': 'a second boot banner on one connection',
      });
}

/// Whether [window] really spans [over], rather than being the two or three lines that
/// happen to have arrived since the port opened. One report period of slack, because the
/// oldest line inside a 5 s window is about 4 s old, never exactly 5.
bool _covers(List<Sample> window, Duration over, DateTime now) =>
    window.length >= 2 &&
    now.difference(window.first.at) >= over - Thresholds.reportPeriod;

// ---------------------------------------------------------------- the two light sensors
Iterable<Fault> _sensors(History h, DateTime now) sync* {
  for (final channel in const ['trans', 'scat']) {
    double value(Reading r) => channel == 'trans' ? r.transMv : r.scatMv;

    final floorWindow = h.unswept(Thresholds.sensorFloorFor, now).toList();
    if (_covers(floorWindow, Thresholds.sensorFloorFor, now) &&
        floorWindow.every((s) => value(s.reading) < Thresholds.sensorFloorMv)) {
      yield Fault('SENSOR_UNPOWERED', Severity.severe,
          'The $channel sensor reads below the ADC floor: check VCC, GND and SIG.', {
        'channel': channel,
        'readings': floorWindow.map((s) => value(s.reading).round()).toList(),
        'threshold': '< ${Thresholds.sensorFloorMv.round()} mV for '
            '${Thresholds.sensorFloorFor.inSeconds} s (floor is 91-150 mV)',
      });
    }

    final satWindow = h.unswept(Thresholds.sensorSaturatedFor, now).toList();
    if (_covers(satWindow, Thresholds.sensorSaturatedFor, now) &&
        satWindow.every((s) => value(s.reading) > Thresholds.sensorSaturatedMv)) {
      yield Fault('SENSOR_SATURATED', Severity.severe,
          'The $channel sensor is pinned at full scale.', {
        'channel': channel,
        'readings': satWindow.map((s) => value(s.reading).round()).toList(),
        'threshold': '> ${Thresholds.sensorSaturatedMv.round()} mV for '
            '${Thresholds.sensorSaturatedFor.inSeconds} s',
      });
    }
  }

  final diag = h.diag;
  for (final entry in {'trans': diag?.noiseTransMv, 'scat': diag?.noiseScatMv}.entries) {
    final spread = entry.value;
    if (spread != null && spread > Thresholds.sensorNoiseMv) {
      yield Fault('SENSOR_NOISY', Severity.warning,
          'The ${entry.key} sensor is noisy: a loose jumper, or light getting in.', {
        'channel': entry.key,
        'spread': '${spread.round()} mV peak to peak',
        'threshold': '> ${Thresholds.sensorNoiseMv.round()} mV across 100 ms means',
      });
    }
  }
}

// ---------------------------------------------------------------- the optical path
Iterable<Fault> _optics(History h, DateTime now) sync* {
  final sweeps = h.samples.where((s) => s.reading.swept && s.reading.sweep.isNotEmpty).toList();
  final lastSweeps = sweeps.length <= Thresholds.sweepsBeforeNotAssembled
      ? sweeps
      : sweeps.sublist(sweeps.length - Thresholds.sweepsBeforeNotAssembled);
  if (lastSweeps.length == Thresholds.sweepsBeforeNotAssembled &&
      lastSweeps.every((s) => s.reading.sweep.values
          .every((mv) => mv != null && mv < Thresholds.sweepLitMv))) {
    yield Fault('NOT_ASSEMBLED', Severity.warning,
        'No optical path: every LED reads at or below dark on the transmission sensor.', {
      'lastSweep': lastSweeps.last.reading.sweep
          .map((colour, mv) => MapEntry(colour, mv?.round())),
      'threshold': 'every colour < +${Thresholds.sweepLitMv.round()} mV for '
          '${Thresholds.sweepsBeforeNotAssembled} sweeps',
    });
  }

  final dark = h.latest?.darkTransMv ?? h.diag?.darkTransMv;
  final darkScat = h.latest?.darkScatMv ?? h.diag?.darkScatMv;
  final worst = [dark, darkScat].whereType<double>().fold<double?>(
      null, (best, mv) => best == null ? mv : max(best, mv));
  if (worst != null && worst > Thresholds.darkMv) {
    yield Fault('LID_OPEN', Severity.warning,
        'Room light is reaching the sensors: the dark reading is ${worst.round()} mV.', {
      'darkTrans': dark?.round(),
      'darkScat': darkScat?.round(),
      'threshold': '> ${Thresholds.darkMv.round()} mV (shaded bench reads 140-160 mV)',
    });
  }
}

// ---------------------------------------------------------------- the LEDs themselves
Iterable<Fault> _diode(History h) sync* {
  final drops = h.diag?.diodeMv;
  if (drops == null || drops.isEmpty) return;

  final broken = <String>{};
  for (final entry in drops.entries) {
    if (entry.value > Thresholds.diodeOpenMv) {
      broken.add(entry.key);
      yield Fault('LED_OPEN', Severity.severe,
          'The ${entry.key} LED is open, reversed or missing its resistor.', {
        'colour': entry.key,
        'forwardDrop': '${entry.value.round()} mV',
        'threshold': '> ${Thresholds.diodeOpenMv.round()} mV (open reads about 3300 mV)',
      });
    } else if (entry.value < Thresholds.diodeShortMv) {
      broken.add(entry.key);
      yield Fault('LED_SHORT', Severity.severe,
          'The ${entry.key} LED anode is shorted to ground.', {
        'colour': entry.key,
        'forwardDrop': '${entry.value.round()} mV',
        'threshold': '< ${Thresholds.diodeShortMv.round()} mV',
      });
    }
  }

  // Healthy drops rise with photon energy: IR < red < yellow < green < blue < violet.
  // A pair out of order by more than the spread between neighbours means two LEDs are on
  // each other's pins. An LED that is already open or shorted says nothing about order.
  final ordered = colours.where((c) => drops.containsKey(c) && !broken.contains(c)).toList();
  for (var i = 0; i + 1 < ordered.length; i++) {
    final low = drops[ordered[i]]!;
    final high = drops[ordered[i + 1]]!;
    if (low - high > Thresholds.diodeInversionMv) {
      yield Fault('LED_SWAPPED', Severity.severe,
          '${ordered[i]} and ${ordered[i + 1]} look swapped: their forward drops are '
          'the wrong way round.', {
        ordered[i]: '${low.round()} mV',
        ordered[i + 1]: '${high.round()} mV',
        'threshold': 'any inversion by > ${Thresholds.diodeInversionMv.round()} mV',
      });
    }
  }
}

// ---------------------------------------------------------------- the temperature probe
Iterable<Fault> _probe(History h, DateTime now) sync* {
  final recent = h.samples.length <= Thresholds.probeNullLines
      ? h.samples
      : h.samples.sublist(h.samples.length - Thresholds.probeNullLines);

  final latest = h.latest?.tempC;
  if (latest != null && Thresholds.probeSentinels.contains(latest)) {
    yield Fault('PROBE_ERROR', Severity.warning,
        'The temperature probe returned its error value ($latest C).', {
      'tC': latest,
      'threshold': 'exactly ${Thresholds.probeSentinels.join(' or ')}',
    });
    return;
  }

  final noProbe = h.diag?.probePresent == false;
  if (recent.length == Thresholds.probeNullLines &&
      recent.every((s) => s.reading.tempC == null)) {
    yield Fault('PROBE_MISSING', Severity.warning,
        'No temperature: the DS18B20 or its 5.1 kOhm pull-up is missing.', {
      'nullLines': recent.length,
      'diagProbePresent': h.diag?.probePresent,
      'threshold': 'tC null for ${Thresholds.probeNullLines} lines',
    });
    return;
  }
  if (noProbe && h.samples.isEmpty) {
    yield Fault('PROBE_MISSING', Severity.warning,
        'The board reports no temperature probe.', {'diagProbePresent': false});
  }

  final window = h.within(const Duration(seconds: 10), now).toList();
  for (var i = 1; i < window.length; i++) {
    final before = window[i - 1].reading.tempC;
    final after = window[i].reading.tempC;
    if (before == null ||
        after == null ||
        Thresholds.probeSentinels.contains(before) ||
        Thresholds.probeSentinels.contains(after)) {
      continue;
    }
    final jump = (after - before).abs();
    if (jump > Thresholds.tempJitterC) {
      yield Fault('TEMP_JITTER', Severity.warning,
          'Temperature jumped ${jump.toStringAsFixed(2)} C in one second, which a liquid '
          'cannot do: noise on the OneWire line.', {
        'from': before,
        'to': after,
        'threshold': '> ${Thresholds.tempJitterC} C between consecutive lines',
      });
      return;
    }
  }
}

// ---------------------------------------------------------------- the radio
Iterable<Fault> _radio(History h, DateTime now) sync* {
  final diag = h.diag;
  final drifted = h.notes.where((n) => n.text.startsWith('radio had drifted')).toList();
  final driftCount = diag?.radioDriftCorrections ?? 0;
  if (drifted.isNotEmpty || driftCount > 0) {
    yield Fault('RADIO_DRIFT', Severity.info,
        'The radio left channel 1 and was pulled back.', {
      'corrections': driftCount,
      'note': drifted.isEmpty ? null : drifted.last.text,
      'threshold': 'any occurrence',
    });
  }
  final failures = diag?.radioSendFailures;
  if (failures != null && failures >= Thresholds.radioSendFailures) {
    // A send that succeeds only reached the radio's queue: ESP-NOW broadcasts are never
    // acknowledged, so the phone cannot tell a listening face from an absent one. Failures
    // are still real, and `heard` says whether the face has ever answered.
    yield Fault('RADIO_DOWN', Severity.warning,
        'The board cannot get packets onto the air: ESP-NOW sends are failing.', {
      'sendFailures': failures,
      'heardFromFaceMsAgo': diag?.radioHeardMs,
      'threshold': '>= ${Thresholds.radioSendFailures} failed sends',
    });
  }
}

// ---------------------------------------------------------------- the stirrer
Iterable<Fault> _motor(History h, DateTime now) sync* {
  // The firmware's own measurement first, if this build makes it.
  final diag = h.diag;
  final byFirmware = [diag?.motorTransShiftMv, diag?.motorScatShiftMv].whereType<double>();
  if (byFirmware.length == 2 &&
      byFirmware.every((shift) => shift.abs() > Thresholds.motorCouplingMv) &&
      byFirmware.first.sign == byFirmware.last.sign) {
    yield _coupling(byFirmware.first, byFirmware.last, 'the firmware\'s own 1 s means');
    return;
  }

  // Otherwise look for a stirrer toggle in the stream and compare across it.
  int? toggle;
  for (var i = h.samples.length - 1; i > 0; i--) {
    if (h.samples[i].reading.stirPct != h.samples[i - 1].reading.stirPct) {
      toggle = i;
      break;
    }
  }
  if (toggle == null) return;
  final at = h.samples[toggle].at;
  if (now.difference(at) > const Duration(seconds: 30)) return;

  double? mean(Iterable<Sample> samples, double Function(Reading) pick) {
    final values = samples.where((s) => !s.reading.swept).map((s) => pick(s.reading)).toList();
    if (values.isEmpty) return null;
    return values.reduce((a, b) => a + b) / values.length;
  }

  final before = h.samples
      .sublist(max(0, toggle - 3), toggle)
      .where((s) => at.difference(s.at) <= Thresholds.motorWindow);
  final after = h.samples
      .sublist(toggle)
      .where((s) => s.at.difference(at) <= Thresholds.motorWindow);

  final transBefore = mean(before, (r) => r.transMv);
  final transAfter = mean(after, (r) => r.transMv);
  final scatBefore = mean(before, (r) => r.scatMv);
  final scatAfter = mean(after, (r) => r.scatMv);
  if (transBefore == null || transAfter == null || scatBefore == null || scatAfter == null) {
    return;
  }
  final transShift = transAfter - transBefore;
  final scatShift = scatAfter - scatBefore;
  if (transShift.abs() > Thresholds.motorCouplingMv &&
      scatShift.abs() > Thresholds.motorCouplingMv &&
      transShift.sign == scatShift.sign) {
    yield _coupling(transShift, scatShift, 'both channels across the stirrer toggle');
  }
}

Fault _coupling(double transShift, double scatShift, String source) {
  final worst = max(transShift.abs(), scatShift.abs());
  return Fault(
      'MOTOR_COUPLING',
      worst > Thresholds.motorCouplingSevereMv ? Severity.severe : Severity.warning,
      'The stirrer is moving both sensors by ${worst.round()} mV: motor current is '
      'sharing the sensors\' supply or ground.',
      {
        'transShift': '${transShift.round()} mV',
        'scatShift': '${scatShift.round()} mV',
        'source': source,
        'threshold': '> ${Thresholds.motorCouplingMv.round()} mV on both channels; '
            '> ${Thresholds.motorCouplingSevereMv.round()} mV is severe',
      });
}

// ---------------------------------------------------------------- not a fault
Iterable<Fault> _swept(History h) sync* {
  if (h.latest?.swept ?? false) {
    yield Fault('SWEPT_LINE', Severity.info,
        'A sweep ran in this second, so this line\'s trans and scat are disturbed.', {
      'trans': h.latest!.transMv.round(),
      'scat': h.latest!.scatMv.round(),
      'threshold': 'exclude the line from any rate calculation',
    });
  }
}
