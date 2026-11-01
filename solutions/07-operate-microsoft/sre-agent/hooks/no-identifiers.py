#!/usr/bin/env python3
"""Azure SRE Agent PreToolUse hook: no GitHub Issue call goes out without a person, or with an identifier in it.

The agent runs this script before every tool call whose name matches the hook's matcher (the GitHub Issue tools, see
sre-agent/agent.yaml). In this solution it is a backstop: the tool policy denies every GitHub write tool, and the
agent drafts the incident record for a person to file. The script blocks those write tools too. For any other Issue
tool, it reads the call as JSON on stdin and scans every key and string in `tool_input` (title, body, labels,
comments), as written and normalized, and blocks the call when it finds a GUID or a 32-character hex id, an Azure host
name or resource id, an e-mail address, or a resource name with a random suffix. Otherwise it asks for a person's
approval, whatever the tool policy and run mode say. It never allows a call by itself, and it fails closed: unreadable
or oversized input is blocked, and an error exits with code 2, which always blocks.

It is deterministic (regular expressions, no model), takes time linear in the size of the input, and uses only the
Python standard library. configure_sre_agent.py fills in SUFFIXES and DENIED_TOOLS at the end of this file, from this
deployment and from sre-agent/agent.yaml, when it applies the hook, and tests the script against good, bad, hidden,
and malformed input in `python configure_sre_agent.py --check`.
"""
import html
import json
import re
import sys
import unicodedata
from urllib.parse import unquote

GUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
# The same ids without hyphens, as Application Insights writes operation and trace ids. Longer hex runs (commit SHAs)
# don't match.
HEX_ID = re.compile(r"(?<![0-9A-Za-z])[0-9a-fA-F]{32}(?![0-9A-Za-z])")
RESOURCE_ID = re.compile(r"/subscriptions/|/resourcegroups/[^/\s]{1,90}/providers/", re.IGNORECASE)
# Host names, e-mail addresses, and resource names are checked word by word, which keeps the scan linear.
WORD = re.compile(r"[A-Za-z0-9._%+@-]+")
AZURE_DOMAINS = ("azurecontainerapps.io", "azurecr.io", "azuresre.ai", "azure.com", "azure.net", "windows.net",
                 "azurewebsites.net", "azure-api.net", "azurefd.net", "azureedge.net", "cloudapp.net", "onmicrosoft.com")
# Public, tenant-independent host names that may appear in an Issue.
PUBLIC_HOSTS = {"portal.azure.com", "sre.azure.com", "management.azure.com", "learn.microsoft.com"}
EMAIL_DOMAIN = re.compile(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
HTML_TAG = re.compile(r"</?[A-Za-z][^<>]{0,200}>")
MARKDOWN = re.compile(r"[*`~_\\]")
MAX_INPUT = 65_536  # characters of tool input; GitHub's own limit for an Issue body

# The decisions this hook returns. "ask" makes the platform hold the call for a person's Allow once.
ASK = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                              "permissionDecisionReason": "A person reads every GitHub Issue before it is posted."}}


def block(reason: str) -> dict:
    return {"decision": "block", "reason": reason}


def without_comments(text: str) -> str:
    parts, start = [], 0
    while (opening := text.find("<!--", start)) >= 0:
        parts.append(text[start:opening])
        closing = text.find("-->", opening + 4)
        if closing < 0:
            return "".join(parts)
        start = closing + 3
    return "".join(parts) + text[start:]


def normalized(text: str) -> str:
    """The text as a reader sees it: compatibility forms folded (fullwidth digits); invisible format characters (zero-
    width spaces, soft hyphens), HTML comments and tags, and Markdown markers removed; entities and URL escapes decoded."""
    for _ in range(3):
        before = text
        text = unicodedata.normalize("NFKC", text)
        text = "".join(ch for ch in text if unicodedata.category(ch) != "Cf")
        text = unquote(html.unescape(HTML_TAG.sub("", without_comments(text))))
        text = MARKDOWN.sub("", text)
        if text == before:
            break
    return text


