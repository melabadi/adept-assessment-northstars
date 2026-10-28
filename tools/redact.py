"""Keep tenant and account details out of the repository's screenshots and docs.

Subcommands:
  init     Build your local redaction list from what identifies your demo tenant: the subscription and tenant ids,
           your account and tenant domain, every GUID and host name in the demo resource groups, the unique tokens in
           resource names, the values in the solutions' azd environments, the RequestHub app registrations, your
           Windows user name, and your git e-mail address. The list is written OUTSIDE the repository; never commit it.
  check    Check images (read with Windows OCR) and every other file that is text, whatever its extension (.log,
           .css, .csproj, ...), for any value on the list, for e-mail addresses, for *.onmicrosoft.com domains, and for
           user profile paths. Binary files that are not images are listed as not checked. Exits 1 when something is
           found. Run it on every image before you commit it; tools/screenshot.mjs runs it for you.

Usage:
  python tools/redact.py init [--rg-prefix rg-ai-sdlc] [--env-glob <glob> ...] [--reset]
  python tools/redact.py check [--optimize] [--changed] [<file or folder> ...]

Options:
  --rg-prefix   resource group name prefix to read from Azure (default rg-ai-sdlc)
  --env-glob    extra glob of azd .env files to read (repeatable); solutions/*/.azure/*/.env is always read
  --reset       start a new list instead of adding to the existing one
  --optimize    after a PNG passes, re-encode it with a 256-color palette when that makes it smaller (needs Pillow)
  --changed     check every file that differs from origin/main, including uncommitted and untracked files

The list's location: %LOCALAPPDATA%\\ai-sdlc-demo\\redactions.json on Windows, ~/.config/ai-sdlc-demo/redactions.json
elsewhere, or the SCREENSHOT_REDACTIONS environment variable. OCR needs Windows 10 or later; elsewhere images are
skipped with a warning.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
GUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
HOST = re.compile(r"\b(?:[a-z0-9-]+\.)+(?:azurecontainerapps\.io|azure\.com|windows\.net|azurecr\.io|azure\.net)\b", re.I)
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
ALLOWED_EMAIL = re.compile(r"(noreply\.github\.com|@example\.(com|org)|@contoso\.com|@contoso\.onmicrosoft\.com)$", re.I)
TENANT_DOMAIN = re.compile(r"\b[A-Za-z0-9-]+\.onmicrosoft\.com\b")
PROFILE = re.compile(r"[A-Za-z]:\\Users\\([^\\\s\"'<>|:*?]+)")
GENERIC_LABELS = {"management", "login", "microsoftonline", "graph", "portal", "services", "ai", "openai",
                  "cognitiveservices", "search", "blob", "core", "windows", "net", "azure", "com", "privatelink",
                  "monitor", "applicationinsights", "centralus", "eastus", "eastus2", "westus", "westus2", "westus3",
                  "cnt-prod", "loadtesting", "postgres", "database", "vault", "azurecr", "io", "azurecontainerapps",
                  "sre", "api", "agents", "in", "livediagnostics", "documents", "queue", "table", "file", "dfs"}
ZERO_GUID = "00000000-0000-0000-0000-000000000000"
GENERIC_NAMES = {"contoso", "fabrikam", "default directory", "microsoft", "demo subscription", "you", "admin",
                 "administrator", "mod administrator", "global administrator", "user", "demo"}


def meaningful(value: str) -> bool:
    """False for values that identify nothing, such as the all-zeros GUID or a generic directory name."""
    v = value.strip().lower()
    return len(v) >= 4 and v not in GENERIC_NAMES and not re.fullmatch(r"[0-]+", v) and not re.fullmatch(r"(.)\1{7}-.*", v)


def list_path() -> Path:
    if os.environ.get("SCREENSHOT_REDACTIONS"):
        return Path(os.environ["SCREENSHOT_REDACTIONS"])
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ai-sdlc-demo" / "redactions.json"
    return Path.home() / ".config" / "ai-sdlc-demo" / "redactions.json"


def load_items() -> list[dict]:
    path = list_path()
    if not path.exists():
        sys.exit(f"No redaction list at {path}. Create it with: python tools/redact.py init")
    items = [i for i in json.loads(path.read_text(encoding="utf-8"))["items"] if meaningful(i["value"])]
    # Pages truncate long names ("ME-contoso-youralias…"), so identifying values also match by their prefixes.
    prefix_kinds = {"windows-user", "tenant-prefix", "tenant-domain", "subscription-name", "account", "git-email",
                    "git-name", "host-label", "name-token", "user-name"}
    expanded = list(items)
    for i in items:
        v = i["value"]
        if i["kind"] in prefix_kinds:
            # A letters-only start of a host name ("centralus") is a common word, not an identifier.
            expanded += [{"kind": i["kind"], "value": v[:n], "replacement": i["replacement"]}
                         for n in range(len(v) - 1, max(6, -(-len(v) // 2)) - 1, -1)
                         if i["kind"] not in ("host-label", "name-token") or re.search(r"\d", v[:n])]
        elif re.match(r"[0-9a-f]{8}-", v, re.I) and re.search("subscription|tenant", i["kind"]):
            expanded.append({"kind": i["kind"], "value": v[:8], "replacement": "00000000"})
    return expanded


def az(args: str):
    out = subprocess.run("az " + args + " -o json", shell=True, capture_output=True, text=True)
    if out.returncode != 0:
        first = (out.stderr.strip().splitlines() or ["failed"])[-1]
        print(f"warning: az {args.split()[0]} {args.split()[1] if len(args.split()) > 1 else ''}: {first[:160]}", file=sys.stderr)
        return None
    return json.loads(out.stdout or "null")


def init(args) -> None:
    path = list_path()
    items: dict[str, dict] = {}
    if path.exists() and not args.reset:
        items = {i["value"].lower(): i for i in json.loads(path.read_text(encoding="utf-8"))["items"] if meaningful(i["value"])}
    before = len(items)

    def add(kind: str, value, replacement: str) -> None:
        if value and meaningful(str(value)):
            items.setdefault(str(value).lower(), {"kind": kind, "value": str(value), "replacement": replacement})

    def add_from_text(text: str, guid_kind: str) -> None:
        for g in GUID.findall(text):
            add(guid_kind, g, ZERO_GUID)
        for host in HOST.findall(text):
            for label in host.lower().split("."):
                if label in GENERIC_LABELS or len(label) < 6:
                    continue
                tokens = [t for t in re.findall(r"(?<![a-z0-9])([a-z0-9]{13})(?![a-z0-9])", label)
                          if re.search(r"\d", t) and re.search(r"[a-z]", t)]
                if tokens:
                    for token in tokens:
                        add("name-token", token, "x" * 13)
                elif re.search(r"\d", label):
                    add("host-label", label, re.sub(r"[a-z0-9]", "x", label))

    acct = az("account show")
    if not acct:
        sys.exit("Sign in with az login first.")
    add("subscription-id", acct["id"], ZERO_GUID)
    add("tenant-id", acct["tenantId"], ZERO_GUID)
    add("subscription-name", acct.get("name"), "Demo subscription")
    upn = acct["user"]["name"]
    add("account", upn, "admin@contoso.onmicrosoft.com")
    if "@" in upn:
        domain = upn.split("@", 1)[1]
        add("tenant-domain", domain, "contoso.onmicrosoft.com")
        add("tenant-prefix", domain.split(".")[0], "contoso")
    add("tenant-name", acct.get("tenantDisplayName"), "Contoso")
    add("tenant-domain", acct.get("tenantDefaultDomain"), "contoso.onmicrosoft.com")

    me = az("ad signed-in-user show") or {}
    if not me:
        # Microsoft Graph can be unavailable (for example a conditional access re-check); the Resource Manager
        # token carries the same identity claims.
        token = az("account get-access-token --query accessToken")
        if token:
            import base64  # noqa: PLC0415
            payload = token.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            me = {"id": claims.get("oid"), "userPrincipalName": claims.get("upn") or claims.get("unique_name"),
                  "displayName": claims.get("name")}
    add("user-object-id", me.get("id"), ZERO_GUID)
    add("account", me.get("userPrincipalName"), "admin@contoso.onmicrosoft.com")
    add("account", me.get("mail"), "admin@contoso.onmicrosoft.com")
    name = me.get("displayName") or ""
    if len(name) >= 6 and name.lower() not in {"admin", "administrator"}:
        add("user-name", name, "Demo Admin")

    query = f"resources | where resourceGroup startswith '{args.rg_prefix}' | project name, properties, identity"
    resources = az(f'graph query -q "{query}" --first 1000') or {}
    for r in resources.get("data", []):
        add_from_text(json.dumps([r.get("properties"), r.get("identity")]), "resource-guid")
        for token in re.findall(r"(?<![a-z0-9])([a-z0-9]{13})(?![a-z0-9])", r["name"].lower()):
            if re.search(r"\d", token) and re.search(r"[a-z]", token):
                add("name-token", token, "x" * 13)

    # Portals also list resources outside the demo resource groups (the Foundry portal's resource list spans every
    # subscription you can see). Their names can embed the tenant number or your name: list those, and every name
    # with a random suffix.
    tenant_number = ""
    if "@" in upn:
        tenant_number = (re.search(r"\d{4,}", upn.split("@", 1)[1].split(".")[0]) or [""])[0]
        add("tenant-number", tenant_number, "0" * len(tenant_number))
    login = subprocess.run("gh api user --jq .login", shell=True, capture_output=True, text=True).stdout.strip().lower()
    personal = [p for p in (tenant_number, (os.environ.get("USERNAME") or "").lower(), login) if p and len(p) >= 4]
    everything = ("resources | project name | union (resourcecontainers | where type =~ "
                  "'microsoft.resources/subscriptions/resourcegroups' | project name)")
    for r in (az(f'graph query -q "{everything}" --first 1000') or {}).get("data", []):
        name = r["name"]
        low = name.lower()
        if any(p in low for p in personal) or (len(name) >= 8 and re.search(r"\d", name) and re.search(r"[a-z]", low)):
            add("resource-name", name, re.sub(r"[A-Za-z0-9]", "x", name))

    env_globs = [str(REPO / "solutions" / "*" / ".azure" / "*" / ".env")] + list(args.env_glob or [])
    for pattern in env_globs:
        for env in glob.glob(pattern):
            for line in Path(env).read_text(encoding="utf-8", errors="ignore").splitlines():
                if "=" in line:
                    add_from_text(line.split("=", 1)[1], "env-guid")

    for app in az('ad app list --display-name RequestHub --query "[].{appId:appId, id:id}"') or []:
        add("app-id", app["appId"], ZERO_GUID)
        add("app-object-id", app["id"], ZERO_GUID)

    add("windows-user", os.environ.get("USERNAME") or os.environ.get("USER"), "you")
    email = subprocess.run("git config user.email", shell=True, capture_output=True, text=True).stdout.strip()
    if email and not email.endswith("users.noreply.github.com"):
        add("git-email", email, "you@example.com")
    git_name = subprocess.run("git config user.name", shell=True, capture_output=True, text=True).stdout.strip()
    if " " in git_name:
        add("git-name", git_name, "Demo User")

    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"note": "Local only: values that identify your demo tenant. Never commit this file.",
            "items": sorted(items.values(), key=lambda i: (i["kind"], i["value"].lower()))}
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")
    kinds: dict[str, int] = {}
    for i in items.values():
        kinds[i["kind"]] = kinds.get(i["kind"], 0) + 1
    print(f"{path}: {len(items)} values ({len(items) - before} new): " + ", ".join(f"{k} {n}" for k, n in sorted(kinds.items())))


OCR_SCRIPT = r"""
param([string[]]$Paths)
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$type) { $task = $asTask.MakeGenericMethod($type).Invoke($null, @($op)); $null = $task.Wait(-1); $task.Result }
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
foreach ($p in $Paths) {
  "=== $p"
  $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($p)) ([Windows.Storage.StorageFile])
  $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
  $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
  $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
  $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
  $result.Lines | ForEach-Object { $_.Text }
  $stream.Dispose()
}
"""


def ocr(images: list[Path]) -> dict[Path, str]:
    """Text of each image, read with Windows OCR in tiles small enough for the engine."""
    if os.name != "nt":
        print("warning: OCR needs Windows; images were not read", file=sys.stderr)
        return {}
    from PIL import Image  # noqa: PLC0415

    texts: dict[Path, str] = {}
    with tempfile.TemporaryDirectory() as tmp:
        tiles: list[tuple[Path, str]] = []
        for image in images:
            with Image.open(image) as im:
                im = im.convert("RGB")
                step, overlap = 3000, 120
                for top in range(0, im.height, step - overlap):
                    for left in range(0, im.width, step - overlap):
                        tile = im.crop((left, top, min(left + step, im.width), min(top + step, im.height)))
                        if tile.width < 40 or tile.height < 20:
                            continue
                        name = os.path.join(tmp, f"{len(tiles)}.png")
                        tile.save(name)
                        tiles.append((image, name))
                        if left + step >= im.width:
                            break
                    if top + step >= im.height:
                        break
        script = os.path.join(tmp, "ocr.ps1")
        Path(script).write_text(OCR_SCRIPT, encoding="utf-8-sig")
        for start in range(0, len(tiles), 40):
            batch = tiles[start:start + 40]
            out = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script, "-Paths",
                                  *[t[1] for t in batch]], capture_output=True, text=True, encoding="utf-8")
            if out.returncode != 0:
                sys.exit("OCR failed: " + out.stderr.strip()[:300])
            current = None
            names = {t[1]: t[0] for t in batch}
            for line in out.stdout.splitlines():
                if line.startswith("=== "):
                    current = names.get(line[4:].strip())
                elif current is not None:
                    texts[current] = texts.get(current, "") + line + "\n"
    return texts


def findings(text: str, items: list[dict], from_ocr: bool) -> tuple[set[str], list[str]]:
    """Kinds of sensitive values in the text, and the generic matches (masked) that triggered them."""
    kinds: set[str] = set()
    details: list[str] = []
    lower = text.lower()
    squeezed = re.sub(r"\s+", "", lower)
    for item in items:
        value = item["value"].lower()
        if value in lower or (from_ocr and re.sub(r"\s+", "", value) in squeezed):
            kinds.add(item["kind"])

    def allowed_email(m: str) -> bool:
        # OCR can misread the placeholder domains, so any address on a placeholder domain is accepted there.
        domain = m.split("@", 1)[1].lower()
        return bool(ALLOWED_EMAIL.search(m)) or (from_ocr and any(d in domain for d in ("contoso", "example", "noreply")))

    for m in EMAIL.findall(text):
        if not allowed_email(m):
            kinds.add("email")
            details.append(m[0] + "***@" + m.split("@", 1)[1])
    for m in TENANT_DOMAIN.findall(text):
        if not m.lower().startswith("contoso."):
            kinds.add("onmicrosoft-domain")
    if any(m.lower() not in {"you", "public", "default"} for m in PROFILE.findall(text)):
        kinds.add("profile-path")
    return kinds, details


def changed_files() -> list[Path]:
    def lines(cmd: str) -> list[str]:
        return subprocess.run(cmd, shell=True, cwd=REPO, capture_output=True, text=True).stdout.splitlines()
    base = (lines("git merge-base HEAD origin/main") or ["origin/main"])[0]
    names = set(lines(f"git diff --name-only --diff-filter=d {base}")) | set(lines("git ls-files --others --exclude-standard"))
    return [REPO / n for n in sorted(names) if (REPO / n).is_file()]


def optimize(png: Path) -> None:
    from PIL import Image  # noqa: PLC0415

    with Image.open(png) as im:
        im.load()
        quantized = im.convert("RGB").quantize(colors=256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE)
    tmp = png.with_suffix(".tmp.png")
    quantized.save(tmp, optimize=True)
    if tmp.stat().st_size < png.stat().st_size:
        tmp.replace(png)
    else:
        tmp.unlink()


def is_text(path: Path) -> bool:
    """Whether a file reads as text: no NUL byte in its first 8 KB."""
    try:
        with path.open("rb") as handle:
            return b"\0" not in handle.read(8192)
    except OSError:
        return False


def check(args) -> int:
    items = load_items()
    files: list[Path] = []
    for target in args.paths:
        p = Path(target).resolve()
        if p.is_dir() and p.is_relative_to(REPO):
            # Only what git would commit: tracked files plus untracked files that are not ignored.
            listed = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", str(p)], cwd=REPO,
                                    capture_output=True, text=True, encoding="utf-8").stdout.splitlines()
            files += [REPO / n for n in listed if (REPO / n).is_file()]
        elif p.is_dir():
            files += [f for f in p.rglob("*") if f.is_file()]
        elif p.is_file():
            files.append(p)
        else:
            print(f"not found: {target}", file=sys.stderr)
            return 2
    if args.changed:
        files += changed_files()
    files = sorted({f.resolve() for f in files})
    if not files:
        print("nothing to check")
        return 0
    images = [f for f in files if f.suffix.lower() in IMAGE_EXT]
    text_files = [f for f in files if f.suffix.lower() not in IMAGE_EXT and is_text(f)]
    skipped = sorted(set(files) - set(images) - set(text_files))
    texts = ocr(images) if images else {}
    bad = 0

    def shown(f: Path) -> Path:
        return f.relative_to(REPO) if f.is_relative_to(REPO) else f

    for f in images + text_files:
        if f.suffix.lower() in IMAGE_EXT:
            kinds, details = findings(texts.get(f, ""), items, from_ocr=True)
        else:
            kinds, details = findings(f.read_text(encoding="utf-8", errors="ignore"), items, from_ocr=False)
        if kinds:
            bad += 1
            print(f"FOUND {shown(f)}: {', '.join(sorted(kinds))}" + (f" ({', '.join(sorted(set(details)))})" if details else ""))
        elif args.optimize and f.suffix.lower() == ".png":
            optimize(f)
    if skipped:
        print(f"warning: {len(skipped)} binary file(s) not checked; look at them yourself: "
              + ", ".join(str(shown(f)) for f in skipped), file=sys.stderr)
    checked = f"{len(images)} images (OCR) and {len(text_files)} text files"
    print(f"{'FAILED' if bad else 'OK'}: {checked} checked, {bad} with tenant or account details.")
    return 1 if bad else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p_init = sub.add_parser("init", help="build or extend your local redaction list")
    p_init.add_argument("--rg-prefix", default="rg-ai-sdlc", help="resource group name prefix (default rg-ai-sdlc)")
    p_init.add_argument("--env-glob", action="append", help="extra glob of azd .env files to read (repeatable)")
    p_init.add_argument("--reset", action="store_true", help="start a new list instead of adding to the existing one")
    p_check = sub.add_parser("check", help="check images and text files for tenant or account details")
    p_check.add_argument("paths", nargs="*", help="files or folders to check")
    p_check.add_argument("--optimize", action="store_true", help="re-encode passing PNGs with a 256-color palette")
    p_check.add_argument("--changed", action="store_true", help="also check every file that differs from origin/main")
    args = parser.parse_args()
    if args.command == "init":
        init(args)
        return 0
    return check(args)


if __name__ == "__main__":
    sys.exit(main())
