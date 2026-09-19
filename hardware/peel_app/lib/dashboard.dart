import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'chart.dart';
import 'reading.dart';
import 'session.dart';

String _clock(double s) {
  final whole = s.floor();
  return '${whole ~/ 60}:${(whole % 60).toString().padLeft(2, '0')}';
}

String _fixed(double? v, int places) => v == null ? '—' : v.toStringAsFixed(places);

const _sweepColours = {
  'red': Color(0xFFE53935),
  'yellow': Color(0xFFFFB300),
  'green': Color(0xFF43A047),
  'blue': Color(0xFF1E88E5),
};

class Dashboard extends StatelessWidget {
  const Dashboard({super.key, required this.session});
  final Session session;

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: session,
      builder: (context, _) => Scaffold(
        appBar: AppBar(
          title: const Text('Peel'),
          actions: [
            IconButton(
              tooltip: 'Copy CSV',
              icon: const Icon(Icons.content_copy),
              onPressed: session.rowCount == 0 ? null : () => _copyCsv(context),
            ),
            PopupMenuButton<String>(
              onSelected: (v) => switch (v) {
                'usb' => session.connectUsb(),
                'demo' => session.startDemo(),
                _ => session.disconnect(),
              },
              itemBuilder: (_) => [
                const PopupMenuItem(value: 'usb', child: Text('Connect to board')),
                const PopupMenuItem(value: 'demo', child: Text('Demo mode')),
                if (session.connected)
                  const PopupMenuItem(value: 'off', child: Text('Disconnect')),
              ],
            ),
          ],
        ),
        body: SafeArea(
          child: ListView(
            padding: const EdgeInsets.fromLTRB(16, 4, 16, 24),
            children: [
              _StatusCard(session: session),
              if (session.connected) ...[
                const SizedBox(height: 12),
                _Headline(session: session),
                _Hint(session: session),
                const SizedBox(height: 12),
                _ChartCard(session: session),
                const SizedBox(height: 12),
                _Readouts(reading: session.latest),
                const SizedBox(height: 12),
                _SweepCard(reading: session.latest),
                const SizedBox(height: 12),
                _Controls(session: session),
                const SizedBox(height: 12),
                _Notes(notes: session.notes),
              ],
            ],
          ),
        ),
      ),
    );
  }

  void _copyCsv(BuildContext context) {
    Clipboard.setData(ClipboardData(text: session.csv()));
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('Copied ${session.rowCount} readings as CSV')),
    );
  }
}

class _StatusCard extends StatelessWidget {
  const _StatusCard({required this.session});
  final Session session;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final text = Theme.of(context).textTheme;

    if (session.state == LinkState.connecting) {
      return const Card(
        child: ListTile(
          leading: SizedBox.square(dimension: 24, child: CircularProgressIndicator()),
          title: Text('Connecting…'),
        ),
      );
    }

    if (!session.connected) {
      return Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(children: [
                Icon(Icons.usb_off, color: scheme.onSurfaceVariant),
                const SizedBox(width: 12),
                Text('Not connected', style: text.titleMedium),
              ]),
              const SizedBox(height: 8),
              Text(
                session.error ??
                    'Plug the DevKitC\'s port marked USB into the phone through the '
                        'USB-C to USB-A adapter, then tap Connect.',
                style: text.bodyMedium?.copyWith(
                    color: session.error != null ? scheme.error : scheme.onSurfaceVariant),
              ),
              const SizedBox(height: 16),
              Row(children: [
                FilledButton.icon(
                  onPressed: session.connectUsb,
                  icon: const Icon(Icons.usb),
                  label: const Text('Connect'),
                ),
                const SizedBox(width: 12),
                OutlinedButton(onPressed: session.startDemo, child: const Text('Try demo')),
              ]),
            ],
          ),
        ),
      );
    }

    final stale = session.stale;
    final demo = session.state == LinkState.demo;
    final colour = stale ? scheme.error : (demo ? scheme.tertiary : Colors.green);
    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 12, 8, 12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(children: [
              Icon(Icons.circle, size: 12, color: colour),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  stale
                      ? 'No data'
                      : demo
                          ? 'Demo · simulated tablet'
                          : 'Live · ${session.deviceLabel}',
                  style: text.titleMedium,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              Text('${session.rowCount} logged', style: text.bodySmall),
              TextButton(onPressed: session.disconnect, child: const Text('Disconnect')),
            ]),
            if (stale)
              Padding(
                padding: const EdgeInsets.only(top: 6, right: 8),
                child: Text(
                  'Nothing for 3 s. Check the board is running 17_stream. If it reset when '
                  'the stirrer started, the phone can\'t supply the motor: plug a charger '
                  'into the DevKitC\'s other port, marked UART.',
                  style: text.bodySmall?.copyWith(color: scheme.error),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _Headline extends StatelessWidget {
  const _Headline({required this.session});
  final Session session;

  @override
  Widget build(BuildContext context) {
    final r = session.latest;
    return Row(children: [
      Expanded(
        child: _Big(
          label: 'Elapsed',
          value: r?.t == null ? '—' : _clock(r!.t!),
          caption: r?.t == null ? 'not started' : 'since t = 0',
        ),
      ),
      Expanded(
        child: _Big(label: 'Absorbance', value: _fixed(r?.absT, 3), caption: 'transmission'),
      ),
      Expanded(
        child: _Big(label: 'Cloudiness', value: _fixed(r?.cloudiness, 3), caption: '90° scatter'),
      ),
    ]);
  }
}

class _Big extends StatelessWidget {
  const _Big({required this.label, required this.value, required this.caption});
  final String label, value, caption;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final muted = Theme.of(context).colorScheme.onSurfaceVariant;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: text.labelMedium?.copyWith(color: muted)),
        FittedBox(
          fit: BoxFit.scaleDown,
          alignment: Alignment.centerLeft,
          child: Text(value,
              style: text.headlineMedium
                  ?.copyWith(fontFeatures: const [FontFeature.tabularFigures()])),
        ),
        Text(caption, style: text.bodySmall?.copyWith(color: muted)),
      ],
    );
  }
}

