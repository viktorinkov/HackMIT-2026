import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:peel_mobile/device/signals.dart';

const _full = '{"t":12.0,"trans":2166,"scat":231,"absT":0.0552,"absS":-0.1072,"tC":22.19,'
    '"sweep":{"ir":820,"red":897,"yellow":1301,"green":2463,"blue":1700,"violet":1096},'
    '"sweepS":{"ir":64,"red":68,"yellow":101,"green":197,"blue":137,"violet":88},'
    '"dark":{"trans":126,"scat":118},"stir":100,"swept":false}';

void main() {
  test('reads every field of a six-colour line', () {
    final line = parseLine(_full) as DataLine;
    final r = line.reading;
    expect(r.t, 12.0);
    expect(r.transMv, 2166);
    expect(r.scatMv, 231);
    expect(r.absT, 0.0552);
    expect(r.absS, -0.1072);
    expect(r.cloudiness, 0.1072);
    expect(r.tempC, 22.19);
    expect(r.sweep, hasLength(6));
    expect(r.sweep['violet'], 1096);
    expect(r.sweepScatter['green'], 197);
    expect(r.darkTransMv, 126);
    expect(r.darkScatMv, 118);
    expect(r.stirPct, 100);
    expect(r.stirring, isTrue);
    expect(r.swept, isFalse);
    expect(r.running, isTrue);
    expect(r.blanked, isTrue);
  });

  test('t of -1 means no run, not minus one second', () {
    final r = (parseLine('{"t":-1.0,"trans":434,"scat":61}') as DataLine).reading;
    expect(r.t, isNull);
    expect(r.running, isFalse);
  });

  test('a four-colour line leaves IR and violet out of the map rather than nulling them', () {
    final r = (parseLine('{"t":1.0,"trans":434,"scat":61,'
            '"sweep":{"red":240,"yellow":-359,"green":-120,"blue":-444}}') as DataLine)
        .reading;
    expect(r.sweep.keys, ['red', 'yellow', 'green', 'blue']);
    expect(r.sweep.containsKey('ir'), isFalse);
    expect(r.sweep['yellow'], -359);
  });

  test('null absorbance before a blank', () {
    final r = (parseLine('{"t":-1.0,"trans":434,"scat":61,"absT":null,"absS":null,"tC":null}')
            as DataLine)
        .reading;
    expect(r.absT, isNull);
    expect(r.blanked, isFalse);
    expect(r.tempC, isNull);
  });

  test('nan and inf cost their own field, not the line', () {
    final r = (parseLine('{"t":3.0,"trans":2460,"scat":180,"absT":nan,"absS":-inf,"tC":22.0}')
            as DataLine)
        .reading;
    expect(r.absT, isNull);
    expect(r.absS, isNull);
    expect(r.transMv, 2460);
    expect(r.tempC, 22.0);
  });

  test('unknown keys are ignored, so newer firmware still parses', () {
    final r = (parseLine('{"t":1.0,"trans":100,"scat":50,"pressure":1013,"mode":"fast"}')
            as DataLine)
        .reading;
    expect(r.transMv, 100);
  });

  test('notes, fragments, boot noise and empty lines', () {
    expect((parseLine('# stirrer on') as NoteLine).text, 'stirrer on');
    expect(parseLine(''), isNull);
    expect(parseLine('   '), isNull);
    expect((parseLine('0,"swept":false}') as UnknownLine).text, '0,"swept":false}');
    expect(parseLine('ESP-ROM:esp32s3-20210327'), isA<UnknownLine>());
    expect(parseLine('{"t":1.0,"trans":'), isA<UnknownLine>());
    // Valid JSON, but not a data line: no sensors in it.
    expect(parseLine('{"hello":true}'), isA<UnknownLine>());
    expect(parseLine('[1,2,3]'), isA<UnknownLine>());
  });

  test('reads the diag line', () {
    final d = (parseLine('{"diag":{"fw":"17_stream+diag","ver":"1.1.0","reset":"BROWNOUT",'
            '"up":41000,"heap":211000,"heapMin":198500,"loopMax":1100,"gated":false,'
            '"dark":{"trans":126,"scat":118},'
            '"diode":{"ir":246,"red":547,"yellow":624,"green":1208,"blue":1510,"violet":1763},'
            '"noise":{"trans":44,"scat":44},'
            '"probe":{"present":true,"count":1,"addr":"28FF641E8C1A03C7"},'
            '"radio":{"ch":1,"fail":3,"drift":0},'
            '"motor":{"stir":100,"transBefore":2460,"transAfter":2610,'
            '"scatBefore":180,"scatAfter":330}}}') as DiagLine)
        .diag;
    expect(d.firmware, '17_stream+diag');
    expect(d.resetReason, 'BROWNOUT');
    expect(d.diodeMv['violet'], 1763);
    expect(d.probeAddress, '28FF641E8C1A03C7');
    expect(d.radioSendFailures, 3);
    expect(d.motorTransShiftMv, 150);
    expect(d.motorScatShiftMv, 150);
  });

  test('a diag line from firmware that reports less of itself', () {
    final d = (parseLine('{"diag":{"fw":"17_stream","up":100}}') as DiagLine).diag;
    expect(d.firmware, '17_stream');
    expect(d.diodeMv, isEmpty);
    expect(d.probePresent, isNull);
    expect(d.motorTransShiftMv, isNull);
  });

  test('every line of the real capture parses', () {
    final file = File('../hardware/data/session_full_cycle.jsonl');
    final xiao = file
        .readAsLinesSync()
        .map((l) => jsonDecode(l) as Map<String, dynamic>)
        .where((e) => e['src'] == 'xiao')
        .map((e) => e['line'] as String)
        .toList();
    expect(xiao, isNotEmpty);
    final unknown = xiao.where((l) => parseLine(l) is UnknownLine).toList();
    expect(unknown, isEmpty, reason: 'unparsed: ${unknown.take(3)}');
    final data = xiao.map(parseLine).whereType<DataLine>().toList();
    expect(data.length, greaterThan(50));
    expect(data.any((d) => d.reading.swept), isTrue);
    expect(data.any((d) => d.reading.blanked), isTrue);
  });
}
