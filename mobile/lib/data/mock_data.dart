/// Mocked backend data. The real app talks to the Peel FastAPI backend;
/// for the demo every result below is static.
enum ScanVerdict { match, mismatch, unconfirmed, degradation }

class RecognitionRow {
  const RecognitionRow(this.label, this.value, {this.detail});

  final String label;
  final String value;
  final String? detail;
}

class ScanResult {
  const ScanResult({
    required this.verdict,
    required this.finding,
    required this.findingDetail,
    required this.medicine,
    required this.rows,
    required this.facts,
    required this.sideEffects,
  });

  final ScanVerdict verdict;
  final String finding;
  final String findingDetail;
  final String medicine;
  final List<RecognitionRow> rows;
  final List<String> facts;
  final List<String> sideEffects;

  bool get canReport => verdict != ScanVerdict.match;
}

const _facts = [
  'Helps ease minor aches and pain.',
  'Lowers fever for a short time.',
  'Oral tablet.',
  'Bottle medicine · DailyMed',
];

const _sideEffects = [
  'Rash, blisters, or red skin can be serious. Stop taking it and get medical help now.',
  'Stop taking it and contact a doctor if new symptoms, redness, or swelling appear.',
];

/// Stand-in for the vision + judge models in the backend.
class MockBackend {
  static const ScanResult matchResult = ScanResult(
    verdict: ScanVerdict.match,
    finding: 'All three checks match',
    findingDetail: 'The bottle, the imprint and the pill agree.',
    medicine: 'Acetaminophen · 500 mg',
    rows: [
      RecognitionRow('Bottle', 'Acetaminophen · 500 mg'),
      RecognitionRow('Imprint', 'L484 · matches bottle', detail: 'White · oval'),
      RecognitionRow('Pill', 'Matches bottle'),
    ],
    facts: _facts,
    sideEffects: _sideEffects,
  );

  static const ScanResult mismatchResult = ScanResult(
    verdict: ScanVerdict.mismatch,
    finding: 'The pill does not match the bottle',
    findingDetail: 'The imprint on the pill belongs to a different medicine.',
    medicine: 'Acetaminophen · 500 mg',
    rows: [
      RecognitionRow('Bottle', 'Acetaminophen · 500 mg'),
      RecognitionRow('Imprint', 'I-2 · does not match bottle',
          detail: 'Orange · round'),
      RecognitionRow('Pill', 'Does not match bottle'),
    ],
    facts: _facts,
    sideEffects: _sideEffects,
  );

  static const ScanResult unconfirmedResult = ScanResult(
    verdict: ScanVerdict.unconfirmed,
    finding: 'Could not confirm the pill',
    findingDetail: 'The imprint photo was not clear enough to read.',
    medicine: 'Acetaminophen · 500 mg',
    rows: [
      RecognitionRow('Bottle', 'Acetaminophen · 500 mg'),
      RecognitionRow('Imprint', 'Not readable', detail: 'Blurry photo'),
      RecognitionRow('Pill', 'Not confirmed'),
    ],
    facts: _facts,
    sideEffects: _sideEffects,
  );

  static const ScanResult degradationResult = ScanResult(
    verdict: ScanVerdict.degradation,
    finding: 'The pill looks degraded',
    findingDetail: 'The device readings are outside the expected range.',
    medicine: 'Acetaminophen · 500 mg',
    rows: [
      RecognitionRow('Bottle', 'Acetaminophen · 500 mg'),
      RecognitionRow('Imprint', 'L484 · matches bottle', detail: 'White · oval'),
      RecognitionRow('Pill', 'Colour and surface changed'),
    ],
    facts: _facts,
    sideEffects: _sideEffects,
  );

  static const List<ScanResult> all = [
    matchResult,
    mismatchResult,
    unconfirmedResult,
    degradationResult,
  ];

  /// Mocked recognition: the demo always lands on the mismatch story so the
  /// report flow is reachable. Tap the finding card to cycle the other states.
  static ScanResult evaluate() => mismatchResult;

  static ScanResult next(ScanResult current) {
    final index = all.indexOf(current);
    return all[(index + 1) % all.length];
  }

  static const String chatPrompt =
      'All three checks match. What would you like to ask?';

  static const String chatSuggestion = 'I have a question about this pill.';

  static String reply(String question) =>
      'The imprint on your pill reads I-2, which belongs to ibuprofen 200 mg, '
      'not the acetaminophen on the bottle. Do not take it, and report the '
      'bottle so someone can check it.';
}
