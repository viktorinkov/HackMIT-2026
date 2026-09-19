# Peel ElevenLabs integration

Agent: [Peel — Pill Check](https://elevenlabs.io/app/agents/agents/agent_5601m2xb8h0aem2b0ghn1gw7hdnd/agent)

Agent ID: `agent_5601m2xb8h0aem2b0ghn1gw7hdnd`

## Backend handoff

The agent takes one string dynamic variable: `scan_context`. Serialize your current scan report to JSON and provide it when the app starts a conversation. The field names below are a proposed handoff contract, not a backend implementation.

Keep the three sources distinct:

- `bottle`: observed label fields, including ingredient/name, strength, form, release type, expiration, and readability.
- `imprint`: observed characters plus researched candidates with source IDs. Vision guesses alone are not verified imprint lookups.
- `hardware`: measurement status, candidate identity, quality/degradation finding, evidence, and device/model limitations. Leave unsupported strength or potency null.
- `drug_facts`: medication-specific facts retrieved by your Elastic research pipeline. Each should include `medication_id`, `topic`, `text`, and `source_ids`. Degradation consequences need evidence for the relevant drug and formulation.
- `sources`: referenced source IDs, titles, URLs, label/version dates where available.
- `scan_id`, `revision`, `status`, and `demo`: identify the active report, order updates, distinguish pending/partial/complete/error, and flag synthetic results.

See [demo-contexts.json](demo-contexts.json) for deliberately synthetic fixtures. Their imprint markings are NOT real medication reference data. All fixtures have `demo: true`.

Dynamic variable values must be strings, numbers, or booleans. Send the entire JSON report as a string, not a nested object:

```json
{
  "dynamic_variables": {
    "scan_context": "{\"scan_id\":\"scan-123\",\"revision\":1,\"demo\":false,\"status\":\"pending\",\"bottle\":null,\"imprint\":null,\"hardware\":null,\"drug_facts\":[],\"sources\":[]}"
  }
}
```

This is the dynamic-variables portion of the conversation configuration; wrap it using the chosen ElevenLabs SDK. SDK option casing can differ.

For a WebSocket session, the initialization event is:

```json
{
  "type": "conversation_initiation_client_data",
  "dynamic_variables": {
    "scan_context": "{\"scan_id\":\"scan-123\",\"revision\":1,\"demo\":false,\"status\":\"pending\"}"
  }
}
```

For results arriving during the conversation, send a contextual update containing the full latest report:

```json
{
  "type": "contextual_update",
  "text": "Updated active Peel scan report: <serialized JSON report>"
}
```

A contextual update supplies background information; it does not itself guarantee an immediate spoken summary. When the user requests a summary, send their request as a user message, or let them ask by voice. Start a new conversation for a different physical pill where practical. Reject stale revisions in the app before sending updates.

Elastic stays in the backend: retrieve and assemble sourced facts there, then pass them with the scan. No backend URL or webhook tool has been invented or connected. Questions beyond the supplied facts require a later research tool or another app-provided context update.

The prompt expects evidence, not raw spectra. Device classification and degradation assessment belong to the hardware/backend model. A generic spectral similarity score does not quantify active ingredient concentration or prove degradation.

## Current configuration

- English; Eric — Smooth, Trustworthy voice.
- GPT-4.1 explanation model; default backup-model configuration retained.
- Clear AI disclosure in the first message.
- Short explanations of bottle/imprint/hardware agreement and disagreement.
- Explicit handling of missing results and unsupported degradation effects.
- No patient data or actual scan data was used during configuration.
- Public access is the platform's initial agent setting. Before a real deployment, decide on authentication and have the backend issue conversation access; do not put an ElevenLabs API key in the mobile app.
- The local [system-prompt.txt](system-prompt.txt) is the authored prompt backup.
- [demo-degradation-with-sources.json](demo-degradation-with-sources.json) combines a simulated nitroglycerin scan with sourced label facts to test a medication-specific explanation. The hardware result and imprint are synthetic; the label facts are real.

## References

- [ElevenLabs dynamic variables](https://elevenlabs.io/docs/eleven-agents/customization/personalization/dynamic-variables)
- [ElevenLabs client-to-server contextual updates](https://elevenlabs.io/docs/eleven-agents/customization/events/client-to-server-events)
- [ElevenLabs WebSocket API](https://elevenlabs.io/docs/eleven-agents/api-reference/eleven-agents/websocket)
- [FDA: expired medicines and changes in strength or composition](https://www.fda.gov/drugs/special-features/dont-be-tempted-use-expired-medicines)

The FDA source supports general caution; it is not a source for drug-specific degradation claims or validation of the Peel device.
