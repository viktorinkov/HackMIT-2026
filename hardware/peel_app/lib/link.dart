import 'dart:async';
import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';

import 'package:usb_serial/usb_serial.dart';

/// A source of text lines from the instrument, and a way to send it the one-letter commands
/// 17_stream understands: b blank, z t=0, a auto t=0, s stop, m stirrer.
abstract class Link {
  String get label;
  Stream<String> get lines;
  Future<void> send(String command);
  Future<void> close();
}

/// The real board, over a USB OTG cable.
///
/// The DevKitC's port marked USB is the ESP32-S3's own USB-Serial/JTAG, which Android sees
/// as a CDC serial device. Its port marked UART goes through a CP210x or CH34x bridge chip.
/// usb_serial drives all three.
class UsbLink implements Link {
  UsbLink._(this._port, this.label);

  final UsbPort _port;
  @override
  final String label;
  final _lines = StreamController<String>.broadcast();
  StreamSubscription<Uint8List>? _sub;
  String _pending = '';

  static Future<List<UsbDevice>> devices() => UsbSerial.listDevices();

  static Future<UsbLink> open(UsbDevice device) async {
    // Auto-detect first. The ESP32-S3's own vendor ID is missing from some driver tables, so
    // fall back to plain CDC, which is what its USB-Serial/JTAG port really is.
    var port = await device.create();
    port ??= await device.create(UsbSerial.CDC);
    if (port == null) {
      throw StateError('No serial driver for ${device.productName ?? 'this device'}');
    }
    if (!await port.open()) {
      throw StateError('Could not open the port. Was USB permission denied?');
    }
    // What a desktop serial monitor does on open. On an ESP32, DTR and RTS together mean
    // "run normally"; RTS on its own holds the chip in reset.
    await port.setDTR(true);
    await port.setRTS(true);
    await port.setPortParameters(
        115200, UsbPort.DATABITS_8, UsbPort.STOPBITS_1, UsbPort.PARITY_NONE);
    return UsbLink._(port, device.productName ?? device.deviceName).._start();
  }

  void _start() {
    _sub = _port.inputStream?.listen(
      (data) {
        _pending += latin1.decode(data);
        var nl = _pending.indexOf('\n');
        while (nl >= 0) {
          _lines.add(_pending.substring(0, nl).replaceAll('\r', ''));
          _pending = _pending.substring(nl + 1);
          nl = _pending.indexOf('\n');
        }
        // Noise with no newline in it: don't let the buffer grow forever.
        if (_pending.length > 4096) _pending = '';
      },
      onError: _lines.addError,
      onDone: _lines.close,
    );
  }

  @override
  Stream<String> get lines => _lines.stream;

  @override
  Future<void> send(String command) =>
      _port.write(Uint8List.fromList(ascii.encode(command)));

  @override
  Future<void> close() async {
    await _sub?.cancel();
    await _port.close();
    await _lines.close();
  }
}

/// A stand-in for the board that prints exactly what 17_stream prints, so every line still
/// goes through the real parser. For showing the app without hardware, and as a demo-day
/// fallback if the rig misbehaves.
///
/// It models a coloured tablet: transmission absorbance rises first-order to a plateau, while
/// cloudiness spikes as the tablet breaks apart and then clears as it dissolves.
class DemoLink implements Link {
  DemoLink({Duration tick = const Duration(seconds: 1), int seed = 7})
      : _rng = Random(seed) {
    _timer = Timer.periodic(tick, (_) => _emit());
    scheduleMicrotask(() {
      _note('17_stream ready. Fast channel = green LED. Stirrer 100%. Temperature probe: demo');
      _note('commands: b blank, z mark t=0, a toggle auto t=0, s stop, m stirrer');
    });
  }

  @override
  String get label => 'Demo';

  final Random _rng;
  late final Timer _timer;
  final _lines = StreamController<String>.broadcast();

  static const _clearT = 2460.0; // the real rig's resting transmission, mV
  static const _clearS = 180.0;
  static const _aInf = 0.42, _k = 1 / 90.0; // plateau absorbance, rate (1/s)
  static const _sweepBase = {'red': 900.0, 'yellow': 1300.0, 'green': 2460.0, 'blue': 1700.0};
  // How strongly each colour is absorbed relative to green: a yellow compound eats blue.
  static const _sweepGain = {'red': 0.05, 'yellow': 0.2, 'green': 0.6, 'blue': 2.2};

  double? _blankT, _blankS;
  int _tick = 0;
  int? _zeroTick, _blankTick;
  bool _stir = true, _auto = true;
  Map<String, double?> _sweep = {for (final c in _sweepBase.keys) c: null};

  double get _elapsed => _zeroTick == null ? -1 : (_tick - _zeroTick!).toDouble();
  double _noise(double sd) => (_rng.nextDouble() + _rng.nextDouble() - 1) * sd;

  void _emit() {
    _tick++;
    // Auto t=0, as the firmware does it: the tablet lands a few seconds after the blank.
    if (_auto && _zeroTick == null && _blankTick != null && _tick - _blankTick! == 6) {
      _zeroTick = _tick;
      _note('t = 0 detected from the transmission drop');
    }
    final t = _elapsed;
    final absT = t < 0 ? 0.0 : _aInf * (1 - exp(-_k * t));
    final cloud = t < 0 ? 0.0 : 0.30 * (t / 40) * exp(1 - t / 40) + 0.04 * (1 - exp(-_k * t));
    final trans = _clearT * pow(10, -absT) + _noise(4);
    final scat = _clearS * pow(10, cloud) + _noise(2);

    final swept = _tick % 10 == 0;
    if (swept) {
      _sweep = {
        for (final e in _sweepBase.entries)
          e.key: e.value * pow(10, -absT * _sweepGain[e.key]!) + _noise(5)
      };
    }
    double? ab(double? blank, double now) =>
        blank == null ? null : double.parse((log(blank / now) / ln10).toStringAsFixed(4));

    _lines.add(jsonEncode({
      't': double.parse(t.toStringAsFixed(1)),
      'trans': trans.roundToDouble(),
      'scat': scat.roundToDouble(),
      'absT': ab(_blankT, trans),
      'absS': ab(_blankS, scat),
      'tC': double.parse((37.0 + _noise(0.05)).toStringAsFixed(2)),
      'sweep': {for (final e in _sweep.entries) e.key: e.value?.roundToDouble()},
      'stir': _stir ? 100 : 0,
      'swept': swept,
    }));
  }

  void _note(String text) => _lines.add('# $text');

  @override
  Stream<String> get lines => _lines.stream;

  @override
  Future<void> send(String command) async {
    switch (command) {
      case 'b':
        _blankT = _clearT;
        _blankS = _clearS;
        _blankTick = _tick;
        _note('blank stored: transmission ${_clearT.round()} mV, scatter ${_clearS.round()} mV');
      case 'z':
        _zeroTick = _tick;
        _note('t = 0 marked');
      case 'a':
        _auto = !_auto;
        _note('auto t=0 ${_auto ? 'on' : 'off'}');
      case 's':
        _zeroTick = null;
        _blankTick = null;
        _note('run stopped');
      case 'm':
        _stir = !_stir;
        _note(_stir ? 'stirrer on' : 'stirrer off');
    }
  }

  @override
  Future<void> close() async {
    _timer.cancel();
    await _lines.close();
  }
}