class _Hint extends StatelessWidget {
  const _Hint({required this.session});
  final Session session;

  @override
  Widget build(BuildContext context) {
    final r = session.latest;
    final String? hint;
    if (r == null) {
      hint = 'Waiting for the first reading…';
    } else if (!r.blanked) {
      hint = 'Fill the cup with clear water, put the lid on, then tap Blank.';
    } else if (!r.running && session.run.isEmpty) {
      hint = session.autoZero
          ? 'Ready. Drop the tablet in: the clock starts when transmission falls.'
          : 'Ready. Drop the tablet in and tap Start.';
    } else {
      hint = null;
    }
    if (hint == null) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(top: 12),
      child: Card(
        color: Theme.of(context).colorScheme.secondaryContainer,
        child: ListTile(
          leading: const Icon(Icons.lightbulb_outline),
          title: Text(hint),
        ),
      ),
    );
  }
}

class _ChartCard extends StatelessWidget {
  const _ChartCard({required this.session});
  final Session session;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final text = Theme.of(context).textTheme;
    final run = session.run;

    final String title;
    final List<Series> series;
    final Widget chart;
    if (run.isNotEmpty) {
      title = session.latest?.running == true ? 'Dissolution curve' : 'Last run';
      series = [
        Series('Absorbance', scheme.primary, [
          for (final r in run)
            if (r.absT != null) Offset(r.t!, r.absT!)
        ]),
        Series('Cloudiness', scheme.tertiary, [
          for (final r in run)
            if (r.cloudiness != null) Offset(r.t!, r.cloudiness!)
        ]),
      ];
      chart = LineChart(series: series, xLabel: 'time', formatX: _clock, yDecimals: 2);
    } else {
      title = 'Live transmission';
      final recent = session.recent;
      series = [
        Series('Transmission, mV', scheme.primary, [
          for (var i = 0; i < recent.length; i++)
            Offset((i - recent.length + 1).toDouble(), recent[i].transMv)
        ]),
      ];
      chart = LineChart(
        series: series,
        xLabel: 'seconds',
        formatX: (x) => x >= 0 ? 'now' : '${x.round()} s',
        minYSpan: 40,
        yDecimals: 0,
      );
    }

    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 12, 16, 12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.only(left: 4),
              child: Text(title, style: text.titleMedium),
            ),
            const SizedBox(height: 4),
            Wrap(spacing: 16, children: [
              for (final s in series)
                Row(mainAxisSize: MainAxisSize.min, children: [
                  Container(width: 14, height: 3, color: s.color),
                  const SizedBox(width: 6),
                  Text(s.label, style: text.bodySmall),
                ]),
            ]),
            const SizedBox(height: 8),
            SizedBox(
              height: 220,
              child: series.every((s) => s.points.isEmpty)
                  ? Center(child: Text('No data yet', style: text.bodyMedium))
                  : chart,
            ),
          ],
        ),
      ),
    );
  }
}

class _Readouts extends StatelessWidget {
  const _Readouts({required this.reading});
  final Reading? reading;

