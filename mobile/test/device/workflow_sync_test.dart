import 'package:fake_async/fake_async.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:peel_mobile/device/session.dart';
import 'package:peel_mobile/device/workflow_sync.dart';

import 'session_test.dart' show FakeLink;

void main() {
  test(
    'workflow follows stages, gates old firmware, and resyncs after reconnect',
    () {
      fakeAsync((time) {
        final session = Session(watchUsb: false, logging: false);
        final stage = ValueNotifier<int?>(0);
        final sync = WorkflowSync(session, stage);
        final first = FakeLink();
        session.connectTo(first);
        time.flushMicrotasks();
        first.say('{"t":-1,"trans":200,"scat":40}');
        time.flushMicrotasks();
        expect(first.sent.where((c) => c.startsWith('PHASE')), isEmpty);
        first.say('{"displayRelay":2,"t":-1,"trans":200,"scat":40}');
        time.flushMicrotasks();
        expect(first.sent.last, 'PHASE0\n');
        stage.value = 4;
        time.flushMicrotasks();
        expect(first.sent.last, 'PHASE4\n');
        final count = first.sent.length;
        time.elapse(const Duration(seconds: 2));
        expect(first.sent.length, count);
        first.say('{"displayError":"radio unavailable"}');
        time.flushMicrotasks();
        expect(session.connected, isTrue);
        stage.value = 7;
        time.flushMicrotasks();
        expect(first.sent.last, 'PHASE7\n');
        first.unplug();
        time.flushMicrotasks();
        final second = FakeLink();
        session.connectTo(second);
        time.flushMicrotasks();
        second.say('{"displayRelay":2,"t":-1,"trans":200,"scat":40}');
        time.flushMicrotasks();
        expect(second.sent.last, 'PHASE7\n');
        expect(first.sent, isNot(contains('z')));
        expect(first.sent, isNot(contains('m')));
        sync.dispose();
        session.dispose();
        stage.dispose();
        time.flushMicrotasks();
      });
    },
  );
}
