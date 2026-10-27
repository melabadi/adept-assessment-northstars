First decide whether the response below presents incident investigation findings, proposes a mitigation, or claims
that an incident recovered. If it does none of these (a greeting, a clarifying question, a progress update, a report
of a missing prerequisite), return {"ok": true} immediately.

$ARGUMENTS

For an investigation, check that the response states:
- the UTC window and the affected resources;
- evidence with UTC timestamps, or the evidence that is missing;
- confirmed facts separately from hypotheses, with a confidence;
- the next validation step.

If it proposes a mitigation, also check that it names the exact target and command, explains how to roll it back,
and says the change waits for approval. If it claims recovery, check that it cites evidence from after the change.

Return {"ok": true} when everything applicable is present. Otherwise return
{"ok": false, "reason": "<the specific missing item>"}.
