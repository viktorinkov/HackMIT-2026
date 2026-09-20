# Mock hardware analysis

The phone-attached hardware runs a spectrometry model (also deployable on Runpod) that compares the pill’s actual contents to a known pill type. We do not have that device or model in this hackathon environment, so this backend path **mocks those model results**.

Photo identification (imprint, shape, color, bottle label) is a separate step. This mock stands in for the hardware verdict only.

## What the real model does

1. Capture a spectrum from the physical pill.
2. Match that spectrum to a known pill type.
3. Decide whether the contents look real, substandard, fake, or unknown.

## What the mock should return

The important field for the rest of the pipeline (judge / Deepgram agent / case table) is the contents status:

| Status | Meaning |
| --- | --- |
| `real` | Spectrum matches a known, expected pill type. |
| `substandard` | Spectrum resembles that type but looks degraded or off-spec. |
| `fake` | Spectrum does not match the claimed/known type. |
| `unknown` | Not enough signal to classify. |

Supporting fields:

| Field | Meaning |
| --- | --- |
| `spectrum` | Mock spectrometry reading (wavelength/intensity samples or a compact signature). |
| `pill_type` | The pill type the spectrum matched, if any. |
| `degraded` | Whether the contents look degraded versus a fresh reference for that type. |
| `confidence` | How sure the mock/model is about the status. |

The mock should be deterministic enough to drive the README case table (Real / Substandard / Fake / Unknown) without calling the real hardware model.
