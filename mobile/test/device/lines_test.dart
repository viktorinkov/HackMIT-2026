import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:peel_mobile/device/lines.dart';

Uint8List bytes(String s) => Uint8List.fromList(latin1.encode(s));

void main() {
  test('splits on LF and strips CR', () {
    final a = LineAssembler();
    expect(a.add(bytes('one\r\ntwo\n')).toList(), ['one', 'two']);
  });

  test('holds a partial line until its newline arrives', () {
    final a = LineAssembler();
    expect(a.add(bytes('{"t":1')).toList(), isEmpty);
    expect(a.add(bytes('.0}\n')).toList(), ['{"t":1.0}']);
  });

  test('a chunk boundary between CR and LF does not split the line', () {
    final a = LineAssembler();
    expect(a.add(bytes('# stirrer on\r')).toList(), isEmpty);
    expect(a.add(bytes('\n')).toList(), ['# stirrer on']);
  });

  test('one byte at a time gives the same lines as one chunk', () {
    const text = '{"t":1.0,"trans":2460}\n# note\r\n{"t":2.0}\n';
    final whole = LineAssembler().add(bytes(text)).toList();
    final drip = <String>[];
    final a = LineAssembler();
    for (final unit in latin1.encode(text)) {
      drip.addAll(a.add(Uint8List.fromList([unit])));
    }
    expect(drip, whole);
    expect(whole, ['{"t":1.0,"trans":2460}', '# note', '{"t":2.0}']);
  });

  test('64 byte chunks that cut lines anywhere still reassemble', () {
    final text = '${List.generate(30, (i) => '{"t":$i.0,"trans":246$i}').join('\n')}\n';
    final a = LineAssembler();
    final out = <String>[];
    final all = latin1.encode(text);
    for (var i = 0; i < all.length; i += 64) {
      out.addAll(a.add(Uint8List.fromList(all.sublist(i, (i + 64).clamp(0, all.length)))));
    }
    expect(out.length, 30);
    expect(out.last, '{"t":29.0,"trans":24629}');
  });

  test('4 kB with no newline in it is flushed instead of buffered forever', () {
    final a = LineAssembler();
    final out = a.add(bytes('x' * 5000)).toList();
    expect(out.length, 1);
    expect(out.first.length, 4096);
    expect(a.add(bytes('\n')).toList(), ['x' * 904]);
  });

  test('Latin-1 junk and NULs come through without throwing', () {
    final a = LineAssembler();
    final out = a
        .add(Uint8List.fromList([0xfe, 0x01, ...latin1.encode('ESP-ROM:esp32s3'), 0x00, 0x0a]))
        .toList();
    expect(out.single, endsWith('ESP-ROM:esp32s3'));
  });

  test('flush returns the tail when the port closes mid-line', () {
    final a = LineAssembler();
    a.add(bytes('{"t":1.0'));
    expect(a.flush(), '{"t":1.0');
    expect(a.flush(), isNull);
  });
}
