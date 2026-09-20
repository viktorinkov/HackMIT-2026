// JSON shapes from the Peel FastAPI on RunPod.

class BottlePhotoResult {
  const BottlePhotoResult({
    required this.isMedicationContainer,
    this.brandName,
    this.genericName,
    this.strength,
    this.form,
    this.quantity,
    this.ndc,
    this.manufacturer,
    this.pharmacy,
    this.rxNumber,
    this.directions,
    this.expiration,
    this.lotNumber,
    this.imprintOnLabel,
    this.visibleWarnings = const [],
    this.otherLabelText,
    required this.confidence,
    this.notes,
  });

  final bool isMedicationContainer;
  final String? brandName;
  final String? genericName;
  final String? strength;
  final String? form;
  final String? quantity;
  final String? ndc;
  final String? manufacturer;
  final String? pharmacy;
  final String? rxNumber;
  final String? directions;
  final String? expiration;
  final String? lotNumber;
  final String? imprintOnLabel;
  final List<String> visibleWarnings;
  final String? otherLabelText;
  final double confidence;
  final String? notes;

  factory BottlePhotoResult.fromJson(Map<String, dynamic> json) {
    return BottlePhotoResult(
      isMedicationContainer: json['is_medication_container'] as bool? ?? false,
      brandName: json['brand_name'] as String?,
      genericName: json['generic_name'] as String?,
      strength: json['strength'] as String?,
      form: json['form'] as String?,
      quantity: json['quantity'] as String?,
      ndc: json['ndc'] as String?,
      manufacturer: json['manufacturer'] as String?,
      pharmacy: json['pharmacy'] as String?,
      rxNumber: json['rx_number'] as String?,
      directions: json['directions'] as String?,
      expiration: json['expiration'] as String?,
      lotNumber: json['lot_number'] as String?,
      imprintOnLabel: json['imprint_on_label'] as String?,
      visibleWarnings: _stringList(json['visible_warnings']),
      otherLabelText: json['other_label_text'] as String?,
      confidence: (json['confidence'] as num?)?.toDouble() ?? 0,
      notes: json['notes'] as String?,
    );
  }

  Map<String, dynamic> toJson() => {
        'is_medication_container': isMedicationContainer,
        'brand_name': brandName,
        'generic_name': genericName,
        'strength': strength,
        'form': form,
        'quantity': quantity,
        'ndc': ndc,
        'manufacturer': manufacturer,
        'pharmacy': pharmacy,
        'rx_number': rxNumber,
        'directions': directions,
        'expiration': expiration,
        'lot_number': lotNumber,
        'imprint_on_label': imprintOnLabel,
        'visible_warnings': visibleWarnings,
        'other_label_text': otherLabelText,
        'confidence': confidence,
        'notes': notes,
      };

  String get displayName {
    final name = genericName ?? brandName;
    if (name == null) return 'Bottle';
    if (strength == null || strength!.isEmpty) return name;
    return '$name · $strength';
  }
}

class ImprintPhotoResult {
  const ImprintPhotoResult({
    required this.isPill,
    this.imprint,
    this.color,
    this.shape,
    this.form,
    this.score,
    this.additionalMarkings,
    required this.confidence,
    this.notes,
  });

  final bool isPill;
  final String? imprint;
  final String? color;
  final String? shape;
  final String? form;
  final String? score;
  final String? additionalMarkings;
  final double confidence;
  final String? notes;

  factory ImprintPhotoResult.fromJson(Map<String, dynamic> json) {
    return ImprintPhotoResult(
      isPill: json['is_pill'] as bool? ?? false,
      imprint: json['imprint'] as String?,
      color: json['color'] as String?,
      shape: json['shape'] as String?,
      form: json['form'] as String?,
      score: json['score'] as String?,
      additionalMarkings: json['additional_markings'] as String?,
      confidence: (json['confidence'] as num?)?.toDouble() ?? 0,
      notes: json['notes'] as String?,
    );
  }

  Map<String, dynamic> toJson() => {
        'is_pill': isPill,
        'imprint': imprint,
        'color': color,
        'shape': shape,
        'form': form,
        'score': score,
        'additional_markings': additionalMarkings,
        'confidence': confidence,
        'notes': notes,
      };

