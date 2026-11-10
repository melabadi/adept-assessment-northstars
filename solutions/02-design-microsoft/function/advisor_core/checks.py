"""Deterministic checks for the architecture advisor's answers (Design phase, Microsoft track).

One module, two places it runs, the same rules in both:
  - The Azure Function's gate (function_app.py, route advisor/check) checks every answer before anything reaches
    GitHub. A failed check stops the ADR draft.
  - The Foundry evaluation embeds this file's source in its code-based evaluators (evaluation.py), so the labelled
    cases are scored with exactly the gate's rules, plus the cases' labels.

The checks never trust the model: the search index decides whether a cited standard exists, which version it has,
and what its text says, and the profile's scope filter decides what the profile may see. The file uses the Python
standard library only, because Foundry runs code-based evaluators in a sandbox without network or extra packages.
"""
import json
import re

# Plain pattern strings: Foundry runs this file as a Python grader, which refuses any call named compile().
STANDARD_ID = r"STD-[A-Z]+-\d{3}"
SEARCH_MARKER = r"\s*【[^】]*】"
CHECK_KINDS = ("citations", "access", "grounding", "abstention", "conflicts")
MIN_EXCERPT_WORDS = 6
# Words that turn a requirement around. A quote may shorten a standard, but no gap it skips may hold one of these.
NEGATIONS = {"not", "no", "never", "nor", "neither", "none", "without", "unless", "except", "cannot", "avoid"}
SENTENCE_BREAK = r"(?<=[.!?])\s+|\n+"
CLAUSE_BREAK = r"(?<=[.!?;])\s+|\n+"
# The stated conclusion (case_misses). A labelled case lists claims a right answer asserts ("states") and claims it never
# asserts ("rejects"), read in the summary and the recommendation only: the options name the wrong choice too. A claim is
# a few words in order, each at most CLAIM_GAP words after the one before; a trailing * matches any ending
# ("approv* automat*" matches "approve low-risk requests automatically"). Text is cut into clauses at punctuation and
# before the words in CLAIM_BREAK. A clause that starts with a word in UNASSERTED asserts nothing: a condition ("if you
# want auto-approval") or the losing side of a comparison ("better than a direct call"). A clause with an odd number of
# NEGATION_CUES denies what it says: "There is no automatic approval" denies the claim, "Nothing prevents automatic
# approval" asserts it.
CLAIM_GAP = 3
CLAIM_BREAK = (r"[.!?]+(?=\s|$)|[;:,()\n–—]+|\s-+\s|\s+(?=(?:but|however|unless|except|while|whereas|although|though|"
               r"because|since|so|if|otherwise|until|before|than|which|without|rather|instead|over|against)\b)")
UNASSERTED = ("if", "unless", "whether", "until", "before", "than")
# A sentence that compares numbered options ("Compared options: (1) send attachments, or (2) send only the fields")
# names the wrong choice too, like the options themselves, so it asserts none of them.
ALTERNATIVES = r"\b(?:options?|alternatives?|compared)\b[^.!?]*?\(?\b1\)"
NEGATION_CUES = ("not", "no", "never", "nor", "neither", "none", "nothing", "without", "cannot", "rather", "instead",
                 "over", "against", "avoid*", "forbid*", "prohibit*", "disallow*", "exclud*", "violat*", "prevent*",
                 "break*")


def words(text: str) -> list:
    """Lowercase words only, so an excerpt matches the standard regardless of punctuation, quotes, or line breaks.
    A contraction reads as its negation ("don't" is "do not"), so the negation check sees it."""
    return re.findall(r"[a-z0-9%]+", re.sub(r"n['’]t\b", " not", str(text).lower()))


def bare_version(text: str) -> str:
    """Versions compare without a leading v, so v2.0 and 2.0 are the same."""
    return str(text).strip().lstrip("vV")


def _position(haystack: list, needle: list, start: int) -> int:
    """Index of the first run of whole words equal to needle at or after start, or -1."""
    for index in range(start, len(haystack) - len(needle) + 1):
        if haystack[index:index + len(needle)] == needle:
            return index
    return -1


def _starts(source: str, pattern: str) -> list:
    """The word index at which each piece of the source starts, when the source is split with pattern."""
    starts, offset = [], 0
    for piece in re.split(pattern, str(source)):
        starts.append(offset)
        offset += len(words(piece))
    return starts


