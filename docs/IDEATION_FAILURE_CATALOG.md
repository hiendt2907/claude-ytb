# Ideation failure catalog

The batch ideation engine records future validation and QA failures in
`assets/quality_reports/ideation_errors.jsonl`. Each event contains a stable
code, script name, attempt, validation message, and QA violations; full script
text and credentials are deliberately excluded.

| Code | Observed cause | Engine prevention / recovery |
| --- | --- | --- |
| `PROVIDER_STDIN_HANG` | `codex exec` inherited open stdin and waited for EOF. | Providers use `stdin=subprocess.DEVNULL`. |
| `IDEATION_TIMEOUT` | A long generation can exceed the legacy 900-second limit. | Per-script timeout defaults to 3600 seconds and emits a typed failure. |
| `RESUME_BATCH_SCOPE` | Local Codex resume ignored its batch key and regenerated completed work. | Resume counts only the requested batch key. |
| `VALIDATION_LONG_LENGTH` | A 8–11 minute Long was rejected by the current Long standard. | The shared `CONTENT_CONTRACT` uses a 12–15 minute viewer-visible Long and renderer-aware audio bounds. |
| `QA_HOOK_WEAK` | The first spoken beat did not carry a concrete tension/question. | Generation and repair require a hook marker/question in the first 28 spoken words after a Long greeting. |
| `QA_CENTRAL_MECHANISM` | Generic CTA wording such as “các cơ chế khiến…” was parsed as a second mechanism. | Mechanism gate ignores generic effect phrases and repair keeps one named mechanism. |
| `QA_SERIES_SEMANTIC_DEDUP` | A proposed episode was too close in meaning to an accepted episode. | Repair replaces its title, topic, and narration with a distinct named mechanism while preserving the funnel contract. |

New failure categories must be added to `ideation_error_engine.py`, given a
regression test, and documented in this table before a batch is resumed.
