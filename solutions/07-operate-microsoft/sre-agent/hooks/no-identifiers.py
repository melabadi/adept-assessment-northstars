#!/usr/bin/env python3
"""Azure SRE Agent PreToolUse hook: block a GitHub tool call whose arguments contain an identifier of this deployment.

The agent runs this script before every tool call whose name matches the hook's matcher (GitHub tools, see
sre-agent/agent.yaml). It reads the call as JSON on stdin and scans every string in `tool_input`: Issue title, body,
labels, comments. It blocks the call when it finds a GUID or a 32-character hex id (subscription, tenant, alert,
thread, operation, or trace ids), an Azure host name, an Azure resource id, an e-mail address, or a resource name with
a random suffix. Otherwise it prints nothing, so the agent's tool policy decides: GitHub writes then wait for a person
to select Allow once.

It is deterministic (regular expressions, no model) and uses only the Python standard library. configure_sre_agent.py
fills in SUFFIXES below with the random suffixes of this deployment's resource names when it applies the hook, and runs
the script against good and bad samples in `python configure_sre_agent.py --check`.
"""
import json
import re
import sys

# The random suffixes in this deployment's resource names (comma-separated), filled in when the hook is applied.
SUFFIXES = [s for s in "{{RESOURCE_SUFFIXES}}".split(",") if re.fullmatch(r"[a-z0-9]{6,}", s)]
# Public, tenant-independent host names that may appear in an Issue.
PUBLIC_HOSTS = {"portal.azure.com", "sre.azure.com", "management.azure.com", "learn.microsoft.com"}

GUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
# The same ids without hyphens, as Application Insights writes operation and trace ids. Longer hex runs (commit SHAs)
# don't match.
HEX_ID = re.compile(r"(?<![0-9A-Za-z])[0-9a-fA-F]{32}(?![0-9A-Za-z])")
HOST = re.compile(r"(?:[A-Za-z0-9-]+\.)+(?:azurecontainerapps\.io|azurecr\.io|azuresre\.ai|azure\.com|azure\.net|"
                  r"windows\.net|azurewebsites\.net|azure-api\.net|azurefd\.net|azureedge\.net|cloudapp\.net|"
                  r"onmicrosoft\.com)\b", re.IGNORECASE)
RESOURCE_ID = re.compile(r"/subscriptions/|/resourcegroups/[^/\s]+/providers/", re.IGNORECASE)
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
# A hyphenated name with a 13-character segment of lowercase letters and digits, the shape of Azure's uniqueString()
# suffix: ca-worker-<suffix>, appi-<suffix>, id-sre-<suffix>.
HYPHENATED = re.compile(r"[a-z0-9]+(?:-+[a-z0-9]+)+")


def suffixed(word: str) -> bool:
    return any(len(part) == 13 and re.search(r"[0-9]", part) and re.search(r"[a-z]", part)
               for part in re.split(r"-+", word))


def findings(text: str) -> set[str]:
    found = set()
    if GUID.search(text) or HEX_ID.search(text):
        found.add("a GUID or trace id")
    if any(match.group(0).lower() not in PUBLIC_HOSTS for match in HOST.finditer(text)):
        found.add("an Azure host name")
    if RESOURCE_ID.search(text):
        found.add("an Azure resource id")
    if EMAIL.search(text):
        found.add("an e-mail address")
    lowered = text.lower()
    if any(s in lowered for s in SUFFIXES) or any(suffixed(m.group(0)) for m in HYPHENATED.finditer(lowered)):
        found.add("a resource name with its random suffix")
    return found


def strings(value: object, path: str = ""):
    if isinstance(value, str):
        yield path or "input", value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from strings(item, f"{path}.{key}" if path else str(key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from strings(item, f"{path}[{index}]")


def main() -> int:
    event = json.load(sys.stdin)
    tool_input = event.get("tool_input", {})
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except ValueError:
            pass
    problems: dict[str, set[str]] = {}
    for field, text in strings(tool_input):
        for finding in findings(text):
            problems.setdefault(finding, set()).add(field)
    if problems:
        details = "; ".join(f"{kind} in {', '.join(sorted(fields))}" for kind, fields in sorted(problems.items()))
        print(json.dumps({"decision": "block", "reason": (
            f"Blocked before anything reached GitHub: the text contains {details}. Rewrite it with placeholders: "
            "'the worker', 'the API', 'the database', 'the alert', 'the resource group', 'the previous worker revision'. "
            "Leave out ids, host names, resource ids, subscription details, and e-mail addresses, then submit it again.")}))
    # No output: no objection. The tool policy decides, and GitHub writes wait for a person's Allow once.
    return 0


if __name__ == "__main__":
    sys.exit(main())