  String get display {
    final mark = imprint;
    if (mark == null || mark.isEmpty) return 'Imprint not read';
    final extras = [color, shape].whereType<String>().where((s) => s.isNotEmpty);
    if (extras.isEmpty) return mark;
    return '$mark · ${extras.join(' · ')}';
  }
}

class PillHardwareResult {
  const PillHardwareResult({
    required this.status,
    required this.spectrum,
    this.pillType,
    required this.degraded,
    required this.confidence,
  });

  final String status;
  final List<double> spectrum;
  final String? pillType;
  final bool degraded;
  final double confidence;

  factory PillHardwareResult.fromJson(Map<String, dynamic> json) {
    return PillHardwareResult(
      status: json['status'] as String? ?? 'unknown',
      spectrum: [
        for (final value in json['spectrum'] as List? ?? const [])
          (value as num).toDouble(),
      ],
      pillType: json['pill_type'] as String?,
      degraded: json['degraded'] as bool? ?? false,
      confidence: (json['confidence'] as num?)?.toDouble() ?? 0,
    );
  }

  Map<String, dynamic> toJson() => {
        'status': status,
        'spectrum': spectrum,
        'pill_type': pillType,
        'degraded': degraded,
        'confidence': confidence,
      };
}

class PillHardwareAnalysis {
  const PillHardwareAnalysis({required this.model, required this.result});

  final String model;
  final PillHardwareResult result;

  factory PillHardwareAnalysis.fromJson(Map<String, dynamic> json) {
    return PillHardwareAnalysis(
      model: json['model'] as String? ?? 'unknown',
      result: PillHardwareResult.fromJson(
        json['result'] as Map<String, dynamic>? ?? const {},
      ),
    );
  }
}

class PhotoRef {
  const PhotoRef({
    required this.target,
    required this.sha256,
    required this.bytes,
    required this.mediaType,
  });

  final String target;
  final String sha256;
  final int bytes;
  final String mediaType;

  Map<String, dynamic> toJson() => {
        'target': target,
        'sha256': sha256,
        'bytes': bytes,
        'media_type': mediaType,
      };
}

class SourceRef {
  const SourceRef({
    required this.id,
    required this.title,
    this.url,
    this.sourceOrg,
    this.publishedAt,
    this.labelDate,
  });

  final String id;
  final String title;
  final String? url;
  final String? sourceOrg;
  final String? publishedAt;
  final String? labelDate;

  factory SourceRef.fromJson(Map<String, dynamic> json) {
    return SourceRef(
      id: json['id'] as String? ?? '',
      title: json['title'] as String? ?? '',
      url: json['url'] as String?,
      sourceOrg: json['source_org'] as String?,
      publishedAt: json['published_at'] as String?,
      labelDate: json['label_date'] as String?,
    );
  }
}

class Finding {
  const Finding({
    required this.statement,
    required this.evidenceType,
    required this.sourceIds,
    required this.severity,
    this.countryScope,
  });

  final String statement;
  final String evidenceType;
  final List<String> sourceIds;
  final String severity;
  final String? countryScope;

  factory Finding.fromJson(Map<String, dynamic> json) {
    return Finding(
      statement: json['statement'] as String? ?? '',
      evidenceType: json['evidence_type'] as String? ?? '',
      sourceIds: _stringList(json['source_ids']),
      severity: json['severity'] as String? ?? 'info',
      countryScope: json['country_scope'] as String?,
    );
  }
}

class Mismatch {
  const Mismatch({
    required this.field,
    this.bottleClaim,
    this.imprintReference,
    this.hardwareReport,
    required this.explanation,
    required this.sourceIds,
  });

  final String field;
  final String? bottleClaim;
  final String? imprintReference;
  final String? hardwareReport;
  final String explanation;
  final List<String> sourceIds;

  factory Mismatch.fromJson(Map<String, dynamic> json) {
    return Mismatch(
      field: json['field'] as String? ?? '',
      bottleClaim: json['bottle_claim'] as String?,
      imprintReference: json['imprint_reference'] as String?,
      hardwareReport: json['hardware_report'] as String?,
      explanation: json['explanation'] as String? ?? '',
      sourceIds: _stringList(json['source_ids']),
    );
  }
}

