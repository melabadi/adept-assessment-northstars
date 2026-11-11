"""Check that the relative links in the repository's Markdown files point at something that exists.

Every tracked Markdown file is checked, except the mirrored copies in the root .github folder (their solution's copy is
checked instead). Each relative link or image is resolved the way GitHub resolves it when it shows the file:

  - a link inside the repository must name a file or folder that exists;
  - a #fragment on a Markdown file, or on the same file, must match one of its headings, using GitHub's anchor rules;
  - a link that climbs out of the repository must land on one of its pages on GitHub, such as ../../issues/new from
    the root README, which opens the repository's new-Issue page in any copy of the repository.

Links in code blocks and inline code are ignored, and so are absolute URLs (http, https, mailto).

Usage:
  python tools/check_links.py            # report broken links; exit 1 if there are any
  python tools/check_links.py --verbose  # also print how many links each file has
"""
from __future__ import annotations

import argparse
import posixpath
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import unquote

REPO = Path(__file__).resolve().parents[1]

# Where GitHub shows a file of the repository: relative links resolve from here.
WEB_ROOT = "/owner/repo/blob/branch"
REPO_PAGES = {"actions", "branches", "commit", "commits", "compare", "discussions", "issues", "labels", "milestones",
              "projects", "pull", "pulls", "releases", "security", "settings", "tags", "tree", "wiki"}

FENCE = re.compile(r"^(```|~~~)")
INLINE_CODE = re.compile(r"`[^`\n]*`")
LINK = re.compile(r"!?\[(?:[^\[\]]|\[[^\]]*\])*\]\(\s*(<[^>]+>|[^)\s]+)(?:\s+\"[^\"]*\")?\s*\)")
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")
HTML_ANCHOR = re.compile(r"<a\s+(?:name|id)=\"([^\"]+)\"", re.IGNORECASE)


def markdown_files() -> list[Path]:
    listed = subprocess.run(["git", "ls-files", "*.md"], cwd=REPO, capture_output=True, text=True, check=True).stdout
    return [REPO / name for name in listed.splitlines()
            if not name.startswith(".github/") or name == ".github/copilot-instructions.md"]


def prose_lines(text: str) -> list[str]:
    """The file's lines with fenced code blocks blanked out and inline code removed."""
    lines, fenced = [], False
    for line in text.splitlines():
        if FENCE.match(line.strip()):
            fenced = not fenced
            lines.append("")
            continue
        lines.append("" if fenced else INLINE_CODE.sub("", line))
    return lines


def slug(heading: str) -> str:
    """GitHub's anchor for a heading: plain text, lower case, punctuation dropped, spaces turned into hyphens."""
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", heading)  # links and images keep their text
    text = re.sub(r"<[^>]+>", "", text).replace("`", "").replace("*", "")
    text = text.strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def anchors(path: Path, cache: dict[Path, set[str]]) -> set[str]:
    if path not in cache:
        seen: Counter[str] = Counter()
        found: set[str] = set()
        for line in prose_lines(path.read_text(encoding="utf-8")):
            match = HEADING.match(line)
            if match:
                base = slug(match.group(1))
                found.add(base if seen[base] == 0 else f"{base}-{seen[base]}")
                seen[base] += 1
            found.update(HTML_ANCHOR.findall(line))
        cache[path] = found
    return cache[path]


def web_path(path: Path, location: str) -> str:
    """Where GitHub sends a relative link from this file, for example /owner/repo/issues/new."""
    folder = path.parent.relative_to(REPO).as_posix()
    return posixpath.normpath(posixpath.join(WEB_ROOT, "" if folder == "." else folder, location))


def check(path: Path, cache: dict[Path, set[str]]) -> tuple[int, list[str]]:
    problems, count = [], 0
    for number, line in enumerate(prose_lines(path.read_text(encoding="utf-8")), start=1):
        for match in LINK.finditer(line):
            target = match.group(1).strip("<>")
            if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE):
                continue
            count += 1
            where = f"{path.relative_to(REPO).as_posix()}:{number}"
            location, _, fragment = target.partition("#")
            location = unquote(location.partition("?")[0])
            if not location:
                resolved = path
            else:
                web = web_path(path, location)
                if web != WEB_ROOT and not web.startswith(WEB_ROOT + "/"):
                    page = web.split("/")[3] if web.startswith("/owner/repo/") else ""
                    if page not in REPO_PAGES:
                        problems.append(f"{where}: {target} -> leaves the repository, but not for one of its pages")
                    continue
                resolved = REPO / web[len(WEB_ROOT):].lstrip("/")
                if not resolved.exists():
                    problems.append(f"{where}: {target} -> missing {location}")
                    continue
            if fragment and resolved.is_file() and resolved.suffix.lower() == ".md":
                if unquote(fragment).lower() not in anchors(resolved, cache):
                    shown = resolved.relative_to(REPO).as_posix()
                    problems.append(f"{where}: {target} -> no heading #{fragment} in {shown}")
    return count, problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--verbose", action="store_true", help="print the number of links checked in each file")
    args = parser.parse_args()

    cache: dict[Path, set[str]] = {}
    total, problems, files = 0, [], markdown_files()
    for path in files:
        count, found = check(path, cache)
        total += count
        problems += found
        if args.verbose and count:
            print(f"{count:4} {path.relative_to(REPO).as_posix()}")
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    print(f"{'FAILED' if problems else 'OK'}: {total} relative links in {len(files)} Markdown files, {len(problems)} broken.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
