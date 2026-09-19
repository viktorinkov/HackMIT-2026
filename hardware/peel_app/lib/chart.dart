import 'dart:math';

import 'package:flutter/material.dart';

class Series {
  const Series(this.label, this.color, this.points);
  final String label;
  final Color color;
  final List<Offset> points; // (x, y) in data units
}

/// A small, dependency-free line chart: gridlines, labelled y ticks, x range at the ends.
class LineChart extends StatelessWidget {
  const LineChart({
    super.key,
    required this.series,
    required this.xLabel,
    this.formatX,
    this.minYSpan = 0.02,
    this.yDecimals = 2,
  });

  final List<Series> series;
  final String xLabel;
  final String Function(double x)? formatX;

  /// Stops a flat, noisy signal from being stretched to fill the whole height.
  final double minYSpan;
  final int yDecimals;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return CustomPaint(
      painter: _ChartPainter(
        series: series,
        xLabel: xLabel,
        formatX: formatX ?? (x) => x.toStringAsFixed(0),
        minYSpan: minYSpan,
        yDecimals: yDecimals,
        grid: scheme.outlineVariant,
        text: scheme.onSurfaceVariant,
      ),
      child: const SizedBox.expand(),
    );
  }
}

class _ChartPainter extends CustomPainter {
  _ChartPainter({
    required this.series,
    required this.xLabel,
    required this.formatX,
    required this.minYSpan,
    required this.yDecimals,
    required this.grid,
    required this.text,
  });

  final List<Series> series;
  final String xLabel;
  final String Function(double) formatX;
  final double minYSpan;
  final int yDecimals;
  final Color grid, text;

  static const _left = 44.0, _bottom = 20.0, _top = 6.0, _right = 6.0;

  @override
  void paint(Canvas canvas, Size size) {
    final pts = [for (final s in series) ...s.points];
    if (pts.isEmpty) return;

    var x0 = pts.map((p) => p.dx).reduce(min), x1 = pts.map((p) => p.dx).reduce(max);
    var y0 = pts.map((p) => p.dy).reduce(min), y1 = pts.map((p) => p.dy).reduce(max);
    if (x1 - x0 < 1) x1 = x0 + 1;
    if (y1 - y0 < minYSpan) {
      final mid = (y0 + y1) / 2;
      y0 = mid - minYSpan / 2;
      y1 = mid + minYSpan / 2;
    }
    final pad = (y1 - y0) * 0.08;
    y0 -= pad;
    y1 += pad;

    final plot = Rect.fromLTRB(_left, _top, size.width - _right, size.height - _bottom);
    Offset at(Offset p) => Offset(
          plot.left + (p.dx - x0) / (x1 - x0) * plot.width,
          plot.bottom - (p.dy - y0) / (y1 - y0) * plot.height,
        );

    final gridPaint = Paint()
      ..color = grid
      ..strokeWidth = 1;
    const rows = 4;
    for (var i = 0; i <= rows; i++) {
      final y = plot.bottom - plot.height * i / rows;
      canvas.drawLine(Offset(plot.left, y), Offset(plot.right, y), gridPaint);
      _label(canvas, (y0 + (y1 - y0) * i / rows).toStringAsFixed(yDecimals),
          Offset(plot.left - 6, y), Alignment.centerRight);
    }
    _label(canvas, formatX(x0), Offset(plot.left, plot.bottom + 4), Alignment.topLeft);
    _label(canvas, xLabel, Offset(plot.center.dx, plot.bottom + 4), Alignment.topCenter);
    _label(canvas, formatX(x1), Offset(plot.right, plot.bottom + 4), Alignment.topRight);

    canvas.save();
    canvas.clipRect(plot);
    for (final s in series) {
      if (s.points.isEmpty) continue;
      final path = Path()..moveTo(at(s.points.first).dx, at(s.points.first).dy);
      for (final p in s.points.skip(1)) {
        final q = at(p);
        path.lineTo(q.dx, q.dy);
      }
      canvas.drawPath(
          path,
          Paint()
            ..color = s.color
            ..style = PaintingStyle.stroke
            ..strokeWidth = 2.5
            ..strokeJoin = StrokeJoin.round);
      canvas.drawCircle(at(s.points.last), 3.5, Paint()..color = s.color);
    }
    canvas.restore();
  }

  void _label(Canvas canvas, String s, Offset anchor, Alignment align) {
    final tp = TextPainter(
      text: TextSpan(text: s, style: TextStyle(color: text, fontSize: 11)),
      textDirection: TextDirection.ltr,
    )..layout();
    final dx = anchor.dx - tp.width * (align.x + 1) / 2;
    final dy = anchor.dy - tp.height * (align.y + 1) / 2;
    tp.paint(canvas, Offset(dx, dy));
  }

  @override
  bool shouldRepaint(_ChartPainter old) => true;
}
