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
 *   --wait <selector>        wait until this element is visible (repeatable). Selectors are CSS, or text=<words> for
 *                            the innermost element showing those words.
 *   --select <sel>=<value>   choose this option in a list, or set this field (repeatable; runs before --wait). Example:
 *                            --select "#persona-select=u-ben" to view RequestHub as a reviewer
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
 *   --accept-consent <app>   when Microsoft's "Permissions requested" page names exactly this app, accept it for your
 *                            account only. Use it only for an app you decided to consent to.
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
// Thrown when the page rendered in the wrong color scheme ('theme') or at the wrong size or scale ('metrics'); the
// capture is then loaded again.
class ThemeRetry extends Error {}
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
const repeatable = new Set(['wait', 'click', 'hide', 'remove', 'select']);
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
  // Pages truncate long names ("ME-contoso-youralias…"), so identifying values also match by their prefixes.
  const PREFIX_KINDS = new Set(['windows-user', 'tenant-prefix', 'tenant-domain', 'subscription-name', 'account', 'git-email', 'git-name', 'host-label', 'name-token', 'user-name']);
  const expanded = [...items];
  for (const i of items) {
    if (PREFIX_KINDS.has(i.kind)) {
      for (let n = i.value.length - 1; n >= Math.max(6, Math.ceil(i.value.length / 2)); n--) {
        const prefix = i.value.slice(0, n);
        // A letters-only start of a host name ("centralus") is a common word, not an identifier.
        if (/^(host-label|name-token)$/.test(i.kind) && !/\d/.test(prefix)) continue;
        expanded.push({ kind: i.kind, value: prefix, replacement: i.replacement });
      }
    } else if (/^[0-9a-f]{8}-/i.test(i.value) && /subscription|tenant/.test(i.kind)) {
      expanded.push({ kind: i.kind, value: i.value.slice(0, 8), replacement: '00000000' });
    }
  }
  const sorted = expanded.sort((a, b) => b.value.length - a.value.length);
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
    if (maskGuids) t = t.replace(GUID, ZERO_GUID).replace(/\b[0-9a-f]{8}-[0-9a-f-]{1,27}(?=…|\.\.\.)/gi, (m) => ZERO_GUID.slice(0, m.length));
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
    // GitHub renders the account's appearance setting; pin its light theme unless --theme dark.
    if (/(^|\\.)github\\.com$/.test(location.hostname) && document.documentElement) {
      document.documentElement.setAttribute('data-color-mode', ${JSON.stringify(options.theme === 'dark' ? 'dark' : 'light')});
      document.documentElement.setAttribute('data-light-theme', 'light');
      document.documentElement.setAttribute('data-dark-theme', 'dark');
    }
  };
  if (document.documentElement) add();
  document.addEventListener('DOMContentLoaded', add);
})()`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const t0 = Date.now();
const debug = (label) => { if (process.env.SCREENSHOT_DEBUG === '1') console.error(`[${((Date.now() - t0) / 1000).toFixed(1)} s] ${label}`); };

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

// ---- Page mode: a minimal DevTools protocol client that creates and drives only its own tab. Playwright's
// connectOverCDP attaches to every open page of the shared capture browser: connecting gets slow, and each connection
// resets the emulated viewport and color scheme of the other sessions' pages.

// Element lookup inside a page: CSS selectors, or text=<substring> for the innermost element showing that text.
const FIND_SOURCE = `(() => {
  if (globalThis.__find) return;
  globalThis.__find = (sel) => {
    if (!sel.startsWith('text=')) return document.querySelector(sel);
    const needle = sel.slice(5).replace(/^["']|["']$/g, '').toLowerCase();
    let best = null;
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
    let n;
    while ((n = walker.nextNode())) {
      if (['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE'].includes(n.tagName)) continue;
      if ((n.innerText || '').toLowerCase().includes(needle)) best = n;
    }
    return best;
  };
  globalThis.__box = (sel) => {
    const el = globalThis.__find(sel);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none' ? { x: r.x, y: r.y, width: r.width, height: r.height } : null;
  };
})()`;
const PAGE_SCRIPTS = `${scrubberSource};${hostCssSource};${FIND_SOURCE}`;
// Whether the page's background is light (null when it is transparent): what the reader will see, whatever the
// media query says.
const RENDERED_LIGHT = `(() => {
  const lum = (el) => {
    if (!el) return null;
    const c = getComputedStyle(el).backgroundColor.match(/[\\d.]+/g);
    if (!c) return null;
    const [r, g, b, a = 1] = c.map(Number);
    return a < 0.5 ? null : (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
  };
  const l = lum(document.body) ?? lum(document.documentElement);
  return l === null ? null : l > 0.5;
})()`;

async function devtools(endpoint) {
  let version;
  try {
    version = await (await fetch(`${endpoint.replace(/\/$/, '')}/json/version`, { signal: AbortSignal.timeout(15_000) })).json();
  } catch (error) {
    fail(2, `No browser at ${endpoint} (${error.message}). Start the capture browser first (CONTRIBUTING.md, "Screenshots").`);
  }
  const ws = new WebSocket(version.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve, { once: true });
    ws.addEventListener('error', () => reject(new Error('cannot open the DevTools connection')), { once: true });
  });
  let nextId = 0;
  const pending = new Map();
  const listeners = new Set();
  ws.addEventListener('message', (event) => {
    const msg = JSON.parse(event.data);
    if (msg.id !== undefined && pending.has(msg.id)) {
      const call = pending.get(msg.id);
      pending.delete(msg.id);
      if (msg.error) call.reject(new Error(`${call.method}: ${msg.error.message}`)); else call.resolve(msg.result);
    } else {
      for (const listener of listeners) listener(msg);
    }
  });
  const send = (method, params = {}, sessionId, timeoutMs = 60_000) => new Promise((resolve, reject) => {
    const id = ++nextId;
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`${method}: no answer in ${timeoutMs / 1000} s`)); }, timeoutMs);
    pending.set(id, { method, resolve: (v) => { clearTimeout(timer); resolve(v); }, reject: (e) => { clearTimeout(timer); reject(e); } });
    ws.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
  });
  return { send, on: (fn) => listeners.add(fn), close: () => ws.close() };
}

async function openTab(cdp, { width, height, scale, theme }) {
  const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank', background: true });
  const { sessionId } = await cdp.send('Target.attachToTarget', { targetId, flatten: true });
  const sessions = new Set([sessionId]);
  const contexts = new Map();
  const state = { loads: 0, inflight: 0, lastNetwork: Date.now() };
  const media = { features: [{ name: 'prefers-color-scheme', value: theme }] };
  const setup = async (sid, child) => {
    await cdp.send('Runtime.enable', {}, sid);
    await cdp.send('Page.enable', {}, sid).catch(() => {});
    await cdp.send('Network.enable', {}, sid).catch(() => {});
    await cdp.send('Page.addScriptToEvaluateOnNewDocument', { source: PAGE_SCRIPTS }, sid).catch(() => {});
    await cdp.send('Emulation.setEmulatedMedia', media, sid).catch(() => {});
    await cdp.send('Target.setAutoAttach', { autoAttach: true, waitForDebuggerOnStart: true, flatten: true }, sid).catch(() => {});
    if (child) await cdp.send('Runtime.runIfWaitingForDebugger', {}, sid).catch(() => {});
  };
  cdp.on((msg) => {
    if (!msg.sessionId || !sessions.has(msg.sessionId)) return;
    const p = msg.params ?? {};
    switch (msg.method) {
      case 'Runtime.executionContextCreated':
        if (p.context.auxData?.isDefault) contexts.set(`${msg.sessionId}:${p.context.id}`, { sessionId: msg.sessionId, id: p.context.id, frameId: p.context.auxData.frameId });
        break;
      case 'Runtime.executionContextDestroyed': contexts.delete(`${msg.sessionId}:${p.executionContextId}`); break;
      case 'Runtime.executionContextsCleared': for (const [k, c] of contexts) if (c.sessionId === msg.sessionId) contexts.delete(k); break;
      case 'Page.loadEventFired': if (msg.sessionId === sessionId) state.loads++; break;
      case 'Network.requestWillBeSent': state.inflight++; state.lastNetwork = Date.now(); break;
      case 'Network.loadingFinished': case 'Network.loadingFailed': state.inflight = Math.max(0, state.inflight - 1); state.lastNetwork = Date.now(); break;
      case 'Target.attachedToTarget':
        if (p.targetInfo.type === 'iframe') { sessions.add(p.sessionId); setup(p.sessionId, true).catch(() => {}); } else cdp.send('Runtime.runIfWaitingForDebugger', {}, p.sessionId).catch(() => {});
        break;
      case 'Target.detachedFromTarget': sessions.delete(p.sessionId); break;
      default:
    }
  });
  await setup(sessionId, false);
  const metrics = async (h) => {
    await cdp.send('Emulation.setDeviceMetricsOverride', { width, height: Math.min(Math.ceil(h), 12_000), deviceScaleFactor: scale, mobile: false }, sessionId);
  };
  await metrics(height);
  await cdp.send('Emulation.setFocusEmulationEnabled', { enabled: true }, sessionId);

  const evalIn = async (ctx, expression) => {
    const r = await cdp.send('Runtime.evaluate', { expression, contextId: ctx.id, returnByValue: true, awaitPromise: true }, ctx.sessionId, 30_000);
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description?.split('\n')[0] ?? r.exceptionDetails.text);
    return r.result.value;
  };
  const frames = async () => {
    const out = [];
    for (const sid of sessions) {
      try {
        const walk = (node) => { out.push({ sessionId: sid, id: node.frame.id, url: node.frame.url, parentId: node.frame.parentId }); (node.childFrames ?? []).forEach(walk); };
        walk((await cdp.send('Page.getFrameTree', {}, sid)).frameTree);
      } catch { /* detached */ }
    }
    return out;
  };
  const contextFor = (frame) => [...contexts.values()].find((c) => c.sessionId === frame.sessionId && c.frameId === frame.id);
  const top = async () => {
    const tree = await cdp.send('Page.getFrameTree', {}, sessionId);
    return contextFor({ sessionId, id: tree.frameTree.frame.id });
  };
  const evalTop = async (expression) => {
    for (let i = 0; i < 40; i++) {
      const ctx = await top();
      if (ctx) { try { return await evalIn(ctx, expression); } catch (e) { if (!/context|destroyed|navigat/i.test(e.message)) throw e; } }
      await sleep(250);
    }
    throw new Error('the page did not get ready');
  };
  const evalAll = async (expression) => {
    const results = [];
    for (const ctx of [...contexts.values()]) { try { results.push(await evalIn(ctx, expression)); } catch { /* detached frame */ } }
    return results;
  };
  return {
    targetId, sessionId, sessions, state, evalTop, evalAll, evalIn, frames, contextFor, metrics,
    send: (method, params, timeoutMs) => cdp.send(method, params, sessionId, timeoutMs),
    reapplyMedia: async () => { for (const sid of sessions) await cdp.send('Emulation.setEmulatedMedia', media, sid).catch(() => {}); },
  };
}

async function settle(tab, { loadTimeout = 90_000, idleCap = 8_000 } = {}) {
  const start = Date.now();
  const loadsBefore = tab.state.loads;
  while (Date.now() - start < loadTimeout) {
    if (tab.state.loads > loadsBefore || (await tab.evalTop('document.readyState').catch(() => '')) === 'complete') break;
    await sleep(250);
  }
  const idleStart = Date.now();
  while (Date.now() - idleStart < idleCap) {
    const quiet = Date.now() - tab.state.lastNetwork;
    if ((tab.state.inflight === 0 && quiet > 600) || quiet > 2_500) break;
    await sleep(200);
  }
}

// With --pick-account (or SCREENSHOT_PICK_ACCOUNT=1): when Microsoft's "Pick an account" page appears, click the tile of
// the account on the redaction list (your Azure CLI account). With --accept-consent "<exact app name>": when Microsoft's
// "Permissions requested" page names exactly that app, accept it for your account only (the organization-wide consent box
// stays unchecked). It never types anything; anything else needs you.
async function signInSteps(tab) {
  const pick = options['pick-account'] || process.env.SCREENSHOT_PICK_ACCOUNT === '1';
  const consentApp = options['accept-consent'] ?? '';
  const accounts = items.filter((i) => i.kind === 'account').map((i) => i.value.toLowerCase());
  const onSignIn = async () => /(^|\.)login\.microsoftonline\.com$/i.test(await tab.evalTop('location.hostname').catch(() => ''));
  for (let attempt = 0; attempt < 5; attempt++) {
    // Sign-in pages often pass through on their own (silent sign-in, "Working on it"): give them time first.
    const until = Date.now() + 12_000;
    while (Date.now() < until && await onSignIn()) {
      const ready = await tab.evalTop(`Boolean(document.querySelector('[data-test-id], [role=button], input[type=submit], #idBtn_Back'))`).catch(() => false);
      if (ready) break;
      await sleep(500);
    }
    if (!(await onSignIn())) return;
    if (!pick && !consentApp) return;
    await sleep(800);
    const page = await tab.evalTop(`(() => {
      const text = document.body ? document.body.innerText : '';
      const visible = (e) => e && e.offsetParent !== null && getComputedStyle(e).visibility !== 'hidden';
      return { consent: /Permissions requested/i.test(text), app: ${JSON.stringify(consentApp)} !== '' && text.includes(${JSON.stringify(consentApp)}),
               staySignedIn: /Stay signed in\\?/i.test(text) && visible(document.querySelector('#idBtn_Back')),
               secret: [...document.querySelectorAll('input[type=password], #idDiv_SAOTCAS_Title, #idDiv_SAOTCC_Title')].some(visible) };
    })()`);
    if (page.secret) refuse(3, 'Refused: Microsoft sign-in needs your password or MFA. Complete it in the capture browser, then retry.');
    if (page.staySignedIn) {
      // "Stay signed in?": answer No. Sign-in completes, and no persistent session is created.
      await tab.evalTop(`document.querySelector('#idBtn_Back').click()`);
    } else if (page.consent) {
      if (!page.app) refuse(3, 'Refused: Microsoft asks to grant an app permissions. Pass --accept-consent "<exact app name>" only for an app the user approved.');
      await tab.evalTop(`(() => {
        document.querySelectorAll('input[type=checkbox]').forEach((c) => { if (c.checked) c.click(); });
        (document.querySelector('input[type=submit][value=Accept]') || document.querySelector('#idSIButton9')).click();
      })()`);
    } else if (pick && accounts.length) {
      const clicked = await tab.evalTop(`(() => {
        const accounts = ${JSON.stringify(accounts)};
        const tile = [...document.querySelectorAll('[data-test-id], [role=button]')].find((e) => accounts.some((a) => (e.innerText || '').toLowerCase().includes(a)));
        if (tile) tile.click();
        return Boolean(tile);
      })()`);
      if (!clicked) return;
    } else {
      return;
    }
    const leave = Date.now() + 30_000;
    while (Date.now() < leave && /(^|\.)login\.microsoftonline\.com$/i.test(await tab.evalTop('location.hostname').catch(() => 'login.microsoftonline.com'))) await sleep(500);
    await settle(tab, { loadTimeout: 30_000 });
  }
}

async function capturePage(url, out) {
  const endpoint = options.cdp ?? process.env.SCREENSHOT_CDP ?? 'http://127.0.0.1:9333';
  const width = Number(options.width ?? 1280);
  const height = Number(options.height ?? 800);
  const scale = Number(options.scale ?? 2);
  const theme = options.theme === 'dark' ? 'dark' : 'light';
  const cdp = await devtools(endpoint);
  const tab = await openTab(cdp, { width, height, scale, theme });
  let saved = false;
  // One attempt: navigate, wait, mask, check, capture. A page that renders in the wrong color scheme (GitHub's React
  // views decide at startup) is loaded again; masking refusals are never retried.
  const captureOnce = async () => {
    saved = false;
    debug('tab open');
    await tab.send('Page.navigate', { url }, 120_000);
    debug('navigated');
    await settle(tab);
    debug('settled');
    await signInSteps(tab);
    debug('sign-in steps done');

    // Where --wait, --click, and --selector apply: the page, or the first frame whose URL contains --frame. Frames such
    // as the Azure portal's React blades attach late, so look for up to a minute.
    const scope = async () => {
      if (!options.frame) return { evaluate: (e) => tab.evalTop(e), frame: null };
      const until = Date.now() + 60_000;
      for (;;) {
        const frame = (await tab.frames()).find((f) => f.url.includes(options.frame));
        const ctx = frame && tab.contextFor(frame);
        if (ctx) return { evaluate: (e) => tab.evalIn(ctx, e), frame };
        if (Date.now() > until) refuse(2, `No frame whose URL contains "${options.frame}"`);
        await sleep(1000);
      }
    };
    const ensureHelpers = async (s) => s.evaluate(`${FIND_SOURCE}; true`);
    // --select "<css>=<value>": choose an option (or set a field) the way a person would, so frameworks such as
    // React see the change. Runs before --wait, so the waits see the result.
    for (const spec of options.select ?? []) {
      const at = spec.lastIndexOf('=');
      if (at < 1) refuse(2, `--select needs <selector>=<value>: ${spec}`);
      const sel = JSON.stringify(spec.slice(0, at));
      const value = JSON.stringify(spec.slice(at + 1));
      const until = Date.now() + 60_000;
      for (;;) {
        const s = await scope();
        await ensureHelpers(s);
        const result = await s.evaluate(`(() => {
          const el = __find(${sel});
          if (!el) return 'missing';
          const proto = el instanceof HTMLSelectElement ? HTMLSelectElement.prototype : el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
          Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, ${value});
          el.dispatchEvent(new Event('input', { bubbles: true }));
          el.dispatchEvent(new Event('change', { bubbles: true }));
          return el.value === ${value} ? 'ok' : 'no such option';
        })()`).catch(() => 'missing');
        if (result === 'ok') break;
        if (result !== 'missing' || Date.now() > until) refuse(2, `--select ${spec}: ${result}`);
        await sleep(400);
      }
      await sleep(500);
      await settle(tab, { loadTimeout: 5_000 });
    }
    for (const sel of options.wait ?? []) {
      const until = Date.now() + 120_000;
      for (;;) {
        const s = await scope();
        await ensureHelpers(s);
        if (await s.evaluate(`__box(${JSON.stringify(sel)})`).catch(() => null)) break;
        if (Date.now() > until) refuse(2, `Timed out waiting for ${sel}`);
        await sleep(400);
      }
    }
    for (const sel of options.click ?? []) {
      const s = await scope();
      await ensureHelpers(s);
      const found = await s.evaluate(`(() => { const el = __find(${JSON.stringify(sel)}); if (!el) return false; el.scrollIntoView({ block: 'center' }); el.click(); return true; })()`);
      if (!found) refuse(2, `Nothing to click: ${sel}`);
      await sleep(500);
      await settle(tab, { loadTimeout: 5_000 });
    }
    debug('waits and clicks done');
    await sleep(Number(options.delay ?? 1500));
    for (const sel of options.hide ?? []) await tab.evalAll(`document.querySelectorAll(${JSON.stringify(sel)}).forEach((e) => { e.style.visibility = 'hidden'; })`);
    for (const sel of options.remove ?? []) await tab.evalAll(`document.querySelectorAll(${JSON.stringify(sel)}).forEach((e) => { e.style.setProperty('display', 'none', 'important'); })`);
    await tab.evalAll(`${PAGE_SCRIPTS}; document.head && document.head.insertAdjacentHTML('beforeend', '<style>*, *::before, *::after { caret-color: transparent !important; animation-play-state: paused !important; transition: none !important; }</style>'); true`);

    const scrubAndCheck = async () => {
      await tab.evalAll(`${PAGE_SCRIPTS}; globalThis.__scrub.scrubTree(document); globalThis.__scrub.scrubInputs(); true`);
      await sleep(250);
      return [...new Set((await tab.evalAll('globalThis.__scrub ? globalThis.__scrub.check() : ["unscrubbed-frame"]')).flat())];
    };
    const before = await scrubAndCheck();
    debug(`scrubbed and checked ${tab.sessions.size} session(s)`);
    if (before.includes('sign-in-page')) refuse(3, `Refused: ${new URL(url).host} redirected to a sign-in page. Sign in in the capture browser (or pass --pick-account), then retry. Nothing was saved.`);
    if (before.length) refuse(3, `Refused before capture: unmasked ${before.join(', ')} on ${new URL(url).host}. Nothing was saved.`);

    // The viewport and color scheme may have been reset by something else; set them again and check both the media
    // query and what the page actually rendered. A resize makes pages that read the scheme once (GitHub's React views)
    // read it again.
    await tab.reapplyMedia();
    await tab.metrics(height + 1);
    await sleep(200);
    await tab.metrics(height);
    await sleep(500);
    if ((await tab.evalTop(`matchMedia('(prefers-color-scheme: dark)').matches`)) !== (theme === 'dark')) throw new ThemeRetry('theme');
    const rendered = await tab.evalTop(RENDERED_LIGHT);
    if (rendered !== null && rendered !== (theme === 'light')) throw new ThemeRetry('theme');
    // Another DevTools client can reset this tab's device metrics; an image captured then can come out tiled or at
    // the wrong scale. Check them before and after the capture, like the color scheme.
    const metricsKept = async () => {
      // devicePixelRatio is a 32-bit float (2 reads as 2.0000000298…), so compare it with a tolerance.
      const [dpr, w] = JSON.parse(await tab.evalTop('JSON.stringify([devicePixelRatio, innerWidth])'));
      const kept = Math.abs(dpr - scale) < 0.01 && w === width;
      if (!kept) debug(`viewport is ${w} CSS px at scale ${dpr}; expected ${width} at ${scale}`);
      return kept;
    };
    if (!(await metricsKept())) throw new ThemeRetry('metrics');

    debug('scheme pinned');
    mkdirSync(path.dirname(path.resolve(out)), { recursive: true });
    const capture = async (clip) => {
      const m = await tab.send('Page.getLayoutMetrics');
      const vp = m.cssVisualViewport ?? m.visualViewport;
      const params = { format: 'png', fromSurface: true, captureBeyondViewport: false };
      if (clip) params.clip = { x: clip.x + vp.pageX, y: clip.y + vp.pageY, width: clip.width, height: clip.height, scale: 1 };
      const { data } = await tab.send('Page.captureScreenshot', params, 90_000);
      writeFileSync(out, Buffer.from(data, 'base64'));
    };
    // Offset of the scoped frame in the page, for element boxes measured inside it.
    const frameOffset = async (s) => {
      if (!s.frame) return { x: 0, y: 0 };
      const owner = await cdp.send('DOM.getFrameOwner', { frameId: s.frame.id }, tab.sessionId).catch(() => null);
      if (!owner) return { x: 0, y: 0 };
      const { model } = await cdp.send('DOM.getBoxModel', { backendNodeId: owner.backendNodeId }, tab.sessionId);
      return { x: model.content[0], y: model.content[1] };
    };
    if (options.selector) {
      const pad = Number(options.padding ?? 8);
      const sel = JSON.stringify(options.selector);
      const s = await scope();
      await ensureHelpers(s);
      const measure = async () => {
        const box = await s.evaluate(`(() => { const el = __find(${sel}); if (!el) return null; el.scrollIntoView({ block: 'nearest' }); return __box(${sel}); })()`);
        if (!box) return null;
        const off = await frameOffset(s);
        return { x: box.x + off.x, y: box.y + off.y, width: box.width, height: box.height };
      };
      await tab.evalTop('window.scrollTo(0, 0)');
      let box = await measure();
      if (!box) refuse(2, `Element not visible: ${options.selector}`);
      if (box.y < 0 || box.y + box.height + pad > height) {
        // Grow the viewport so the whole element fits from the top of the page, then measure again.
        await tab.evalTop('window.scrollTo(0, 0)');
        await tab.metrics(Math.max(height, box.y + box.height + pad + 16));
        await sleep(700);
        box = await measure();
        if (!box) refuse(2, `Element not visible: ${options.selector}`);
      }
      await capture({ x: Math.max(0, box.x - pad), y: Math.max(0, box.y - pad), width: box.width + 2 * pad, height: box.height + 2 * pad });
    } else if (options.clip) {
      const [x, y, w, h] = options.clip.split(',').map(Number);
      if (y + h > height) { await tab.metrics(y + h); await sleep(700); }
      await capture({ x, y, width: w, height: h });
    } else if (options.full) {
      await tab.evalTop('window.scrollTo(0, 0)');
      const m = await tab.send('Page.getLayoutMetrics');
      await tab.metrics(Math.max(height, (m.cssContentSize ?? m.contentSize).height));
      await sleep(700);
      await capture(null);
    } else {
      await capture(null);
    }
    saved = true;
    const after = [...new Set((await tab.evalAll('globalThis.__scrub ? globalThis.__scrub.check() : ["unscrubbed-frame"]')).flat())];
    if (after.length) { try { unlinkSync(out); } catch {} saved = false; refuse(3, `Refused after capture: unmasked ${after.join(', ')} appeared. The image was deleted.`); }
    const renderedAfter = await tab.evalTop(RENDERED_LIGHT);
    const schemeKept = (await tab.evalTop(`matchMedia('(prefers-color-scheme: dark)').matches`)) === (theme === 'dark') && (renderedAfter === null || renderedAfter === (theme === 'light'));
    const metricsStill = await metricsKept();
    if (!schemeKept || !metricsStill) {
      try { unlinkSync(out); } catch {}
      saved = false;
      throw new ThemeRetry(schemeKept ? 'metrics' : 'theme');
    }
  };
  try {
    for (let attempt = 1; ; attempt++) {
      try {
        await captureOnce();
        break;
      } catch (error) {
        if (!(error instanceof ThemeRetry)) throw error;
        if (attempt >= 3) {
          refuse(2, error.message === 'metrics'
            ? 'The page kept losing its viewport size or scale; another tool attached to the capture browser may be resetting it. Close that tool and retry.'
            : `The page kept rendering in the wrong color scheme. If the site has its own theme setting, set it to ${theme}.`);
        }
        debug(`${error.message === 'metrics' ? 'viewport size or scale' : 'color scheme'} mismatch, loading again (attempt ${attempt + 1})`);
      }
    }
  } finally {
    await cdp.send('Target.closeTarget', { targetId: tab.targetId }).catch(() => {});
    cdp.close();
  }
  if (saved) {
    ocrCheck(out);
    console.log(`saved ${out}`);
  }
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