def excerpt_found(excerpt: str, source: str, check_negations: bool = True) -> bool:
    """True when the excerpt is the standard's own words and keeps the standard's meaning:
      - split on an ellipsis, every part appears in the source as whole words, in the source's order;
      - every part is at least MIN_EXCERPT_WORDS words long or a whole sentence of the standard, so a stray word or a
        stitched fragment ("personal data ... be sent") never passes;
      - no gap the quote skips holds a negation (NEGATIONS): neither between two parts, nor between the start of the
        first part's clause and that part. "API keys ... be stored in configuration" skips "must not", and "persist
        raw prompts" leaves out the "Do not" in front of it: both fail. A clause after a semicolon starts afresh.
    check_negations=False skips the last rule, only to explain a rejection."""
    text = words(source)
    sentences = [words(s) for s in re.split(SENTENCE_BREAK, str(source))]
    parts = [part for part in (words(p) for p in re.split(r"\.\.\.|…", str(excerpt))) if part]
    if not parts or any(len(part) < MIN_EXCERPT_WORDS and part not in sentences for part in parts):
        return False
    clauses = _starts(source, CLAUSE_BREAK)

    def place(index: int, start: int) -> bool:
        """Whether parts[index:] fit at or after word `start`. Every occurrence is tried, so a phrase the standard
        repeats can't hide a placement that skips no negation."""
        if index == len(parts):
            return True
        found = _position(text, parts[index], start)
        while found >= 0:
            gap = text[(start if index else max(s for s in clauses if s <= found)):found]
            if not (check_negations and NEGATIONS.intersection(gap)) and place(index + 1, found + len(parts[index])):
                return True
            found = _position(text, parts[index], found + 1)
        return False

    return place(0, 0)


def _word_matches(word: str, pattern: str) -> bool:
    """A claim's or a cue's word: exact, or any ending when it ends with *."""
    return word.startswith(pattern[:-1]) if pattern.endswith("*") else word == pattern


def _claim_in(found: list, claim: list) -> bool:
    """Whether the claim's words appear in found in order, each at most CLAIM_GAP words after the one before."""
    def place(index: int, start: int) -> bool:
        if index == len(claim):
            return True
        end = len(found) if index == 0 else min(len(found), start + CLAIM_GAP + 1)
        return any(_word_matches(found[at], claim[index]) and place(index + 1, at + 1) for at in range(start, end))

    return bool(claim) and place(0, 0)


def asserts(text: str, claim: str) -> bool:
    """Whether the text asserts the claim: a clause holds the claim's words, isn't UNASSERTED, and doesn't deny them
    (an odd number of NEGATION_CUES). Sentences that compare numbered ALTERNATIVES assert nothing. Claims are written as
    positive statements; a test keeps cues out of the labels."""
    pattern = str(claim).lower().split()
    for sentence in re.split(SENTENCE_BREAK, str(text).lower()):
        if re.search(ALTERNATIVES, sentence):
            continue
        for clause in re.split(CLAIM_BREAK, sentence):
            found = words(clause)
            if not found or found[0] in UNASSERTED or not _claim_in(found, pattern):
                continue
            if sum(1 for w in found if any(_word_matches(w, c) for c in NEGATION_CUES)) % 2 == 0:
                return True
    return False


def conclusion_misses(expected: dict, answer: dict) -> list[str]:
    """What the answer's stated conclusion and its evidence got wrong against a labelled case's expectConclusion:
      states    the claims the summary or the recommendation must assert: each entry is a claim, or a list of
                alternative claims of which one is enough, and every entry must be asserted;
      rejects   claims neither may assert: the opposite conclusion, even when the answer's quotes are right;
      evidence  {standard id: words, or a list of alternatives}: one of the answer's excerpts of that standard must
                contain them, so the answer quotes a sentence that supports its conclusion.
    A correct quote alone passes the citations check; it earns nothing here."""
    misses = []
    stated = "\n".join(str(answer.get(key) or "") for key in ("summary", "recommendation"))
    for entry in expected.get("states") or []:
        claims = [entry] if isinstance(entry, str) else list(entry)
        if not any(asserts(stated, claim) for claim in claims):
            misses.append(f"conclusion: states none of {', '.join(repr(c) for c in claims)}")
    misses += [f"conclusion: asserts {claim!r}, which the case rules out"
               for claim in expected.get("rejects") or [] if asserts(stated, claim)]
    for standard, phrases in (expected.get("evidence") or {}).items():
        phrases = [phrases] if isinstance(phrases, str) else list(phrases)
        quoted = [words(c.get("excerpt", "")) for c in answer.get("constraints", [])
                  if re.findall(STANDARD_ID, str(c.get("standardId", ""))) == [standard]]
        if not any(_position(excerpt, words(phrase), 0) >= 0 for excerpt in quoted for phrase in phrases):
            misses.append(f"evidence: no excerpt of {standard} quotes {' or '.join(repr(p) for p in phrases)}")
    return misses


