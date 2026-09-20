import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:uuid/uuid.dart';

import '../data/api_models.dart';
import '../data/mock_data.dart';
import '../services/peel_api.dart';
import '../device/signals.dart';

export '../data/mock_data.dart' show ScanStep;

const _deviceIdKey = 'peel_user_uuid';

/// Single in-memory session shared by the scan screens.
class ScanSession extends ChangeNotifier {
  int generation = 0;
  bool hardwareSkipped = false;

  void skipHardware() {
    hardwareSkipped = true;
    hardware = null;
    runReadings = const [];
    runLogPath = null;
    notifyListeners();
  }

  List<Reading> runReadings = const [];
  String? runLogPath;

  void finishRun(List<Reading> readings, String? logPath) {
    hardwareSkipped = false;
    runReadings = List.unmodifiable(readings);
    runLogPath = logPath;
    notifyListeners();
  }

  File? bottlePhoto;
  File? imprintPhoto;
  BottlePhotoResult? bottleResult;
  ImprintPhotoResult? imprintResult;
  PhotoRef? bottleRef;
  PhotoRef? imprintRef;
  PillHardwareAnalysis? hardware;
  String? scanId;
  ScanEnvelope? scan;
  ReportDraft reportDraft = const ReportDraft();
  String? deviceId;

  ResearchReport? get research => scan?.research;

  Future<void> loadDeviceId() async {
    final prefs = await SharedPreferences.getInstance();
    var id = prefs.getString(_deviceIdKey);
    if (id == null || id.isEmpty) {
      id = const Uuid().v4();
      await prefs.setString(_deviceIdKey, id);
    }
    deviceId = id;
    notifyListeners();
  }

  void setPhoto(ScanStep step, File? photo) {
    switch (step) {
      case ScanStep.bottle:
        bottlePhoto = photo;
        if (photo == null) {
          bottleResult = null;
          bottleRef = null;
        }
      case ScanStep.imprint:
        imprintPhoto = photo;
        if (photo == null) {
          imprintResult = null;
          imprintRef = null;
        }
      case ScanStep.pill:
        break;
    }
    notifyListeners();
  }

  File? photoFor(ScanStep step) => switch (step) {
    ScanStep.bottle => bottlePhoto,
    ScanStep.imprint => imprintPhoto,
    ScanStep.pill => null,
  };

  bool hasVision(ScanStep step) => switch (step) {
    ScanStep.bottle => bottleResult != null,
    ScanStep.imprint => imprintResult != null,
    ScanStep.pill => false,
  };

  Future<void> identifyPhoto(ScanStep step, File photo) async {
    switch (step) {
      case ScanStep.bottle:
        bottlePhoto = photo;
        bottleResult = await peelApi.identifyBottle(photo);
        bottleRef = await peelApi.photoRef('bottle', photo);
      case ScanStep.imprint:
        imprintPhoto = photo;
        imprintResult = await peelApi.identifyImprint(photo);
        imprintRef = await peelApi.photoRef('imprint', photo);
      case ScanStep.pill:
        break;
    }
    notifyListeners();
  }

  void clearVision(ScanStep step) {
    switch (step) {
      case ScanStep.bottle:
        bottleResult = null;
        bottleRef = null;
      case ScanStep.imprint:
        imprintResult = null;
        imprintRef = null;
      case ScanStep.pill:
        break;
    }
    notifyListeners();
  }

  void applyDraft(ReportDraft draft) {
    reportDraft = draft;
    notifyListeners();
  }

  void reset() {
    generation++;
    hardwareSkipped = false;
    runReadings = const [];
    runLogPath = null;
    bottlePhoto = null;
    imprintPhoto = null;
    bottleResult = null;
    imprintResult = null;
    bottleRef = null;
    imprintRef = null;
    hardware = null;
    scanId = null;
    scan = null;
    reportDraft = const ReportDraft();
    notifyListeners();
  }
}

final scanSession = ScanSession();