  @override
  Widget build(BuildContext context) {
    final r = reading;
    final tiles = [
      _Tile(Icons.flare, 'Transmission', r == null ? '—' : '${r.transMv.round()} mV'),
      _Tile(Icons.blur_on, 'Scatter', r == null ? '—' : '${r.scatMv.round()} mV'),
      _Tile(Icons.thermostat, 'Temperature',
          r?.tempC == null ? 'no probe' : '${r!.tempC!.toStringAsFixed(1)} °C'),
      _Tile(Icons.cyclone, 'Stirrer',
          r == null ? '—' : (r.stirPct > 0 ? '${r.stirPct} %' : 'off')),
    ];
    return LayoutBuilder(builder: (context, box) {
      final w = (box.maxWidth - 12) / 2;
      return Wrap(
        spacing: 12,
        runSpacing: 12,
        children: [for (final t in tiles) SizedBox(width: w, child: t)],
      );
    });
  }
}

class _Tile extends StatelessWidget {
  const _Tile(this.icon, this.label, this.value);
  final IconData icon;
  final String label, value;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final muted = Theme.of(context).colorScheme.onSurfaceVariant;
    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Row(children: [
          Icon(icon, color: muted),
          const SizedBox(width: 10),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(label, style: text.labelMedium?.copyWith(color: muted)),
              Text(value,
                  style: text.titleMedium
                      ?.copyWith(fontFeatures: const [FontFeature.tabularFigures()]),
                  overflow: TextOverflow.ellipsis),
            ]),
          ),
        ]),
      ),
    );
  }
}

class _SweepCard extends StatelessWidget {
  const _SweepCard({required this.reading});
  final Reading? reading;

  static const _fullScale = 3300.0; // the ADC ceiling, so the four bars are comparable

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final track = Theme.of(context).colorScheme.surfaceContainerHighest;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Colour sweep', style: text.titleMedium),
            Text('Transmission under each LED, every 10 s',
                style: text.bodySmall
                    ?.copyWith(color: Theme.of(context).colorScheme.onSurfaceVariant)),
            const SizedBox(height: 12),
            for (final c in Reading.colours) ...[
              Row(children: [
                SizedBox(width: 56, child: Text(c, style: text.bodyMedium)),
                Expanded(
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(4),
                    child: LinearProgressIndicator(
                      value: ((reading?.sweep[c] ?? 0) / _fullScale).clamp(0.0, 1.0),
                      minHeight: 12,
                      color: _sweepColours[c],
                      backgroundColor: track,
                    ),
                  ),
                ),
                SizedBox(
                  width: 64,
                  child: Text(
                    reading?.sweep[c] == null ? '—' : '${reading!.sweep[c]!.round()} mV',
                    textAlign: TextAlign.right,
                    style: text.bodyMedium
                        ?.copyWith(fontFeatures: const [FontFeature.tabularFigures()]),
                  ),
                ),
              ]),
              const SizedBox(height: 8),
            ],
          ],
        ),
      ),
    );
  }
}

class _Controls extends StatelessWidget {
  const _Controls({required this.session});
  final Session session;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final stirring = (session.latest?.stirPct ?? 0) > 0;
    Widget button(String cmd, IconData icon, String label) => FilledButton.tonalIcon(
          onPressed: session.stale ? null : () => session.send(cmd),
          icon: Icon(icon),
          label: Text(label),
        );
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Controls', style: text.titleMedium),
            const SizedBox(height: 12),
            Wrap(spacing: 8, runSpacing: 8, children: [
              button('b', Icons.water_drop_outlined, 'Blank'),
              button('z', Icons.play_arrow, 'Start'),
              button('s', Icons.stop, 'Stop'),
              button('m', Icons.cyclone, stirring ? 'Stirrer off' : 'Stirrer on'),
            ]),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Auto start'),
              subtitle: const Text('Start the clock when the tablet hits the water'),
              value: session.autoZero,
              onChanged: session.stale ? null : (_) => session.send('a'),
            ),
          ],
        ),
      ),
    );
  }
}

class _Notes extends StatelessWidget {
  const _Notes({required this.notes});
  final List<String> notes;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final recent = notes.reversed.take(6).toList();
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Board messages', style: text.titleMedium),
            const SizedBox(height: 8),
            if (recent.isEmpty) Text('None yet', style: text.bodySmall),
            for (final n in recent)
              Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Text(n, style: text.bodySmall?.copyWith(fontFamily: 'monospace')),
              ),
          ],
        ),
      ),
    );
  }
}