class DrugFact {
  const DrugFact({
    required this.medicationId,
    required this.topic,
    required this.text,
    required this.sourceIds,
  });

  final String medicationId;
  final String topic;
  final String text;
  final List<String> sourceIds;

  factory DrugFact.fromJson(Map<String, dynamic> json) {
    return DrugFact(
      medicationId: json['medication_id'] as String? ?? '',
      topic: json['topic'] as String? ?? '',
      text: json['text'] as String? ?? '',
      sourceIds: _stringList(json['source_ids']),
    );
  }
}

class ResearchReport {
  const ResearchReport({
    required this.verdict,
    required this.riskLevel,
    required this.headline,
    required this.findings,
    required this.mismatches,
    required this.recallHits,
    required this.gaps,
    required this.nextSteps,
    required this.drugFacts,
    required this.sources,
    required this.agentUsed,
    required this.demo,
  });

  final String verdict;
  final String riskLevel;
  final String headline;
  final List<Finding> findings;
  final List<Mismatch> mismatches;
  final List<SourceRef> recallHits;
  final List<String> gaps;
  final List<String> nextSteps;
  final List<DrugFact> drugFacts;
  final List<SourceRef> sources;
  final bool agentUsed;
  final bool demo;

  factory ResearchReport.fromJson(Map<String, dynamic> json) {
    return ResearchReport(
      verdict: json['verdict'] as String? ?? 'insufficient_evidence',
      riskLevel: json['risk_level'] as String? ?? 'unknown',
      headline: json['headline'] as String? ?? '',
      findings: [
        for (final item in json['findings'] as List? ?? const [])
          Finding.fromJson(item as Map<String, dynamic>),
      ],
      mismatches: [
        for (final item in json['mismatches'] as List? ?? const [])
          Mismatch.fromJson(item as Map<String, dynamic>),
      ],
      recallHits: [
        for (final item in json['recall_hits'] as List? ?? const [])
          SourceRef.fromJson(item as Map<String, dynamic>),
      ],
      gaps: _stringList(json['gaps']),
      nextSteps: _stringList(json['next_steps']),
      drugFacts: [
        for (final item in json['drug_facts'] as List? ?? const [])
          DrugFact.fromJson(item as Map<String, dynamic>),
      ],
      sources: [
        for (final item in json['sources'] as List? ?? const [])
          SourceRef.fromJson(item as Map<String, dynamic>),
      ],
      agentUsed: json['agent_used'] as bool? ?? false,
      demo: json['demo'] as bool? ?? false,
    );
  }

  bool get canReport => verdict != 'no_adverse_findings';
}

class ScanEnvelope {
  const ScanEnvelope({
    required this.scanId,
    required this.deviceId,
    this.country,
    required this.revision,
    required this.status,
    required this.demo,
    required this.createdAt,
    required this.updatedAt,
    this.bottle,
    this.imprint,
    this.hardware,
    this.research,
  });

  final String scanId;
  final String deviceId;
  final String? country;
  final int revision;
  final String status;
  final bool demo;
  final String createdAt;
  final String updatedAt;
  final Map<String, dynamic>? bottle;
  final Map<String, dynamic>? imprint;
  final Map<String, dynamic>? hardware;
  final ResearchReport? research;

  factory ScanEnvelope.fromJson(Map<String, dynamic> json) {
    final research = json['research'];
    return ScanEnvelope(
      scanId: json['scan_id'] as String,
      deviceId: json['device_id'] as String,
      country: json['country'] as String?,
      revision: json['revision'] as int? ?? 1,
      status: json['status'] as String? ?? 'pending',
      demo: json['demo'] as bool? ?? false,
      createdAt: json['created_at'] as String? ?? '',
      updatedAt: json['updated_at'] as String? ?? '',
      bottle: json['bottle'] as Map<String, dynamic>?,
      imprint: json['imprint'] as Map<String, dynamic>?,
      hardware: json['hardware'] as Map<String, dynamic>?,
      research: research is Map<String, dynamic>
          ? ResearchReport.fromJson(research)
          : null,
    );
  }
}

class DeepgramSession {
  const DeepgramSession({
    required this.scanId,
    required this.websocketUrl,
    required this.authorization,
    this.accessToken,
    this.expiresIn,
    this.grantError,
    required this.settings,
    required this.openingMessages,
  });