def suffixed(word: str) -> bool:
    """A hyphenated name with a 13-character part of lowercase letters and digits, the shape of Azure's uniqueString()
    suffix: ca-worker-<suffix>, appi-<suffix>, id-sre-<suffix>."""
    return "-" in word and any(len(part) == 13 and part.isascii() and part.isalnum() and not part.isalpha()
                               and not part.isdigit() for part in re.split(r"[-.]+", word))


def findings(text: str) -> set[str]:
    found = set()
    for variant in {text, normalized(text)}:
        if GUID.search(variant) or HEX_ID.search(variant):
            found.add("a GUID or trace id")
        if RESOURCE_ID.search(variant):
            found.add("an Azure resource id")
        lowered = variant.lower()
        if any(suffix in lowered for suffix in SUFFIXES):
            found.add("a resource name with its random suffix")
        for word in WORD.findall(lowered):
            word = word.strip(".-")
            local, at, domain = word.rpartition("@")
            if at and local and EMAIL_DOMAIN.fullmatch(domain):
                found.add("an e-mail address")
            host = domain if at else word
            if host not in PUBLIC_HOSTS and any(host.endswith("." + d) for d in AZURE_DOMAINS):
                found.add("an Azure host name")
            if suffixed(word):
                found.add("a resource name with its random suffix")
    return found


def strings(value: object, path: str = ""):
    """Every key and string in the tool input, with where it was found."""
    if isinstance(value, str):
        yield path or "input", value
    elif isinstance(value, dict):
        for key, item in value.items():
            where = f"{path}.{key}" if path else str(key)
            yield f"{where} (key)", str(key)
            yield from strings(item, where)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from strings(item, f"{path}[{index}]")


def decide(event: object) -> dict:
    if not isinstance(event, dict) or "tool_input" not in event:
        return block("The guard could not find the tool call's arguments (tool_input), so nothing was sent.")
    tool_name = str(event.get("tool_name") or "")
    if DENIED_TOOLS.fullmatch(tool_name):
        return block(f"{tool_name} is not allowed: this agent never writes to GitHub. It drafts the incident record in "
                     "its reply, and a person files it.")
    tool_input = event["tool_input"]
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except ValueError:
            pass
    if not isinstance(tool_input, (dict, list, str)):
        return block("The guard could not read the tool call's arguments, so nothing was sent.")
    if len(json.dumps(tool_input)) > MAX_INPUT:
        return block(f"The text is longer than {MAX_INPUT} characters, too long to check, so nothing was sent.")
    problems: dict[str, set[str]] = {}
    for field, text in strings(tool_input):
        for finding in findings(text):
            problems.setdefault(finding, set()).add(field)
    if problems:
        details = "; ".join(f"{kind} in {', '.join(sorted(fields))}" for kind, fields in sorted(problems.items()))
        return block(f"Blocked before anything reached GitHub: the text contains {details}. Rewrite it with "
                     "placeholders: 'the worker', 'the API', 'the database', 'the alert', 'the resource group', 'the "
                     "previous worker revision'. Leave out ids, host names, resource ids, subscription details, and "
                     "e-mail addresses, then submit it again.")
    return ASK


def main() -> int:
    try:
        print(json.dumps(decide(json.loads(sys.stdin.read()))))
        return 0
    except Exception as error:  # fail closed: exit code 2 always blocks, and stderr becomes the reason
        print(f"The identifier guard failed ({type(error).__name__}), so nothing was sent to GitHub.", file=sys.stderr)
        return 2


# Filled in when the hook is applied: the random suffixes in this deployment's resource names (comma-separated), and
# the GitHub tools the agent never uses (the github.deny patterns in sre-agent/agent.yaml, as a regular expression).
SUFFIXES = [s for s in "{{RESOURCE_SUFFIXES}}".split(",") if re.fullmatch(r"[a-z0-9]{6,}", s)]
DENIED_TOOLS = re.compile(r"{{GITHUB_DENIED_TOOLS}}")

if __name__ == "__main__":
    sys.exit(main())
