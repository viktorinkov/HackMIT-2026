"""TruePill: the spectral classification layer for the Peel bench rig.

Self-contained and relocatable. Every import inside this package is relative,
so the directory works wherever it is dropped - at the repository root
(`import truepill`), inside another package (`from backend.truepill import
...`), or under a different name - without touching sys.path and without its
generically named modules (models, noise, library, server) colliding with
anyone else's. tests/test_relocatable.py proves it on every run.

It needs numpy and scipy (requirements.txt). Nothing in the repository imports
it yet, so adding it changes no existing behaviour.

The short way in, from 17_stream lines to the backend's hardware result:

    from truepill import classify_capture, load_library, to_pill_hardware_result

    library = load_library()                      # the rig's measured references
    result = classify_capture(blank_lines, sample_lines, library, expected_drug="advil")
    payload = to_pill_hardware_result(result)     # PillHardwareResult(**payload)

Only the names below are the public surface; the pipeline modules (kinetics,
dissolution, verdict, server) import lazily from their own files so that
`import truepill` stays cheap and does not pull in FastAPI.
"""

from .backend_bridge import to_pill_hardware_analysis, to_pill_hardware_result
from .classification import (
    DEFAULT_CONFIG,
    ClassificationResult,
    ClassifierConfig,
    LibraryEntry,
    SpectralMatch,
    classify,
    compute_absorbance,
    cosine_similarity,
    match_spectrum,
)
from .hardware import (
    PEEL_BENCH_RIG,
    RigProfile,
    average_sweeps,
    classify_capture,
    load_library,
    parse_stream_line,
    sweep_vector,
)
from .noise import NoiseParams

__all__ = [
    "DEFAULT_CONFIG",
    "PEEL_BENCH_RIG",
    "ClassificationResult",
    "ClassifierConfig",
    "LibraryEntry",
    "NoiseParams",
    "RigProfile",
    "SpectralMatch",
    "average_sweeps",
    "classify",
    "classify_capture",
    "compute_absorbance",
    "cosine_similarity",
    "load_library",
    "match_spectrum",
    "parse_stream_line",
    "sweep_vector",
    "to_pill_hardware_analysis",
    "to_pill_hardware_result",
]
