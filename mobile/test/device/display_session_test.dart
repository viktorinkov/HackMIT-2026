import 'package:fake_async/fake_async.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:peel_mobile/device/display_session.dart';

import 'session_test.dart' show FakeLink;

void main() {
  test(
    'display commands wait for acknowledgements and ignore sensor telemetry',
    () {
      fakeAsync((time) {
        final link = FakeLink();
        final display = DisplaySession();
        display.attach(link);
        time.flushMicrotasks();
        expect(link.sent, ['HELLO\n']);
        expect(display.ready, isFalse);
        link.say('{"display":"peel","text":"Hello!","version":1}');
        time.flushMicrotasks();
        expect(display.ready, isFalse);
        link.say('{"t":-1,"trans":100,"scat":10}');
        link.say('ESP-ROM startup');
        time.flushMicrotasks();
        expect(display.ready, isFalse);
        link.say(
          '{"display":"peel","text":"Hello!","version":1,"via":"seeed-radio"}',
        );
        time.flushMicrotasks();
        expect(display.ready, isTrue);
        display.showPeel();
        time.flushMicrotasks();
        expect(display.text, 'Hello!');
        expect(link.sent.last, 'PEEL\n');
        link.say(
          '{"display":"peel","text":"Peel","version":1,"via":"seeed-radio"}',
        );
        time.flushMicrotasks();
        expect(display.text, 'Peel');
        expect(link.sent, ['HELLO\n', 'PEEL\n']);
        link.unplug();
        time.flushMicrotasks();
        expect(display.ready, isFalse);
        expect(display.error, contains('disconnected'));
        display.dispose();
        time.flushMicrotasks();
      });
    },
  );
  test('no firmware reply becomes actionable instead of waiting forever', () {
    fakeAsync((time) {
      final display = DisplaySession();
      display.attach(FakeLink());
      time.flushMicrotasks();
      time.elapse(const Duration(seconds: 6));
      expect(display.connecting, isFalse);
      expect(display.error, contains('No display response'));
      display.dispose();
      time.flushMicrotasks();
    });
  });
}
