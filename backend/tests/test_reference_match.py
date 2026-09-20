import pytest
from backend.reference_match import match_readings, reference_profiles
from backend.scans.normalizer import hardware_doc
from backend.pill import PillHardwareResult
from backend.deepgram.prompt import build_playground_prompt
from backend.deepgram.session import opening_messages_from_scan


def hardware(values):
    return {'model': 'peel-xiao', 'status': 'unknown', 'spectrum': values}


@pytest.mark.parametrize('name,curve', reference_profiles().items())
def test_classification_changes_with_readings_and_ignores_bottle_name(name, curve):
    h = hardware([v - .4 for v in curve])
    h['pill_type'] = 'unrelated label'
    result = match_readings(h)
    assert result['closest_match'] == name
    assert result['distance'] == 0
    assert result['status'] == 'matched'
    assert result['reference_source'] == 'synthetic'
    assert result['validated_identity'] is False


def test_no_forced_match_for_flat_short_or_corrupt_data():
    for values, status in [([0]*20, 'no_signal'), ([0,1], 'insufficient_data'),
                           ([float('nan')]*20, 'insufficient_data')]:
        assert match_readings(hardware(values))['status'] == status
    assert match_readings(hardware(list(range(20))))['status'] == 'outside_library'
    assert match_readings({'model':'mock-spectrometry','spectrum':list(range(20))})['status']=='no_data'


def test_switched_profiles_are_ambiguous():
    p = reference_profiles()
    mid = [(a+b)/2 for a,b in zip(p['Vitamin B12'],p['Caffeine'])]
    assert match_readings(hardware(mid))['status'] == 'ambiguous'


def test_real_readings_flow_to_saved_result_and_short_voice():
    values=reference_profiles()['Vitamin B12']
    raw=PillHardwareResult(status='unknown',spectrum=values,degraded=False,confidence=0)
    h=hardware_doc(raw,'peel-xiao')
    assert h['reference_match']['closest_match']=='Vitamin B12'
    assert h['status']=='unknown' and h['pill_type'] is None
    doc={'scan_id':'test','hardware':h}
    assert opening_messages_from_scan(doc)[2].startswith('Closest match: Vitamin B12.')
    prompt=build_playground_prompt(doc).prompt
    assert 'synthetic-optical-v1' in prompt
    assert '"absorbance_trace"' not in prompt
    assert '"sensor_readings"' not in prompt
