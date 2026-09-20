// GraphScreen: embeds the Peel Atlas evidence graph (served by the FastAPI
// backend at /atlas/) inside the Flutter app via webview_flutter.
//
// See backend/src/backend/graph/handoff/FLUTTER_HANDOFF.md before wiring this in — in particular
// the manifest edits it needs and the warning about what happens if Android
// kills the WebView's renderer process.
//
// Bridge contract v1 (matches backend/src/backend/graph/static/js/bridge.js
// and js/bridge-protocol.js exactly; all three are kept message-for-message
// in sync — do not invent a new message shape here without updating both):
//
//   Page -> app, via the `PeelBridge` JavaScript channel
//   (window.PeelBridge.postMessage(JSON.stringify(msg))). Every message
//   carries v:1.
//     {v:1, type:'ready'}
//     {v:1, type:'graph_loaded', nodes, links, demo}
//     {v:1, type:'node_selected', node:{id, type, label, scan_id?}}
//     {v:1, type:'open_scan', scan_id}
//     {v:1, type:'open_url', url}
//     {v:1, type:'error', code, message}
//     {v:1, type:'back_result', handled}
//
//   App -> page, via window.PeelAtlas.receive(jsonString):
//     {type:'set_device', device_id, demo?}
//     {type:'focus_node', node_id, expand?}
//     {type:'back'}
//
// The device id travels only over this bridge (`set_device`), never in the
// page URL — so nothing sensitive ends up in a WebView navigation log.
//
// `back`/`back_result` is a request/reply pair: the app sends `back` on the
// Android back gesture/button, the page tries to close its own search modal
// or collapse the bottom sheet or clear the selection (in that order) and
// replies `back_result {handled}`. `handled:false` means the page had
// nothing left to do with it, so the app should pop the route itself — see
// `_handleSystemBack` below, which gives the page up to 300ms to reply
// before popping anyway (a wedged or unresponsive WebView must never make
// the back button stop working).

import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:webview_flutter/webview_flutter.dart';

/// Override at run time: `flutter run --dart-define=PEEL_API=http://<laptop-ip>:8010`.
/// The default (10.0.2.2) only resolves to the host machine from the Android
/// *emulator* — on the real phone at the venue this must be the laptop's
/// hotspot IP (see FLUTTER_HANDOFF.md "Networking"). The page and the API are
/// the SAME FastAPI app, so this is also the base URL Peel's own API calls
/// already use — there is nothing separate to configure.
const String kPeelApi = String.fromEnvironment('PEEL_API', defaultValue: 'http://10.0.2.2:8010');

class GraphScreen extends StatefulWidget {
  const GraphScreen({
    super.key,
    required this.deviceId,
    this.demo = false,
    this.focusNodeId,
    this.onOpenScan,
  });

  final String deviceId;
  final bool demo;
  final String? focusNodeId;
  final ValueChanged<String>? onOpenScan;

  @override
  State<GraphScreen> createState() => _GraphScreenState();
}

class _GraphScreenState extends State<GraphScreen> {
  static const _bg = Color(0xFF131316); // matches css/tokens.css --bg-canvas
  late final WebViewController _web;
  Timer? _watchdog;
  bool _loaded = false;
  String? _error;
  Completer<bool>? _backCompleter;

  Uri get _url => Uri.parse('$kPeelApi/atlas/').replace(
        queryParameters: {'embed': '1', if (widget.demo) 'demo': '1'},
      );

