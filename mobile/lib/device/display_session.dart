import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:usb_serial/usb_serial.dart';

import 'link.dart';

/// A display-only connection. It never sends instrument commands or diagnostics.
class DisplaySession extends ChangeNotifier {
  Link? _link;
  StreamSubscription<String>? _lines;
  StreamSubscription<UsbEvent>? _usb;
  Timer? _timeout;
  bool _disposed = false;
  int _generation = 0;
  bool connecting = false;
  bool ready = false;
  String text = 'Hello!';
  String? error;

  void watchUsb() {
    _usb = UsbSerial.usbEventStream?.listen((event) {
      if (event.event == UsbEvent.ACTION_USB_ATTACHED && _link == null) {
        connect();
      } else if (event.event == UsbEvent.ACTION_USB_DETACHED) {
        disconnect('Display disconnected. Reconnect its USB cable.');
      }
    });
  }

  Future<void> connect({String host = '', int port = 9001}) async {
    if (connecting) return;
    await disconnect();
    final generation = _generation;
    connecting = true;
    error = null;
    _notify();
    try {
      final Link link;
      if (host.isNotEmpty) {
        link = await TcpLink.connect(host, port);
      } else {
        final devices = await UsbLink.devices();
        final displays = devices
            .where((d) => d.serial?.toUpperCase() == '80:45:6B:64:89:18')
            .toList();
        final candidates = displays.isNotEmpty ? displays : devices;
        if (candidates.length != 1) {
          throw StateError(
            'Connect only the BOX-3 display to the phone with a USB data cable.',
          );
        }
        link = await UsbLink.open(candidates.single);
      }
      if (_disposed || generation != _generation) {
        await link.close();
        return;
      }
      await attach(link);
    } catch (e) {
      if (generation != _generation || _disposed) return;
      connecting = false;
      error = e is StateError ? e.message : 'Could not connect: $e';
      _notify();
    }
  }

  Future<void> attach(Link link) async {
    _link = link;
    connecting = true;
    ready = false;
    _lines = link.lines.listen(
      _receive,
      onError: (Object e) => disconnect('Display connection failed: $e'),
      onDone: () =>
          disconnect('Display disconnected. Reconnect its USB cable.'),
    );
    _timeout = Timer(const Duration(seconds: 5), () {
      connecting = false;
      error =
          'No display response. Check the BOX-3 display firmware and cable.';
      _notify();
    });
    await showHello();
  }

  void _receive(String line) {
    try {
      final value = jsonDecode(line);
      if (value is! Map ||
          value['display'] != 'peel' ||
          value['version'] != 1 ||
          !['Hello!', 'Peel'].contains(value['text'])) {
        return;
      }
      text = value['text'] as String;
      ready = true;
      connecting = false;
      error = null;
      _timeout?.cancel();
      _notify();
    } on FormatException {
      // Boot messages are not display acknowledgements.
    }
  }

  Future<void> showHello() => _send('HELLO\n');
  Future<void> showPeel() => _send('PEEL\n');
  Future<void> _send(String command) async {
    try {
      await _link?.send(command);
    } catch (e) {
      await disconnect('Could not update the display: $e');
    }
  }

  Future<void> disconnect([String? reason]) async {
    _generation++;
    _timeout?.cancel();
    final lines = _lines;
    final link = _link;
    _lines = null;
    _link = null;
    ready = false;
    connecting = false;
    error = reason;
    _notify();
    await lines?.cancel();
    await link?.close();
  }

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _usb?.cancel();
    unawaited(disconnect());
    super.dispose();
  }
}