def strip_markers(node):
    """Remove inline citation markers, such as 【5:0†source】, from every text in the answer.
    The structured fields already carry the citations."""
    if isinstance(node, str):
        return re.sub(SEARCH_MARKER, "", node)
    if isinstance(node, list):
        return [strip_markers(value) for value in node]
    if isinstance(node, dict):
        return {key: strip_markers(value) for key, value in node.items()}
    return node


def answer_text(response: dict) -> str:
    """The agent's final text in a Responses API response, as the REST API returns it (the SDK's output_text)."""
    if isinstance(response.get("output_text"), str):
        return response["output_text"]
    parts = []
    for item in response.get("output") or []:
        if isinstance(item, dict) and item.get("type") == "message":
            parts += [c.get("text") or "" for c in item.get("content") or [] if isinstance(c, dict) and c.get("type") == "output_text"]
    return "".join(parts)


def parse_answer(text: str) -> dict:
    """The answer the agent returned in its strict JSON schema, without citation markers. Raises ValueError otherwise."""
    data = json.loads(text)
    if not isinstance(data, dict) or "answerable" not in data:
        raise ValueError("the agent's answer is not the architecture_recommendation JSON object")
    for key in ("options", "constraints", "conflicts", "unknowns"):
        data.setdefault(key, [])
    return strip_markers(data)


def retrieved_ids(node) -> list[str]:
    """Standard ids of the documents the knowledge tool returned to the agent.

    Works on every shape Azure reports them in: a Responses API response (mcp_call items from a Foundry IQ knowledge
    base, azure_ai_search_call_output items from the Azure AI Search tool) and a Foundry evaluation's output_items
    (tool_result entries). Tool outputs nest JSON inside JSON strings, so strings that look like JSON are parsed and
    walked too. Only documents count: a dict whose "id" is a standard id. The answer itself uses "standardId", so a
    citation is never mistaken for a retrieval."""
    found: set[str] = set()

    def walk(value, depth: int) -> None:
        if depth > 16:
            return
        if isinstance(value, str):
            text = value.strip()
            if text[:1] in "{[" and "STD-" in text:
                try:
                    walk(json.loads(text), depth + 1)
                except ValueError:
                    pass
            return
        if isinstance(value, dict):
            ident = value.get("id")
            if isinstance(ident, str) and re.fullmatch(STANDARD_ID, ident):
                found.add(ident)
            for child in value.values():
                walk(child, depth + 1)
        elif isinstance(value, list):
            for child in value:
                walk(child, depth + 1)

    walk(node, 0)
    return sorted(found)


def cited(answer: dict) -> set[str]:
    """Standard ids the answer relies on: constraints, options, and conflicts."""
    return set(re.findall(STANDARD_ID, json.dumps({k: answer.get(k, []) for k in ("constraints", "options", "conflicts")})))


