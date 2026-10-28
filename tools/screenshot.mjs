#!/usr/bin/env node
/**
 * Capture documentation screenshots with tenant and account details masked.
 *
 * page      Opens a URL in a browser you are signed in to (connected through the Chrome DevTools Protocol), masks every
 *           value in your local redaction list in all frames while the page renders, plus e-mail addresses,
 *           *.onmicrosoft.com domains, user profile paths, and GUIDs. It checks the page again after the capture and
 *           refuses to keep the image if anything is left. Then `python tools/redact.py check` reads the image with OCR.
 * terminal  Renders command output as a terminal window, with the same masking.
 *
 * Usage:
 *   node tools/screenshot.mjs browser
 *   node tools/screenshot.mjs page <url> <out.png> [options]
 *   node tools/screenshot.mjs terminal <out.png> (--input <file> | --run "<command>") [options]
 *
 * browser   Starts the capture browser: Chrome (or Edge) with its own profile outside the repository, reachable only
 *           from this machine on port 9333. Sign in to GitHub and Azure there once.
 *
 * Page options:
 *   --wait <selector>        wait until this element is visible (repeatable; Playwright selectors such as text=Done)
 *   --click <selector>       click this element before capturing (repeatable, in order)
 *   --frame <url part>       apply --wait, --click, and --selector inside the first frame whose URL contains this
 *   --selector <selector>    capture only this element, with --padding pixels around it (default 8)
 *   --clip <x,y,w,h>         capture this rectangle of the viewport, in CSS pixels
 *   --full                   capture the whole scrollable page
 *   --hide <selector>        make these elements invisible, keeping their space (repeatable)
 *   --remove <selector>      remove these elements from the layout (repeatable). GitHub's staff bar is always removed.
 *   --width <px>, --height <px>  viewport size (default 1280 x 800)
 *   --scale <n>              device scale factor (default 2, for sharp images on high-density screens)
 *   --theme <light|dark>     color scheme the page sees (default light, so every README looks the same)
 *   --delay <ms>             extra wait after the page settles (default 1500)
 *   --keep-guids             do not mask GUIDs
 *   --pick-account           when Microsoft's "Pick an account" page appears, click the tile of the account on your
 *                            redaction list (never types anything); or set SCREENSHOT_PICK_ACCOUNT=1
 *   --cdp <url>              DevTools endpoint (default: $SCREENSHOT_CDP or http://127.0.0.1:9333)
 *
 * Terminal options:
 *   --input <file>           text to render; lines starting with "PS> " or "$ " are shown as commands
 *   --run "<command>"        run this command with PowerShell 7 (or bash) in --cwd and render its output
 *   --cwd <dir>              working directory for --run (default: current directory)
 *   --title <text>           window title (default: PowerShell)
 *   --tail <n>               keep only the last n lines of output
 *   --width <px>             window width in CSS pixels (default 960)
 *   --scale <n>              device scale factor (default 2)
 *
 * The redaction list lives outside the repository (create it with `python tools/redact.py init`); see CONTRIBUTING.md,
 * "Screenshots". Exit codes: 0 saved, 2 usage or setup error, 3 refused because a sensitive value was left.
 */
