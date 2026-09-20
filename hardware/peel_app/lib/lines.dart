import 'dart:convert';
import 'dart:typed_data';

/// Turns whatever bytes USB hands over into whole lines.
///
/// A read can end anywhere: mid-line, between the CR and the LF, or in the middle of a
/// UTF-8 sequence that is really just boot ROM noise. The board also emits, at reset, a
/// burst with no newline in it at all. This holds the leftovers between reads and never
/// grows without bound.
class LineAssembler {
  LineAssembler({this.maxLineLength = 4096});

  /// Longer than any line 17_stream produces (a six-colour line with both sweeps is about
  /// 300 bytes). Past this the buffer is junk, so it goes.
  final int maxLineLength;

  final _pending = StringBuffer();

  /// Bytes are decoded as Latin-1, which maps every byte to a character and so cannot
  /// throw. The protocol is ASCII; anything else is noise we want to see rather than an
  /// exception we have to catch.
  /// Eager rather than lazy: bytes taken off the port must not depend on anyone iterating
  /// the result.
  List<String> add(Uint8List bytes) {
    _pending.write(latin1.decode(bytes));
    var buffer = _pending.toString();
    _pending.clear();

    final lines = <String>[];
    var start = 0;
    for (var i = 0; i < buffer.length; i++) {
      if (buffer.codeUnitAt(i) != 0x0a) continue;
      lines.add(_clean(buffer.substring(start, i)));
      start = i + 1;
    }
    buffer = buffer.substring(start);

    // A CR at the very end may be the first half of a CRLF split across two reads, so it
    // stays in the buffer until the next one arrives.
    if (buffer.length > maxLineLength) {
      lines.add(_clean(buffer.substring(0, maxLineLength)));
      buffer = buffer.substring(maxLineLength);
    }
    _pending.write(buffer);
    return lines;
  }

  /// Whatever is left when the port closes, if it is not empty.
  String? flush() {
    final rest = _clean(_pending.toString());
    _pending.clear();
    return rest.isEmpty ? null : rest;
  }

  /// Strips CR and the NULs an ESP32 emits while its USB peripheral settles.
  static String _clean(String line) =>
      line.replaceAll('\r', '').replaceAll('\u0000', '').trimRight();
}
