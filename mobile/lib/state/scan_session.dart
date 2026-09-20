import 'dart:io';

import 'package:flutter/foundation.dart';

import '../data/mock_data.dart';

export '../data/mock_data.dart' show ScanStep;

/// Single in-memory session shared by the demo screens.
class ScanSession extends ChangeNotifier {
  File? bottlePhoto;
  File? imprintPhoto;
  File? pillPhoto;

  ScanResult result = MockBackend.evaluate();

  String concern = 'I have a concern about this pill.';
  String dateNoticed = 'Today';
  String medicineName = 'Acetaminophen';
  String strength = '500 mg';
  String manufacturer = 'Not on the bottle';
  String lotNumber = 'Not on the bottle';
  String expiryDate = 'Not on the bottle';

  void setPhoto(ScanStep step, File? photo) {
    switch (step) {
      case ScanStep.bottle:
        bottlePhoto = photo;
      case ScanStep.imprint:
        imprintPhoto = photo;
      case ScanStep.pill:
        pillPhoto = photo;
    }
    notifyListeners();
  }

  File? photoFor(ScanStep step) => switch (step) {
        ScanStep.bottle => bottlePhoto,
        ScanStep.imprint => imprintPhoto,
        ScanStep.pill => pillPhoto,
      };

  void cycleResult() {
    result = MockBackend.next(result);
    notifyListeners();
  }

  void updateReport({
    String? concern,
    String? dateNoticed,
    String? medicineName,
    String? strength,
    String? manufacturer,
    String? lotNumber,
    String? expiryDate,
  }) {
    this.concern = concern ?? this.concern;
    this.dateNoticed = dateNoticed ?? this.dateNoticed;
    this.medicineName = medicineName ?? this.medicineName;
    this.strength = strength ?? this.strength;
    this.manufacturer = manufacturer ?? this.manufacturer;
    this.lotNumber = lotNumber ?? this.lotNumber;
    this.expiryDate = expiryDate ?? this.expiryDate;
    notifyListeners();
  }

  void reset() {
    bottlePhoto = null;
    imprintPhoto = null;
    pillPhoto = null;
    result = MockBackend.evaluate();
    notifyListeners();
  }
}

/// The demo runs against one session instance.
final scanSession = ScanSession();
