import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:http/http.dart' as http;
import 'package:http_parser/http_parser.dart';

import '../data/api_models.dart';

class PeelApiException implements Exception {
  PeelApiException(this.message, {this.statusCode});

  final String message;
  final int? statusCode;

  @override
  String toString() => message;
}

class PeelApi {
  PeelApi({String? baseUrl, http.Client? client})
    : baseUrl =
          (baseUrl ??
                  const String.fromEnvironment(
                    'PEEL_API_BASE',
                    defaultValue:
                        'https://m2cw0a06ep8e5g-8000.proxy.runpod.net',
                  ))
              .replaceAll(RegExp(r'/$'), ''),
      _client = client ?? http.Client();

  final String baseUrl;
  final http.Client _client;

  Uri _uri(String path) => Uri.parse('$baseUrl$path');

  Future<BottlePhotoResult> identifyBottle(File photo) async {
    final body = await _upload('/photo-identification/bottle', photo);
    return BottlePhotoResult.fromJson(
      body['result'] as Map<String, dynamic>? ?? const {},
    );
  }

  Future<ImprintPhotoResult> identifyImprint(File photo) async {
    final body = await _upload('/photo-identification/imprint', photo);
    return ImprintPhotoResult.fromJson(
      body['result'] as Map<String, dynamic>? ?? const {},
    );
  }

  Future<ScanEnvelope> createScan({
    required String deviceId,
    BottlePhotoResult? bottle,
    ImprintPhotoResult? imprint,
    PillHardwareResult? hardware,
    String? hardwareModel,
    List<PhotoRef> photos = const [],
  }) async {
    return ScanEnvelope.fromJson(
      await _json(
        'POST',
        '/scans',
        body: {
          'device_id': deviceId,
          'demo': false,
          if (bottle != null) 'bottle': bottle.toJson(),
          if (imprint != null) 'imprint': imprint.toJson(),
          if (hardware != null) 'hardware': hardware.toJson(),
          if (hardwareModel != null) 'hardware_model': hardwareModel,
          if (photos.isNotEmpty)
            'photos': [for (final photo in photos) photo.toJson()],
        },
      ),
    );
  }

  Future<ScanEnvelope> getScan(String scanId) async {
    return ScanEnvelope.fromJson(await _json('GET', '/scans/$scanId'));
  }

  Future<DeepgramSession> createSession(String scanId) async {
    return DeepgramSession.fromJson(
      await _json('POST', '/deepgram/session', body: {'scan_id': scanId}),
    );
  }

  Future<FiledReport> submitReport(String scanId, ReportDraft draft) async {
    return FiledReport.fromJson(
      await _json('POST', '/scans/$scanId/reports', body: draft.toJson()),
    );
  }

  Future<List<FiledReport>> listReports(String scanId) async {
    final body = await _json('GET', '/scans/$scanId/reports');
    final results = body['results'] as List? ?? const [];
    return [
      for (final item in results)
        FiledReport.fromJson(item as Map<String, dynamic>),
    ];
  }

  Future<PhotoRef> photoRef(String target, File file) async {
    final bytes = await file.readAsBytes();
    return PhotoRef(
      target: target,
      sha256: sha256.convert(bytes).toString(),
      bytes: bytes.length,
      mediaType: _mediaType(file.path).mimeType,
    );
  }

  Future<Map<String, dynamic>> _upload(String path, File photo) async {
    final request = http.MultipartRequest('POST', _uri(path))
      ..files.add(
        await http.MultipartFile.fromPath(
          'upload',
          photo.path,
          contentType: _mediaType(photo.path),
        ),
      );
    final streamed = await _client
        .send(request)
        .timeout(const Duration(seconds: 90));
    final response = await http.Response.fromStream(streamed);
    return _decode(response);
  }

  Future<Map<String, dynamic>> _json(
    String method,
    String path, {
    Object? body,
  }) async {
    final uri = _uri(path);
    final headers = {'Accept': 'application/json'};
    late http.Response response;
    if (method == 'GET') {
      response = await _client
          .get(uri, headers: headers)
          .timeout(const Duration(seconds: 30));
    } else {
      headers['Content-Type'] = 'application/json';
      final encoded = jsonEncode(body ?? {});
      response = method == 'POST'
          ? await _client
                .post(uri, headers: headers, body: encoded)
                .timeout(const Duration(seconds: 30))
          : await _client
                .put(uri, headers: headers, body: encoded)
                .timeout(const Duration(seconds: 30));
    }
    return _decode(response);
  }

  Map<String, dynamic> _decode(http.Response response) {
    Map<String, dynamic>? json;
    if (response.body.isNotEmpty) {
      try {
        final decoded = jsonDecode(response.body);
        if (decoded is Map<String, dynamic>) json = decoded;
      } on FormatException {
        json = null;
      }
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw PeelApiException(
        _errorMessage(json, response),
        statusCode: response.statusCode,
      );
    }
    return json ?? {};
  }

  String _errorMessage(Map<String, dynamic>? json, http.Response response) {
    final detail = json?['detail'];
    if (detail is String && detail.isNotEmpty) return detail;
    if (detail != null) return detail.toString();
    return 'Request failed (${response.statusCode})';
  }

  MediaType _mediaType(String path) {
    final lower = path.toLowerCase();
    if (lower.endsWith('.png')) return MediaType('image', 'png');
    if (lower.endsWith('.webp')) return MediaType('image', 'webp');
    if (lower.endsWith('.gif')) return MediaType('image', 'gif');
    return MediaType('image', 'jpeg');
  }
}

final peelApi = PeelApi();
