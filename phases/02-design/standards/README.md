# Approved architecture standards (synthetic)

Each file is one standard with a stable ID and version. `scope` controls who may retrieve it in the Microsoft track:
`all` applies everywhere, `small-team` and `enterprise` apply only to that operating profile.

Two deliberate traps for the demos:
- **Conflict:** STD-OBS-002 (log full prompts for 30 days) contradicts STD-SEC-002 (never persist raw prompts with user free text).
- **Gap:** no standard sets a monthly AI token budget. Advisors must say they do not know.