import { createRequire } from 'node:module';
import { existsSync, mkdirSync, readFileSync, unlinkSync, writeFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const fail = (code, message) => { console.error(message); process.exit(code); };
class Refusal extends Error { constructor(code, message) { super(message); this.code = code; } }
const refuse = (code, message) => { throw new Refusal(code, message); };

let chromium;
try {
  // Only the repository's own Playwright: Node would otherwise pick up any copy in a parent folder.
  if (!existsSync(path.join(repo, 'app', 'web', 'node_modules', 'playwright', 'package.json'))) throw new Error('missing');
  ({ chromium } = createRequire(path.join(repo, 'app', 'web', 'package.json'))('playwright'));
} catch {
  fail(2, 'Playwright is missing. Run: npm ci --prefix app/web');
}

const [mode, ...rest] = process.argv.slice(2);
if (!mode || mode === '--help' || mode === '-h') {
  const source = readFileSync(fileURLToPath(import.meta.url), 'utf8');
  console.log(source.slice(source.indexOf('/**') + 3, source.indexOf('*/')).replace(/^ \* ?/gm, '').trim());
  process.exit(mode ? 0 : 2);
}
if (mode === 'browser') {
  // Starts the capture browser: a separate Chrome or Edge profile, reachable only from this machine.
  const { spawn } = await import('node:child_process');
  const candidates = process.platform === 'win32'
    ? [`${process.env.ProgramFiles}\\Google\\Chrome\\Application\\chrome.exe`, `${process.env['ProgramFiles(x86)']}\\Google\\Chrome\\Application\\chrome.exe`, `${process.env['ProgramFiles(x86)']}\\Microsoft\\Edge\\Application\\msedge.exe`]
    : process.platform === 'darwin'
      ? ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge']
      : ['/usr/bin/google-chrome', '/usr/bin/microsoft-edge', '/usr/bin/chromium'];
  const exe = candidates.find((c) => c && existsSync(c));
  if (!exe) fail(2, 'Chrome or Edge not found.');
  const profile = process.platform === 'win32'
    ? path.join(process.env.LOCALAPPDATA ?? os.homedir(), 'ai-sdlc-demo', 'capture-browser')
    : path.join(os.homedir(), '.config', 'ai-sdlc-demo', 'capture-browser');
  const port = new URL(process.env.SCREENSHOT_CDP ?? 'http://127.0.0.1:9333').port;
  spawn(exe, [`--remote-debugging-port=${port}`, `--user-data-dir=${profile}`, '--no-first-run', '--no-default-browser-check',
    '--disable-features=CalculateNativeWinOcclusion', '--disable-backgrounding-occluded-windows', '--disable-renderer-backgrounding',
    '--disable-background-timer-throttling', 'https://github.com/login', 'https://portal.azure.com/'], { detached: true, stdio: 'ignore' }).unref();
  console.log(`Capture browser started (profile ${profile}, DevTools on 127.0.0.1:${port}). Sign in there; close it when you are done.`);
  process.exit(0);
}
if (!['page', 'terminal'].includes(mode)) fail(2, 'Usage: node tools/screenshot.mjs browser | page <url> <out.png> [options] | terminal <out.png> --input <file> [options]. See the header of this file.');
const positional = [];
const options = {};
const repeatable = new Set(['wait', 'click', 'hide', 'remove']);
for (let i = 0; i < rest.length; i++) {
  const arg = rest[i];
  if (!arg.startsWith('--')) { positional.push(arg); continue; }
  const key = arg.slice(2);
  if (['full', 'keep-guids', 'pick-account'].includes(key)) { options[key] = true; continue; }
  const value = rest[++i];
  if (value === undefined) fail(2, `Missing value for ${arg}`);
  if (repeatable.has(key)) (options[key] ??= []).push(value); else options[key] = value;
}

const redactionFile = process.env.SCREENSHOT_REDACTIONS
  || (process.platform === 'win32'
    ? path.join(process.env.LOCALAPPDATA ?? os.homedir(), 'ai-sdlc-demo', 'redactions.json')
    : path.join(os.homedir(), '.config', 'ai-sdlc-demo', 'redactions.json'));
if (!existsSync(redactionFile)) fail(2, `No redaction list at ${redactionFile}. Create it with: python tools/redact.py init`);
const GENERIC_NAMES = new Set(['contoso', 'fabrikam', 'default directory', 'microsoft', 'demo subscription', 'you', 'admin',
  'administrator', 'mod administrator', 'global administrator', 'user', 'demo']);
const meaningful = (v) => {
  const s = String(v ?? '').trim().toLowerCase();
  return s.length >= 4 && !GENERIC_NAMES.has(s) && !/^[0-]+$/.test(s) && !/^(.)\1{7}-/.test(s);
};
const items = JSON.parse(readFileSync(redactionFile, 'utf8')).items.filter((i) => meaningful(i.value));
const maskGuids = !options['keep-guids'];

// Pure text masking, shared by Node (terminal mode) and the browser. Must stay self-contained: it is serialized.
function makeFix(items, maskGuids) {
  const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const sorted = [...items].sort((a, b) => b.value.length - a.value.length);
  const listRx = sorted.length ? new RegExp(sorted.map((i) => esc(i.value)).join('|'), 'gi') : null;
  const replacements = new Map(sorted.map((i) => [i.value.toLowerCase(), i.replacement]));
  const GUID = /\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/gi;
  const ZERO_GUID = '00000000-0000-0000-0000-000000000000';
  const EMAIL = /[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}/g;
  const ALLOWED_EMAIL = /(noreply\.github\.com|@example\.(com|org)|@contoso\.com|@contoso\.onmicrosoft\.com)$/i;
  const TENANT_DOMAIN = /\b[A-Za-z0-9-]+\.onmicrosoft\.com\b/g;
  const PROFILE = /([A-Za-z]:\\Users\\)([^\\\s"'<>|:*?]+)/g;
  const keepProfile = (name) => /^(you|public|default)$/i.test(name);
  const fix = (s) => {
    if (typeof s !== 'string' || !s) return s;
    let t = listRx ? s.replace(listRx, (m) => replacements.get(m.toLowerCase()) ?? 'x'.repeat(m.length)) : s;
    t = t.replace(EMAIL, (m) => (ALLOWED_EMAIL.test(m) ? m : 'user@contoso.com'));
    t = t.replace(TENANT_DOMAIN, (m) => (/^contoso\./i.test(m) ? m : 'contoso.onmicrosoft.com'));
    t = t.replace(PROFILE, (m, prefix, name) => (keepProfile(name) ? m : `${prefix}you`));
    if (maskGuids) t = t.replace(GUID, ZERO_GUID);
    return t;
  };
  const findKinds = (all) => {
    const lower = all.toLowerCase();
    const kinds = new Set(sorted.filter((i) => lower.includes(i.value.toLowerCase())).map((i) => i.kind));
    if ((all.match(EMAIL) || []).some((m) => !ALLOWED_EMAIL.test(m))) kinds.add('email');
    if ((all.match(TENANT_DOMAIN) || []).some((m) => !/^contoso\./i.test(m))) kinds.add('onmicrosoft-domain');
    if ([...all.matchAll(PROFILE)].some((m) => !keepProfile(m[2]))) kinds.add('profile-path');
    if (maskGuids && (all.match(GUID) || []).some((m) => m !== ZERO_GUID)) kinds.add('guid');
    return [...kinds];
  };
  return { fix, findKinds };
}

// Runs in every frame of the page: masks displayed text as it appears, and reports what is left. It never changes
// page state: script and style content, hidden inputs, and sign-in pages are left alone, and visible input values are
// masked only at capture time.
function installScrubber({ fix, findKinds }) {
  if (globalThis.__scrub) return true;
  const signIn = /(^|\.)(login\.microsoftonline\.com|login\.live\.com|login\.windows\.net|login\.microsoft\.com|account\.live\.com|msauth\.net|msftauth\.net)$/i.test(location.hostname)
    || (/(^|\.)github\.com$/i.test(location.hostname) && /^\/(login|session|sessions)(\/|$)/.test(location.pathname));
  if (signIn) {
    const top = window === window.top;
    globalThis.__scrub = { scrubTree() {}, scrubInputs() {}, check: () => (top ? ['sign-in-page'] : []) };
    return true;
  }
  const ATTRS = ['title', 'aria-label', 'aria-description', 'placeholder', 'alt', 'data-tooltip'];
  const SKIP = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE']);
  const filter = { acceptNode: (n) => (n.nodeType === 1 && SKIP.has(n.tagName) ? 2 : 1) };
  const skipped = (n) => n.parentElement && SKIP.has(n.parentElement.tagName);
  const isElement = (n) => n && n.nodeType === 1;
  const visibleInput = (n) => (n.tagName === 'INPUT' && !/^(hidden|password)$/i.test(n.type || '')) || n.tagName === 'TEXTAREA';
  const scrubNode = (node) => {
    if (!node) return;
    if (node.nodeType === 3) {
      if (skipped(node)) return;
      const v = fix(node.nodeValue);
      if (v !== node.nodeValue) node.nodeValue = v;
      return;
    }
    if (!isElement(node) || SKIP.has(node.tagName)) return;
    for (const a of ATTRS) {
      const v = node.getAttribute(a);
      if (v) { const f = fix(v); if (f !== v) node.setAttribute(a, f); }
    }
    if (node.shadowRoot && !node.shadowRoot.__scrubObserved) { scrubTree(node.shadowRoot); observe(node.shadowRoot); }
  };
  const scrubTree = (root) => {
    if (!root) return;
    if (isElement(root) || root.nodeType === 3) scrubNode(root);
    if (root.nodeType === 3 || (isElement(root) && SKIP.has(root.tagName))) return;
    const walker = (root.ownerDocument || root).createTreeWalker(root, 1 | 4, filter);
    let n;
    while ((n = walker.nextNode())) scrubNode(n);
  };
  const observe = (root) => {
    root.__scrubObserved = true;
    new MutationObserver((mutations) => {
      for (const m of mutations) {
        if (m.type === 'childList') m.addedNodes.forEach((n) => scrubTree(n));
        else scrubNode(m.target);
      }
    }).observe(root, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ATTRS });
  };
  const eachInput = (root, fn) => {
    root.querySelectorAll('input, textarea').forEach((n) => { if (visibleInput(n)) fn(n); });
    root.querySelectorAll('*').forEach((n) => { if (n.shadowRoot) eachInput(n.shadowRoot, fn); });
  };
  const scrubInputs = () => eachInput(document, (n) => { const f = fix(n.value); if (f !== n.value) n.value = f; });
  const check = () => {
    const texts = [document.title || ''];
    const collect = (root) => {
      const walker = (root.ownerDocument || root).createTreeWalker(root, 1 | 4, filter);
      let n;
      while ((n = walker.nextNode())) {
        if (n.nodeType === 3) { if (!skipped(n)) texts.push(n.nodeValue); continue; }
        for (const a of ATTRS) { const v = n.getAttribute(a); if (v) texts.push(v); }
        if (n.shadowRoot) collect(n.shadowRoot);
      }
    };
    collect(document);
    eachInput(document, (n) => texts.push(n.value));
    return findKinds(texts.join('\n'));
  };
  globalThis.__scrub = { scrubTree, scrubInputs, check };
  observe(document);
  const full = () => scrubTree(document);
  document.addEventListener('DOMContentLoaded', full);
  addEventListener('load', full);
  full();
  return true;
}
const scrubberSource = `(${installScrubber})((${makeFix})(${JSON.stringify(items)}, ${maskGuids}))`;
const { fix: fixText } = makeFix(items, maskGuids);

// Page furniture that never belongs in public docs, removed on every page of these hosts.
const HOST_CSS = {
  'github.com': '.staffbar-container, #serverstats { display: none !important; }',
};
const hostCssSource = `(() => {
  const rules = ${JSON.stringify(HOST_CSS)};
  const add = () => {
    for (const [host, css] of Object.entries(rules)) {
      if ((location.host === host || location.host.endsWith('.' + host)) && !document.getElementById('__screenshot_css')) {
        const style = document.createElement('style');
        style.id = '__screenshot_css';
        style.textContent = css;
        (document.head || document.documentElement).appendChild(style);
      }
    }
  };
  if (document.documentElement) add();
  document.addEventListener('DOMContentLoaded', add);
})()`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function scrubAllFrames(page) {
  for (const frame of page.frames()) {
    try {
      await frame.evaluate(scrubberSource);
      await frame.evaluate(hostCssSource);
      await frame.evaluate(() => { globalThis.__scrub.scrubTree(document); globalThis.__scrub.scrubInputs(); });
    } catch { /* detached or navigating frame */ }
  }
}

async function leftovers(page) {
  const found = new Set();
  for (const frame of page.frames()) {
    try {
      (await frame.evaluate(() => (globalThis.__scrub ? globalThis.__scrub.check() : ['unscrubbed-frame']))).forEach((k) => found.add(k));
    } catch { /* detached frame */ }
  }
  return [...found];
}

function ocrCheck(out) {
  const result = spawnSync('python', [path.join(repo, 'tools', 'redact.py'), 'check', '--optimize', out], { stdio: 'inherit' });
  if (result.status !== 0) {
    try { unlinkSync(out); } catch {}
    fail(3, `Refused: ${out} did not pass tools/redact.py check, and was deleted.`);
  }
}

// With --pick-account (or SCREENSHOT_PICK_ACCOUNT=1): when Microsoft's "Pick an account" page appears, click the tile of
// the account on the redaction list (your Azure CLI account). It never types anything; anything else needs you.
async function pickAccount(page) {
  if (!(options['pick-account'] || process.env.SCREENSHOT_PICK_ACCOUNT === '1')) return;
  const accounts = items.filter((i) => i.kind === 'account').map((i) => i.value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  for (let attempt = 0; attempt < 3; attempt++) {
    if (!/(^|\.)login\.microsoftonline\.com$/i.test(new URL(page.url()).hostname)) return;
    if (!accounts.length) return;
    const tile = page.locator('[data-test-id], [role="button"]').filter({ hasText: new RegExp(accounts.join('|'), 'i') }).first();
    try { await tile.waitFor({ state: 'visible', timeout: 15_000 }); } catch { return; }
    await tile.click();
    await page.waitForURL((u) => !/(^|\.)login\.microsoftonline\.com$/i.test(new URL(u).hostname), { timeout: 45_000 }).catch(() => {});
    if (await page.locator('input[type="password"], #idDiv_SAOTCAS_Title, #idDiv_SAOTCC_Title').count()) {
      refuse(3, 'Refused: Microsoft sign-in needs your password or MFA. Complete it in the capture browser, then retry.');
    }
    await page.waitForLoadState('networkidle', { timeout: 20_000 }).catch(() => {});
  }
}

async function capturePage(url, out) {
  const cdp = options.cdp ?? process.env.SCREENSHOT_CDP ?? 'http://127.0.0.1:9333';
  const width = Number(options.width ?? 1280);
  const height = Number(options.height ?? 800);
  const scale = Number(options.scale ?? 2);
  let browser;
  try { browser = await chromium.connectOverCDP(cdp, { timeout: 60_000 }); } catch (error) { fail(2, `No browser at ${cdp} (${error.message.split('\n')[0]}). Start the capture browser first (CONTRIBUTING.md, "Screenshots").`); }
  const context = browser.contexts()[0];
  const page = await context.newPage();
  try {
    await page.addInitScript({ content: scrubberSource });
    await page.addInitScript({ content: hostCssSource });
    const session = await context.newCDPSession(page);
    await session.send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: scale, mobile: false });
    await session.send('Emulation.setFocusEmulationEnabled', { enabled: true });
    // One look in every README: light unless --theme dark, whatever the operating system's setting.
    await page.emulateMedia({ colorScheme: options.theme === 'dark' ? 'dark' : 'light' });
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    await page.waitForLoadState('networkidle', { timeout: 20_000 }).catch(() => {});
    await pickAccount(page);
    const scope = () => {
      if (!options.frame) return page;
      const frame = page.frames().find((f) => f.url().includes(options.frame));
      if (!frame) refuse(2, `No frame whose URL contains "${options.frame}"`);
      return frame;
    };
    for (const sel of options.wait ?? []) await scope().locator(sel).first().waitFor({ state: 'visible', timeout: 120_000 });
    for (const sel of options.click ?? []) {
      await scope().locator(sel).first().click({ timeout: 60_000 });
      await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {});
    }
    await sleep(Number(options.delay ?? 1500));
    for (const sel of options.hide ?? []) {
      for (const frame of page.frames()) await frame.evaluate((s) => document.querySelectorAll(s).forEach((e) => { e.style.visibility = 'hidden'; }), sel).catch(() => {});
    }
    for (const sel of options.remove ?? []) {
      for (const frame of page.frames()) await frame.evaluate((s) => document.querySelectorAll(s).forEach((e) => { e.style.setProperty('display', 'none', 'important'); }), sel).catch(() => {});
    }
    await scrubAllFrames(page);
    await sleep(300);
    const before = await leftovers(page);
    if (before.includes('sign-in-page')) refuse(3, `Refused: ${new URL(url).host} redirected to a sign-in page. Sign in in the capture browser (or pass --pick-account), then retry. Nothing was saved.`);
    if (before.length) refuse(3, `Refused before capture: unmasked ${before.join(', ')} on ${new URL(url).host}. Nothing was saved.`);

    mkdirSync(path.dirname(path.resolve(out)), { recursive: true });
    // Captured through the DevTools protocol (Playwright's own screenshot ignores the emulated scale on a connected
    // browser), always within the viewport: capturing beyond it resizes the page and re-flows layouts such as
    // GitHub's after the element was measured. When the target is taller than the viewport, the viewport grows first
    // and the target is measured again.
    await page.addStyleTag({ content: '*, *::before, *::after { caret-color: transparent !important; animation-play-state: paused !important; transition: none !important; }' }).catch(() => {});
    const setHeight = async (h) => {
      await session.send('Emulation.setDeviceMetricsOverride', { width, height: Math.min(Math.ceil(h), 12_000), deviceScaleFactor: scale, mobile: false });
      await sleep(700);
    };
    const capture = async (clip) => {
      const metrics = await session.send('Page.getLayoutMetrics');
      const vp = metrics.cssVisualViewport ?? metrics.visualViewport;
      const params = { format: 'png', fromSurface: true, captureBeyondViewport: false };
      if (clip) params.clip = { x: clip.x + vp.pageX, y: clip.y + vp.pageY, width: clip.width, height: clip.height, scale: 1 };
      const { data } = await session.send('Page.captureScreenshot', params);
      writeFileSync(out, Buffer.from(data, 'base64'));
    };
    if (options.selector) {
      const pad = Number(options.padding ?? 8);
      const target = scope().locator(options.selector).first();
      await page.evaluate(() => window.scrollTo(0, 0));
      await target.scrollIntoViewIfNeeded();
      await sleep(300);
      let box = await target.boundingBox();
      if (!box) refuse(2, `Element not visible: ${options.selector}`);
      if (box.y < 0 || box.y + box.height + pad > height) {
        // Grow the viewport so the whole element fits from the top of the page, then measure again.
        await page.evaluate(() => window.scrollTo(0, 0));
        box = await target.boundingBox();
        await setHeight(Math.max(height, (box?.y ?? 0) + (box?.height ?? 0) + pad + 16));
        await target.scrollIntoViewIfNeeded();
        await sleep(300);
        box = await target.boundingBox();
        if (!box) refuse(2, `Element not visible: ${options.selector}`);
      }
      await capture({ x: Math.max(0, box.x - pad), y: Math.max(0, box.y - pad), width: box.width + 2 * pad, height: box.height + 2 * pad });
    } else if (options.clip) {
      const [x, y, w, h] = options.clip.split(',').map(Number);
      if (y + h > height) await setHeight(y + h);
      await capture({ x, y, width: w, height: h });
    } else if (options.full) {
      await page.evaluate(() => window.scrollTo(0, 0));
      const metrics = await session.send('Page.getLayoutMetrics');
      const size = metrics.cssContentSize ?? metrics.contentSize;
      await setHeight(Math.max(height, size.height));
      await capture(null);
    } else {
      await capture(null);
    }
    const after = await leftovers(page);
    if (after.length) { try { unlinkSync(out); } catch {} refuse(3, `Refused after capture: unmasked ${after.join(', ')} appeared. The image was deleted.`); }
  } finally {
    await page.close().catch(() => {});
  }
  ocrCheck(out);
  console.log(`saved ${out}`);
  process.exit(0);
}

