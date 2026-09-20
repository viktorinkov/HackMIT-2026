import 'dart:async';

import 'package:flutter/foundation.dart';

import 'session.dart';

/// Mirrors the existing app's animation stage over its existing USB session.
/// Display support is optional and never controls navigation or a pill verdict.
class WorkflowSync {
  WorkflowSync(this.session, this.stage) {
    session.addListener(_sync);
    stage.addListener(_sync);
    _sync();
  }
  final Session session;
  final ValueListenable<int?> stage;
  int? _sent;
  int _reset = -1;

  void _sync() {
    if (!session.connected ||
        !session.supportsWorkflowDisplay ||
        _reset != session.resetCount) {
      _sent = null;
      _reset = session.resetCount;
    }
    final current = stage.value;
    if (!session.connected ||
        !session.supportsWorkflowDisplay ||
        current == null ||
        current == _sent) {
      return;
    }
    _sent = current;
    unawaited(session.send('PHASE$current\n'));
  }

  void dispose() {
    session.removeListener(_sync);
    stage.removeListener(_sync);
  }
}
