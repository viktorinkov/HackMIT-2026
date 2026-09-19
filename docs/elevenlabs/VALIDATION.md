# ElevenLabs setup validation — 2026-09-19

Configured and published through the ElevenLabs dashboard using the Chrome extension. Final model: GPT-4.1. Voice: Eric — Smooth, Trustworthy. Language: English.

These are observed text-preview checks, not automated regression tests or clinical validation. All scan measurements and imprint records supplied were synthetic. The nitroglycerin test additionally used real DailyMed label facts.

| Scenario | Observed result |
| --- | --- |
| Pending scan, initial configuration | Said the scan was pending and no bottle, imprint, or hardware results were available. |
| Suspected degradation without drug-specific facts, final configuration | Described possible degradation; explicitly said it lacked sourced information for the specific medication; declined to recommend extra tablets. |
| Reported degradation with sourced nitroglycerin label facts, final configuration | Explained possible loss of potency and reduced effectiveness; identified the result as simulated; did not invent a remaining-potency percentage or add unsupported degradation mechanisms. |
| Bottle says acetaminophen, imprint and hardware suggest ibuprofen, final configuration | Identified the conflict, preserved uncertainty, stated that mismatch alone does not prove counterfeiting, and suggested pharmacist verification. |
| Context changes between different synthetic scan IDs | Used the newly supplied medication rather than retaining the prior pill identity. |

The first model's answers were verbose and blurred general information with sourced medication-specific claims. The prompt was tightened and the model changed before the final checks above.

Still unverified: microphone input, synthesized speech/pronunciation, Flutter integration, actual backend reports, Elastic retrieval, hardware model validity, and full end-to-end latency. No live backend tool is connected. The prompt alone is not an authentication or clinical validation boundary.

The backend must supply sourced medication-specific degradation facts. If those facts are absent, the agent explains the limit rather than filling the gap from memory.
