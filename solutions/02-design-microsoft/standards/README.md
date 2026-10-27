# Approved architecture standards (synthetic)

Each file is one standard with a stable id (the file name) and a version. The front matter drives ingestion into Azure AI Search:

- `scope` decides who may retrieve it: `all` applies everywhere, `small-team` and `enterprise` only to that operating profile.
- `status` must be `approved`; anything else is left out of the index.
- `keywords` lists the words people use for the topic, so search finds the standard.

Two deliberate traps for the demo:

- **Conflict:** STD-OBS-002 (log full prompts and completions for 30 days) contradicts STD-SEC-002 (never persist raw prompts or completions that contain user free text).
- **Gap:** no standard sets a monthly AI token budget. The advisor must say it does not know.