function ansiToHtml(text) {
  const escape = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const colors = { 30: '#6e7681', 31: '#ff7b72', 32: '#3fb950', 33: '#d29922', 34: '#58a6ff', 35: '#bc8cff', 36: '#39c5cf', 37: '#e6edf3', 90: '#8b949e', 91: '#ffa198', 92: '#56d364', 93: '#e3b341', 94: '#79c0ff', 95: '#d2a8ff', 96: '#56d4dd', 97: '#ffffff' };
  let html = '';
  let open = false;
  for (const part of text.split(/(\x1b\[[0-9;]*m)/)) {
    const m = part.match(/^\x1b\[([0-9;]*)m$/);
    if (!m) { html += escape(part.replace(/\x1b\[[0-9;?]*[A-Za-z]/g, '')); continue; }
    if (open) { html += '</span>'; open = false; }
    const codes = m[1].split(';').map(Number);
    const style = [];
    for (const c of codes) { if (c === 1) style.push('font-weight:600'); if (colors[c]) style.push(`color:${colors[c]}`); }
    if (style.length) { html += `<span style="${style.join(';')}">`; open = true; }
  }
  return open ? `${html}</span>` : html;
}

async function captureTerminal(out) {
  let text;
  if (options.input) {
    const buf = readFileSync(options.input);
    text = buf[0] === 0xff && buf[1] === 0xfe ? buf.toString('utf16le').slice(1) : buf.toString('utf8').replace(/^\uFEFF/, '');
  } else if (options.run) {
    const shell = process.platform === 'win32' ? ['pwsh', ['-NoProfile', '-Command', options.run]] : ['bash', ['-lc', options.run]];
    const result = spawnSync(shell[0], shell[1], { cwd: options.cwd ?? process.cwd(), encoding: 'utf8', env: { ...process.env, FORCE_COLOR: '1' }, maxBuffer: 64 * 1024 * 1024 });
    text = `PS> ${options.run}\n${result.stdout ?? ''}${result.stderr ?? ''}`;
  } else {
    fail(2, 'terminal mode needs --input <file> or --run "<command>"');
  }
  let lines = text.replace(/\r\n/g, '\n').replace(/\n+$/, '').split('\n');
  if (options.tail && lines.length > Number(options.tail)) lines = ['…', ...lines.slice(-Number(options.tail))];
  const masked = lines.map((l) => fixText(l));
  const body = masked.map((l) => {
    const cmd = l.match(/^(PS>|\$) (.*)$/);
    return cmd ? `<span class="prompt">${cmd[1]}</span> <span class="cmd">${ansiToHtml(cmd[2])}</span>` : ansiToHtml(l);
  }).join('\n');
  const width = Number(options.width ?? 960);
  const title = fixText(options.title ?? 'PowerShell').replace(/</g, '&lt;');
  const html = `<!doctype html><meta charset="utf-8"><style>
    body{margin:0;padding:16px;background:#ffffff;font-family:"Segoe UI",system-ui,sans-serif}
    .win{width:${width}px;border-radius:10px;overflow:hidden;box-shadow:0 6px 24px rgba(0,0,0,.25);background:#0d1117;border:1px solid #30363d}
    .bar{height:34px;display:flex;align-items:center;gap:8px;padding:0 12px;background:#161b22;color:#8b949e;font-size:13px}
    .dot{width:12px;height:12px;border-radius:50%}.r{background:#ff5f57}.y{background:#febc2e}.g{background:#28c840}
    .t{margin-left:10px}
    pre{margin:0;padding:14px 16px 16px;color:#e6edf3;font:13px/1.45 "Cascadia Mono","Cascadia Code",Consolas,"Segoe UI Emoji",monospace;white-space:pre-wrap;word-break:break-word}
    .prompt{color:#3fb950;font-weight:600}.cmd{color:#e6edf3;font-weight:600}
  </style><div class="win"><div class="bar"><span class="dot r"></span><span class="dot y"></span><span class="dot g"></span><span class="t">${title}</span></div><pre>${body}</pre></div>`;
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ deviceScaleFactor: Number(options.scale ?? 2), viewport: { width: width + 32, height: 400 } });
    await page.setContent(html);
    await page.evaluate(scrubberSource);
    const left = await leftovers(page);
    if (left.length) refuse(3, `Refused: unmasked ${left.join(', ')} in the output.`);
    mkdirSync(path.dirname(path.resolve(out)), { recursive: true });
    await page.locator('.win').screenshot({ path: out, animations: 'disabled', omitBackground: false });
  } finally {
    await browser.close();
  }
  ocrCheck(out);
  console.log(`saved ${out}`);
  process.exit(0);
}

try {
  if (mode === 'page') {
    if (positional.length !== 2) fail(2, 'Usage: node tools/screenshot.mjs page <url> <out.png> [options]');
    await capturePage(positional[0], positional[1]);
  } else {
    if (positional.length !== 1) fail(2, 'Usage: node tools/screenshot.mjs terminal <out.png> --input <file> [options]');
    await captureTerminal(positional[0]);
  }
} catch (error) {
  if (error instanceof Refusal) fail(error.code, error.message);
  fail(2, `Capture failed: ${error.message.split('\n')[0]}`);
}