  @override
  void initState() {
    super.initState();
    _web = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted) // JS is OFF by default; the graph needs it
      ..setBackgroundColor(_bg)
      ..addJavaScriptChannel('PeelBridge', onMessageReceived: _onBridge)
      ..setOnConsoleMessage((m) => debugPrint('[atlas] ${m.level.name}: ${m.message}'))
      ..setNavigationDelegate(NavigationDelegate(
        onNavigationRequest: (req) {
          if (req.url.startsWith(kPeelApi)) return NavigationDecision.navigate;
          _offerUrl(req.url); // an external source link never replaces the graph
          return NavigationDecision.prevent;
        },
        onWebResourceError: (e) {
          if (e.isForMainFrame ?? true) _fail('${e.errorCode}: ${e.description}');
        },
      ));
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _error = null;
      _loaded = false;
    });
    if (kDebugMode) await _web.clearCache(); // a stale bundle in the WebView cache never self-heals
    _watchdog?.cancel();
    _watchdog = Timer(const Duration(seconds: 15), () {
      if (!_loaded) _fail('Timed out reaching $kPeelApi');
    });
    await _web.loadRequest(_url);
  }

  void _fail(String message) {
    if (mounted) setState(() => _error = message);
  }

  Future<void> _send(Map<String, Object?> msg) =>
      // Double-encode: the outer jsonEncode makes the payload a safe JS string literal.
      _web.runJavaScript('window.PeelAtlas&&window.PeelAtlas.receive(${jsonEncode(jsonEncode(msg))});');

  void _onBridge(JavaScriptMessage m) {
    final Object? decoded;
    try {
      decoded = jsonDecode(m.message);
    } catch (_) {
      return;
    }
    if (decoded is! Map<String, dynamic>) return;
    switch (decoded['type']) {
      case 'ready':
        _send({'type': 'set_device', 'device_id': widget.deviceId, 'demo': widget.demo});
        if (widget.focusNodeId != null) {
          _send({'type': 'focus_node', 'node_id': widget.focusNodeId, 'expand': true});
        }
      case 'graph_loaded':
        _watchdog?.cancel();
        if (mounted) setState(() => _loaded = true);
      case 'open_scan':
        final id = decoded['scan_id'];
        if (id is String) widget.onOpenScan?.call(id);
      case 'open_url':
        final url = decoded['url'];
        if (url is String) _offerUrl(url);
      case 'error':
        _fail((decoded['message'] as String?) ?? 'The graph failed to load');
      case 'back_result':
        _backCompleter?.complete(decoded['handled'] == true);
    }
  }

  /// The Android back gesture/button: ask the page first (close its search
  /// modal, else collapse the sheet, else clear the selection), and only pop
  /// this route if the page says it had nothing left to do — or doesn't
  /// answer within 300ms, so a wedged WebView can never trap the user here.
  Future<void> _handleSystemBack() async {
    final completer = Completer<bool>();
    _backCompleter = completer;
    unawaited(_send({'type': 'back'}));
    bool handled;
    try {
      handled = await completer.future.timeout(const Duration(milliseconds: 300), onTimeout: () => false);
    } finally {
      if (identical(_backCompleter, completer)) _backCompleter = null;
    }
    if (!handled && mounted) Navigator.of(context).maybePop();
  }

  void _offerUrl(String url) {
    Clipboard.setData(ClipboardData(text: url));
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Link copied: $url')));
  }

  @override
  void dispose() {
    _watchdog?.cancel();
    _backCompleter = null;
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, result) {
        if (didPop) return;
        _handleSystemBack();
      },
      child: Scaffold(
        backgroundColor: _bg,
        appBar: AppBar(
          title: const Text('Evidence graph'),
          backgroundColor: _bg,
          foregroundColor: Colors.white,
          actions: [IconButton(tooltip: 'Reload', icon: const Icon(Icons.refresh), onPressed: _load)],
        ),
        body: Stack(children: [
          WebViewWidget(
            controller: _web,
            // Without this, Flutter's gesture arena steals the orbit/pinch
            // gesture from the canvas the moment this screen sits inside
            // anything scrollable (a PageView, a swipe-back gesture, ...).
            gestureRecognizers: {Factory<OneSequenceGestureRecognizer>(() => EagerGestureRecognizer())},
          ),
          if (!_loaded && _error == null) const Center(child: CircularProgressIndicator()),
          if (_error != null)
            Center(
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Column(mainAxisSize: MainAxisSize.min, children: [
                  const Icon(Icons.cloud_off, color: Colors.white70, size: 40),
                  const SizedBox(height: 12),
                  Text(_error!, textAlign: TextAlign.center, style: const TextStyle(color: Colors.white70)),
                  const SizedBox(height: 12),
                  FilledButton(onPressed: _load, child: const Text('Retry')),
                ]),
              ),
            ),
        ]),
      ),
    );
  }
}

// Hook it up wherever the app has a place to launch it, e.g. an AppBar
// action on the dashboard screen. IMPORTANT (see FLUTTER_HANDOFF.md): only
// ever push this while no spectrometer session is in progress — if Android
// kills the WebView's renderer process the whole app exits, including a live
// USB spectrometer session.
//
// IconButton(
//   tooltip: 'Evidence graph',
//   icon: const Icon(Icons.hub_outlined),
//   onPressed: () => Navigator.of(context).push(
//     MaterialPageRoute(builder: (_) => const GraphScreen(deviceId: 'demo-phone-1', demo: true)),
//   ),
// )