  final String scanId;
  final String websocketUrl;
  final String authorization;
  final String? accessToken;
  final int? expiresIn;
  final String? grantError;
  final Map<String, dynamic> settings;
  final List<String> openingMessages;

  factory DeepgramSession.fromJson(Map<String, dynamic> json) {
    return DeepgramSession(
      scanId: json['scan_id'] as String,
      websocketUrl: json['websocket_url'] as String,
      authorization: json['authorization'] as String,
      accessToken: json['access_token'] as String?,
      expiresIn: json['expires_in'] as int?,
      grantError: json['grant_error'] as String?,
      settings: Map<String, dynamic>.from(json['settings'] as Map? ?? const {}),
      openingMessages: _stringList(json['opening_messages']),
    );
  }
}

class PurchaseLocation {
  const PurchaseLocation({
    this.label,
    this.city,
    this.region,
    this.country,
  });

  final String? label;
  final String? city;
  final String? region;
  final String? country;

  factory PurchaseLocation.fromJson(Map<String, dynamic> json) {
    return PurchaseLocation(
      label: json['label'] as String?,
      city: json['city'] as String?,
      region: json['region'] as String?,
      country: json['country'] as String?,
    );
  }

  Map<String, dynamic> toJson() => {
        if (label != null) 'label': label,
        if (city != null) 'city': city,
        if (region != null) 'region': region,
        if (country != null) 'country': country,
      };

  bool get isEmpty =>
      (label == null || label!.isEmpty) &&
      (city == null || city!.isEmpty) &&
      (region == null || region!.isEmpty) &&
      (country == null || country!.isEmpty);

  String get display {
    final parts = [label, city, region, country]
        .whereType<String>()
        .where((part) => part.isNotEmpty);
    return parts.join(' · ');
  }
}

class ReportDraft {
  const ReportDraft({this.purchasedOn, this.purchaseLocation, this.seller});

  final String? purchasedOn;
  final PurchaseLocation? purchaseLocation;
  final String? seller;

  factory ReportDraft.fromJson(Map<String, dynamic> json) {
    final location = json['purchase_location'];
    return ReportDraft(
      purchasedOn: json['purchased_on'] as String?,
      purchaseLocation: location is Map<String, dynamic>
          ? PurchaseLocation.fromJson(location)
          : location is String && location.trim().isNotEmpty
              ? PurchaseLocation(label: location.trim())
              : null,
      seller: json['seller'] as String?,
    );
  }

  Map<String, dynamic> toJson() => {
        if (purchasedOn != null) 'purchased_on': purchasedOn,
        if (purchaseLocation != null && !purchaseLocation!.isEmpty)
          'purchase_location': purchaseLocation!.toJson(),
        if (seller != null) 'seller': seller,
      };

  ReportDraft copyWith({
    String? purchasedOn,
    PurchaseLocation? purchaseLocation,
    String? seller,
  }) {
    return ReportDraft(
      purchasedOn: purchasedOn ?? this.purchasedOn,
      purchaseLocation: purchaseLocation ?? this.purchaseLocation,
      seller: seller ?? this.seller,
    );
  }
}

class FiledReport {
  const FiledReport({
    required this.reportId,
    required this.scanId,
    this.purchasedOn,
    this.purchaseLocation,
    this.seller,
    required this.createdAt,
  });

  final String reportId;
  final String scanId;
  final String? purchasedOn;
  final PurchaseLocation? purchaseLocation;
  final String? seller;
  final String createdAt;

  factory FiledReport.fromJson(Map<String, dynamic> json) {
    final location = json['purchase_location'];
    return FiledReport(
      reportId: json['report_id'] as String,
      scanId: json['scan_id'] as String,
      purchasedOn: json['purchased_on'] as String?,
      purchaseLocation: location is Map<String, dynamic>
          ? PurchaseLocation.fromJson(location)
          : null,
      seller: json['seller'] as String?,
      createdAt: json['created_at'] as String? ?? '',
    );
  }
}

List<String> _stringList(Object? value) {
  if (value is! List) return const [];
  return [for (final item in value) item.toString()];
}
