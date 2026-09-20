import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:usb_serial/usb_serial.dart';

import 'lines.dart';

/// A source of text lines from the instrument, and a way to send it the one-letter commands
/// 17_stream understands: b blank, z t=0, a auto t=0, s stop, m stirrer, d diagnostics.
abstract class Link {
  String get label;

  /// Whole lines, CR and NULs already stripped. Closes when the board goes away.
  Stream<String> get lines;

  Future<void> send(String command);
  Future<void> close();
}

/// The real board, over a USB OTG cable.
///
/// The XIAO ESP32-S3's USB-C port is the chip's own USB-Serial/JTAG peripheral, which
/// Android sees as a CDC-ACM device with Espressif's vendor id 0x303A. A DevKitC's port
/// marked UART instead goes through a CP210x or CH34x bridge. usb_serial drives all three,
/// but only the CDC path needs the fallback below: felHR85's driver table is keyed on
/// vendor id and does not know Espressif's.
class UsbLink implements Link {
  UsbLink._(this._port, this.label);

  final UsbPort _port;
  @override
  final String label;

  final _lines = StreamController<String>.broadcast();
  final _assembler = LineAssembler();
  StreamSubscription<Uint8List>? _sub;

  /// Espressif's vendor id. The XIAO ESP32-S3 enumerates as 303A:1001 in USB-Serial/JTAG
  /// mode and 303A:4001 when a sketch opens USBCDC itself.
  static const espressifVendorId = 0x303A;

  static Future<List<UsbDevice>> devices() => UsbSerial.listDevices();

  /// The board, if exactly one plausible one is attached. Espressif first, then anything
  /// else that enumerated, so a DevKitC on a bridge chip still works.
  static UsbDevice? pick(List<UsbDevice> devices) {
    if (devices.isEmpty) return null;
    return devices.firstWhere((d) => d.vid == espressifVendorId,
        orElse: () => devices.first);
  }

  static Future<UsbLink> open(UsbDevice device) async {
    // Auto-detect first; fall back to plain CDC, which is what USB-Serial/JTAG really is.
    UsbPort? port;
    try {
      port = await device.create();
    } on Exception {
      port = null;
    }
    port ??= await device.create(UsbSerial.CDC);
    if (port == null) {
      throw StateError('No serial driver for ${device.productName ?? 'this device'} '
          '(${device.vid?.toRadixString(16)}:${device.pid?.toRadixString(16)}).');
    }
    if (!await port.open()) {
      // open() returns false both when the permission dialog was refused and when another
      // app holds the device. The caller shows this to the user as is.
      // create() already took a connection to the device, and only close() gives it back:
      // left open, it is this app that holds the board on the next attempt.
      try {
        await port.close();
      } catch (_) {
        // Closing a port that never opened may throw; there is nothing more to release.
      }
      throw StateError('Could not open the port: USB permission was denied, or another '
          'app has the board open.');
    }
    // What a desktop serial monitor does on open. On an ESP32, DTR and RTS together mean
    // "run normally": RTS asserted while DTR is not holds the chip in reset, so the order
    // here matters.
    await port.setDTR(true);
    await port.setRTS(true);
    await port.setPortParameters(
        115200, UsbPort.DATABITS_8, UsbPort.STOPBITS_1, UsbPort.PARITY_NONE);
    return UsbLink._(port, device.productName ?? device.deviceName).._start();
  }

  void _start() {
    final input = _port.inputStream;
    if (input == null) {
      _lines.addError(StateError('The port opened but has no input stream.'));
      return;
    }
    _sub = input.listen(
      (data) {
        for (final line in _assembler.add(data)) {
          if (!_lines.isClosed) _lines.add(line);
        }
      },
      onError: (Object e) {
        if (!_lines.isClosed) _lines.addError(e);
      },
      onDone: () {
        final rest = _assembler.flush();
        if (rest != null && !_lines.isClosed) _lines.add(rest);
        if (!_lines.isClosed) _lines.close();
      },
      cancelOnError: false,
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
    try {
      await _port.close();
    } catch (_) {
      // The cable is already out: nothing to close.
    }
    if (!_lines.isClosed) await _lines.close();
  }
}

/// The simulator, over TCP. Developer-only: `python3 hardware/sim/fake_board.py --tcp 9000`,
/// then point the app at the host running it. Same bytes, same parser, no board.
class TcpLink implements Link {
  TcpLink._(this._socket, this.label) {
    _sub = _socket.listen(
      (data) {
        for (final line in _assembler.add(Uint8List.fromList(data))) {
          if (!_lines.isClosed) _lines.add(line);
        }
      },
      onError: (Object e) {
        if (!_lines.isClosed) _lines.addError(e);
      },
      onDone: () {
        final rest = _assembler.flush();
        if (rest != null && !_lines.isClosed) _lines.add(rest);
        if (!_lines.isClosed) _lines.close();
      },
      cancelOnError: false,
    );
  }

  final Socket _socket;
  @override
  final String label;
  final _lines = StreamController<String>.broadcast();
  final _assembler = LineAssembler();
  late final StreamSubscription<List<int>> _sub;

  static Future<TcpLink> connect(String host, int port,
      {Duration timeout = const Duration(seconds: 5)}) async {
    final socket = await Socket.connect(host, port, timeout: timeout);
    socket.setOption(SocketOption.tcpNoDelay, true);
    return TcpLink._(socket, 'sim $host:$port');
  }

  @override
  Stream<String> get lines => _lines.stream;

  @override
  Future<void> send(String command) async {
    _socket.add(ascii.encode(command));
    await _socket.flush();
  }

  @override
  Future<void> close() async {
    await _sub.cancel();
    try {
      await _socket.close();
    } catch (_) {}
    _socket.destroy();
    if (!_lines.isClosed) await _lines.close();
  }
}