def check(answer: dict, question: str, retrieved: list[str], standards: dict, permitted: list[str], profile: str) -> list[str]:
    """The gate. Returns the problems found; an empty list means the answer may be published.

    standards: id -> {"version": ..., "text": ...} for every standard in the index (what exists).
    permitted: ids the profile's scope filter returns from the index (what this profile may see).
    retrieved: ids the knowledge tool returned to the agent for this answer."""
    allowed = set(permitted)
    problems: list[str] = []
    flagged: set[str] = set()

    # Negative access test on every call: the knowledge base must never return a standard outside the profile.
    for standard in retrieved:
        if standard not in allowed:
            problems.append(f"access: the knowledge base returned {standard}, which is outside the '{profile}' scope")

    def verify(standard: str, where: str) -> bool:
        if standard not in standards:
            problems.append(f"citation: {standard} in {where} does not exist in the standards index (invented)")
        elif standard not in allowed:
            problems.append(f"access: {standard} in {where} is outside the '{profile}' scope and must not be used")
        else:
            return True
        flagged.add(standard)
        return False

    for constraint in answer.get("constraints", []):
        ids = re.findall(STANDARD_ID, str(constraint.get("standardId", "")))
        if len(ids) != 1:
            problems.append(f"citation: '{constraint.get('standardId', '')}' is not exactly one standard id")
            continue
        standard = ids[0]
        if not verify(standard, "constraints"):
            continue
        cited_version, indexed = bare_version(constraint.get("version", "")), standards[standard]["version"]
        if cited_version != bare_version(indexed):
            problems.append(f"version: {standard} cited as v{cited_version}, the index has v{indexed}")
        excerpt, source = constraint.get("excerpt", ""), standards[standard]["text"]
        if not excerpt_found(excerpt, source):
            why = ("leaves out a negation the standard has" if excerpt_found(excerpt, source, check_negations=False)
                   else "is not in the standard")
            problems.append(f"excerpt: the quote attributed to {standard} {why}: \"{str(excerpt)[:80]}\"")
    for option in answer.get("options", []):
        for standard in sorted(set(re.findall(STANDARD_ID, " ".join(option.get("standards", []))))):
            verify(standard, f"option '{str(option.get('name', ''))[:40]}'")
    for conflict in answer.get("conflicts", []):
        for standard in sorted(set(re.findall(STANDARD_ID, " ".join(conflict.get("standards", []))))):
            verify(standard, "conflicts")
    # Anywhere else in the answer, an id is only allowed if it is real and in scope (or the question named it).
    for standard in sorted(set(re.findall(STANDARD_ID, json.dumps(answer))) - flagged - set(re.findall(STANDARD_ID, question))):
        verify(standard, "the answer text")

    if not answer.get("answerable") and answer.get("recommendation"):
        problems.append("abstention: answerable is false but a recommendation was given")
    if not answer.get("answerable") and not answer.get("unknowns"):
        problems.append("abstention: answerable is false but unknowns is empty")
    if answer.get("answerable") and not answer.get("constraints"):
        problems.append("grounding: an answer must cite at least one standard")
    return problems


def case_misses(case: dict, answer: dict) -> list[str]:
    """What an answer got wrong compared with a labelled evaluation case (eval_cases.jsonl)."""
    misses = []
    used = cited(answer)
    if bool(answer.get("answerable")) != bool(case["expectAnswerable"]):
        misses.append(f"expected answerable={case['expectAnswerable']}, got {answer.get('answerable')}")
    misses += [f"did not cite {s}" for s in case.get("expectStandards", []) if s not in used]
    misses += [f"cited out-of-scope {s}" for s in case.get("forbidStandards", []) if s in used]
    expected = set(case.get("expectConflict") or [])
    if expected and not any(expected <= set(re.findall(STANDARD_ID, " ".join(c.get("standards", [])))) for c in answer.get("conflicts", [])):
        misses.append(f"did not flag the conflict {' vs '.join(case['expectConflict'])}")
    if case.get("expectConclusion"):
        misses += conclusion_misses(case["expectConclusion"], answer)
    return misses


def _field(item: dict, name: str):
    """Evaluation items keep nested data as JSON strings (the dataset schema stays flat); accept both forms."""
    value = item.get(name)
    return json.loads(value) if isinstance(value, str) and value[:1] in "{[" else value


def evaluate_item(item: dict) -> dict:
    """Score one Foundry evaluation item. The item holds the case (question, profile, labels), the index snapshot
    (standards, permitted), and item["sample"] with the agent's output_text and output_items."""
    sample = item.get("sample") or {}
    answer = parse_answer(sample.get("output_text") or "")
    retrieved = retrieved_ids(sample.get("output_items"))
    problems = check(answer, item.get("question", ""), retrieved, _field(item, "standards"), _field(item, "permitted"),
                     item.get("profile", ""))
    case = {key: _field(item, key) for key in ("expectAnswerable", "expectStandards", "forbidStandards", "expectConflict",
                                               "expectConclusion")}
    return {"problems": problems, "misses": case_misses(case, answer), "retrieved": retrieved}


def verdict(result: dict, kind: str) -> bool:
    """One evaluator's pass or fail. Each kind is a column in the Foundry evaluation report."""
    problems, misses = result["problems"], result["misses"]

    def has(items, *prefixes):
        return any(entry.startswith(prefixes) for entry in items)

    if kind == "citations":
        return not has(problems, "citation:", "version:", "excerpt:")
    if kind == "access":
        return not has(problems, "access:") and not has(misses, "cited out-of-scope")
    if kind == "grounding":
        return not has(problems, "grounding:") and not has(misses, "did not cite", "conclusion:", "evidence:")
    if kind == "abstention":
        return not has(problems, "abstention:") and not has(misses, "expected answerable=")
    if kind == "conflicts":
        return not has(misses, "did not flag the conflict")
    raise ValueError(f"unknown check kind {kind}")
