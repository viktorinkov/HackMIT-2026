import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'faults.dart';
import 'session.dart';
import 'signals.dart';

/// The whole UI: values, faults, commands, raw lines. Material defaults, one screen, no
/// theming and no charts. It exists to prove the layer underneath it works at the bench;
/// the product UI is someone else's file.
class DebugScreen extends StatefulWidget {
  const DebugScreen({super.key, required this.session});
  final Session session;

  @override
  State<DebugScreen> createState() => _DebugScreenState();
}

class _DebugScreenState extends State<DebugScreen> {
  final _host = TextEditingController(text: '10.0.2.2:9000');

  @override
  void dispose() {
    _host.dispose();
    super.dispose();
  }

  Future<void> _connectSim() async {
    final parts = _host.text.trim().split(':');
    await widget.session
        .connectSim(parts.first, parts.length > 1 ? int.tryParse(parts[1]) ?? 9000 : 9000);
  }

  Future<void> _copyLog() async {
    final log = widget.session.log;
    if (log == null) return;
    await Clipboard.setData(ClipboardData(text: await log.read()));
    if (mounted) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('Copied ${log.records} records')));
    }
  }

  @override
  Widget build(BuildContext context) {
    final session = widget.session;
    return Scaffold(
      appBar: AppBar(title: const Text('Peel debug')),
      body: AnimatedBuilder(
        animation: session,
        builder: (context, _) => ListView(
          padding: const EdgeInsets.all(12),
          children: [
            _connection(session),
            const Divider(),
            _commands(session),
            const Divider(),
            _values(session.latest),
            const Divider(),
            _faults(session.faults),
            const Divider(),
            _observations(session.faults),
            const Divider(),
            _diag(session.diag),
            const Divider(),
            _notes(session),
          ],
        ),
      ),
    );
  }

  Widget _connection(Session session) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('${session.state.name}'
              '${session.deviceLabel == null ? '' : ': ${session.deviceLabel}'}'
              '  ${session.lineCount} lines'),
          if (session.error != null) Text(session.error!),
          Wrap(spacing: 8, runSpacing: 8, children: [
            ElevatedButton(onPressed: session.connectUsb, child: const Text('USB')),
            ElevatedButton(onPressed: _connectSim, child: const Text('Simulator')),
            ElevatedButton(onPressed: session.disconnect, child: const Text('Disconnect')),
            ElevatedButton(
              onPressed: session.log == null ? null : _copyLog,
              child: const Text('Copy log'),
            ),
          ]),
          SizedBox(
            width: 220,
            child: TextField(
              controller: _host,
              decoration: const InputDecoration(labelText: 'simulator host:port'),
            ),
          ),
          if (session.log != null)
            Text('log: ${session.log!.path}'
                '${session.log!.isClosed ? ' (closed)' : ''}'),
        ],
      );

  Widget _commands(Session session) => Wrap(spacing: 8, runSpacing: 8, children: [
        for (final entry in const {
          'b': 'blank',
          'z': 't=0',
          'a': 'auto t=0',
          's': 'stop',
          'm': 'stirrer',
          'd': 'diagnostics',
        }.entries)
          ElevatedButton(
            onPressed: session.connected ? () => session.send(entry.key) : null,
            child: Text('${entry.key}  ${entry.value}'),
          ),
      ]);

  Widget _values(Reading? r) {
    if (r == null) return const Text('no readings yet');
    String mv(double? v) => v == null ? '-' : '${v.round()} mV';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _row('t', r.t == null ? 'not running' : '${r.t!.toStringAsFixed(1)} s'),
        _row('trans', mv(r.transMv)),
        _row('scat', mv(r.scatMv)),
        _row('absT', r.absT?.toStringAsFixed(4) ?? 'no blank'),
        _row('absS', r.absS?.toStringAsFixed(4) ?? 'no blank'),
        _row('temperature', r.tempC == null ? '-' : '${r.tempC} C'),
        _row('stirrer', '${r.stirPct}%'),
        _row('swept', '${r.swept}'),
        _row('dark', 'trans ${mv(r.darkTransMv)}, scat ${mv(r.darkScatMv)}'),
        for (final colour in colours)
          if (r.sweep.containsKey(colour))
            _row('sweep $colour',
                '${mv(r.sweep[colour])}   scatter ${mv(r.sweepScatter[colour])}'),
      ],
    );
  }

  /// Only what is wrong. An empty list here means a healthy board, so the informational
  /// entries — a swept line, a late line — are listed separately below.
  Widget _faults(List<Fault> faults) =>
      _faultList('faults', faults.where((f) => f.severity != Severity.info).toList());

  Widget _observations(List<Fault> faults) => _faultList(
      'observations (not faults)', faults.where((f) => f.severity == Severity.info).toList());

  Widget _faultList(String title, List<Fault> faults) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title),
          if (faults.isEmpty) const Text('none'),
          for (final f in faults)
            Padding(
              padding: const EdgeInsets.only(bottom: 6),
              child: Text('[${f.severity.name}] ${f.id}\n${f.message}\n${f.evidence}'),
            ),
        ],
      );

  Widget _diag(Diag? d) {
    if (d == null) return const Text('no diagnostics yet: press d');
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _row('firmware', '${d.firmware} ${d.version} ${d.build}'),
        _row('reset', '${d.resetReason}  up ${d.uptimeMs} ms'),
        _row('heap', '${d.heapBytes} (min ${d.heapMinBytes})  loopMax ${d.loopMaxUs} us'),
        _row('dark', 'trans ${d.darkTransMv}, scat ${d.darkScatMv}'),
        _row('noise', 'trans ${d.noiseTransMv}, scat ${d.noiseScatMv}'),
        _row('diode', '${d.diodeMv}'),
        _row('probe', '${d.probePresent} x${d.probeCount} ${d.probeAddress}'),
        _row('radio',
            'ch ${d.radioChannel}, fail ${d.radioSendFailures}, drift ${d.radioDriftCorrections}'),
        _row('motor', 'shift trans ${d.motorTransShiftMv}, scat ${d.motorScatShiftMv}'),
      ],
    );
  }

  Widget _notes(Session session) {
    final notes = session.history.notes.reversed.take(15).toList();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('board messages'),
        for (final note in notes) Text('# ${note.text}'),
        if (session.history.unknown.isNotEmpty) ...[
          const Text('not protocol'),
          for (final line in session.history.unknown.reversed.take(5)) Text(line.text),
        ],
      ],
    );
  }

  Widget _row(String label, String value) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 2),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(width: 110, child: Text(label)),
            Expanded(child: Text(value)),
          ],
        ),
      );
}
