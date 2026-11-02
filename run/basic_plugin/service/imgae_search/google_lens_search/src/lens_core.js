// Google Lens 反向图像搜索核心库
//
// 设计要点（都是踩过才知道的）：
//   · 引擎能力差别极大：SauceNAO 是唯一「无 key、纯 HTTP、直连可达」的，其余三家
//     （yandex/bing/baidu）的直连接口全是空壳或被拒，必须真浏览器跑 DOM。
//     所以：业务只读 engines config 决定用谁，探针没跑过就只开 saucenao。
//   · 浏览器是**单例**：headless Edge 起来一次、复用一个 page、一次只跑一个引擎。
//     每次命令新开浏览器既慢又会漏进程（验收第 7 条就是查这个）。
//   · 出站请求一律走 safeFetch（防 SSRF）或白名单里的固定 POST；候选页面的 og/作者
//     信息同样走 safeFetch。绝不把用户图片发到白名单外的域名。
//   · 无服务端 token 依赖。

import crypto from 'node:crypto';
import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawn, execFileSync } from 'node:child_process';
import { safeFetch, validateFetchUrl } from './safe-fetch.js';


const MODULE_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

/** 辅助搜索函数 */
/** 必应的搜索结果链接会包一层 `bing.com/ck/a?…&u=a1<base64url>`，这里还原成真实地址。 */
export function decodeBingHref(href) {
  const raw = String(href ?? '');
  const m = raw.match(/[?&]u=a1([^&]+)/);
  if (!m) return raw;
  try {
    const b64 = m[1].replace(/-/g, '+').replace(/_/g, '/');
    const padded = b64 + '='.repeat((4 - (b64.length % 4)) % 4);
    const decoded = Buffer.from(padded, 'base64').toString('utf8');
    return /^https?:\/\//i.test(decoded) ? decoded : raw;
  } catch {
    return raw;
  }
}

/** 把必应页面上抓到的 (href,text) 列表洗成 [{url,title}]：解包、去重、去掉必应自家链接。 */
export function parseBingSearchLinks(list) {
  const out = [];
  const seen = new Set();
  for (const item of Array.isArray(list) ? list : []) {
    const url = decodeBingHref(item?.href ?? item?.url ?? '');
    if (!/^https?:\/\//i.test(url)) continue;
    const host = hostOf(url);
    if (!host || host.endsWith('bing.com') || host.endsWith('microsoft.com')) continue;
    const key = url.split('#')[0];
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ url: key, title: trimText(String(item?.text ?? ''), 160) });
  }
  return out;
}

/**
 * 兜底搜索：直接使用无头浏览器读取必应搜索页。
 * 慢（约 4~8 秒一次），但不需要任何 key，而且能真的给出 `x.com/<handle>` 这种链接。
 */
export async function bingWebSearch(query, { timeoutMs = 20000, exe } = {}) {
  const q = encodeURIComponent(trimText(String(query ?? ''), 200));
  if (!q) return [];
  const url = `https://www.bing.com/search?q=${q}&setlang=zh-Hans&mkt=zh-CN`;
  const expression = `(() => {
    const anchors = Array.from(document.querySelectorAll('#b_results a[href]')).slice(0, 80);
    return JSON.stringify(anchors.map((a) => ({ href: a.getAttribute('href'), text: (a.textContent || '').trim().slice(0, 120) })));
  })()`;
  const raw = await browserProbe(url, expression, { timeoutMs, settleMs: 1200, exe });
  let list = [];
  try {
    list = JSON.parse(String(raw ?? '[]'));
  } catch {
    list = [];
  }
  return parseBingSearchLinks(list);
}

/** 谷歌结果页的链接是 `/url?q=<真实地址>&sa=…`，这里还原；自家链接（google.*、gstatic）丢掉。 */
export function parseGoogleSearchLinks(list) {
  const out = [];
  const seen = new Set();
  for (const item of Array.isArray(list) ? list : []) {
    let url = String(item?.href ?? item?.url ?? '');
    const wrapped = url.match(/^\/url\?q=([^&]+)/) || url.match(/[?&]url=([^&]+)/);
    if (wrapped) {
      try {
        url = decodeURIComponent(wrapped[1]);
      } catch {
        continue;
      }
    }
    if (!/^https?:\/\//i.test(url)) continue;
    const host = hostOf(url);
    if (!host || /(^|\.)google\./.test(host) || host.endsWith('gstatic.com') || host.endsWith('googleusercontent.com')) continue;
    const key = url.split('#')[0];
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ url: key, title: trimText(String(item?.text ?? ''), 160) });
  }
  return out;
}

/**
 * 谷歌搜索（需要魔法）。国内网络下必应/360 会刻意不返回 `x.com` 链接，
 * 所以「用作者名反查推特」这条路只能走谷歌 —— 由调用方套 withVpn 使用。
 */
export async function googleWebSearch(query, { timeoutMs = 25000, exe } = {}) {
  const q = encodeURIComponent(trimText(String(query ?? ''), 200));
  if (!q) return [];
  const url = `https://www.google.com/search?q=${q}&hl=zh-CN&num=20`;
  const expression = `(() => {
    const anchors = Array.from(document.querySelectorAll('a[href]')).slice(0, 200);
    return JSON.stringify(anchors.map((a) => ({ href: a.getAttribute('href'), text: (a.textContent || '').trim().slice(0, 120) })));
  })()`;
  const raw = await browserProbe(url, expression, { timeoutMs, settleMs: 1200, exe });
  let list = [];
  try {
    list = JSON.parse(String(raw ?? '[]'));
  } catch {
    list = [];
  }
  return parseGoogleSearchLinks(list);
}

/** 结果里有没有「像账号」的链接（推特/微博/B站/ins/pixiv）。用来判断要不要再上谷歌。 */
export function hasPlatformResult(rows) {
  for (const row of Array.isArray(rows) ? rows : []) {
    if (matchPlatform(row?.url)) return true;
  }
  return false;
}

export function createSearchFn(root = MODULE_ROOT, { withVpn = null, onLog = null } = {}) {
  return async (query) => {
    const text = String(query);
    let rows = [];
    try {
      rows = await bingWebSearch(text);
    } catch (error) {
      if (onLog) onLog(`[Google Lens] 必应搜索失败：${error?.message ?? error}`);
    }
    if (!hasPlatformResult(rows) && typeof withVpn === 'function') {
      try {
        const viaGoogle = await withVpn(() => googleWebSearch(text));
        if (Array.isArray(viaGoogle) && viaGoogle.length) {
          if (onLog) onLog(`[Google Lens] 谷歌搜索返回 ${viaGoogle.length} 条结果`);
          return viaGoogle;
        }
      } catch (error) {
        if (onLog) onLog(`[Google Lens] 谷歌搜索失败：${error?.message ?? error}`);
      }
    }
    return rows;
  };
}

export const ENGINE_IDS = ['saucenao', 'lens', 'yandex', 'bing', 'baidu', 'google', 'iqdb', 'tracemoe'];

// 只允许把图发给这几个域名（写死在代码里，不读配置 —— 这是安全边界，不是可调项）。
// 2026-10-29 加：iqdb.org（动漫图库）、api.trace.moe（动画截图）。
// ascii2d 试过但被 Cloudflare 拦（headless 永远停在「正在进行安全验证」），不列进来。
const UPLOAD_HOSTS = [
  'saucenao.com', 'yandex.com', 'yandex.ru', 'bing.com', 'baidu.com', 'google.com', 'lens.google.com',
  'iqdb.org', 'trace.moe',
  // 搜索类（只在 need-search 的场合用：必应/谷歌/DDG/Brave/Startpage）
  'duckduckgo.com', 'brave.com', 'startpage.com'
];

const BROWSER_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0';
const BROWSER_ENGINES = new Set(['yandex', 'bing', 'baidu', 'google']);

// 3：新增 Google Lens 渠道。缓存 key 里带版本号，升版本等于让旧缓存（只查 SauceNAO 的结果）
// 全部失效 —— 否则同一张图会一直吃老结果，看起来「改了跟没改一样」。
export const ENGINES_VERSION = 3;

// ── 小工具 ────────────────────────────────────────────────────────────────
// 计时器不 unref：unref 后独自跑脚本时会「事件循环空了」直接退出（exit 13）。
const sleep = (ms) => new Promise((resolve) => { setTimeout(resolve, ms); });

function hostOf(url) {
  try { return new URL(String(url)).hostname.toLowerCase(); } catch { return ''; }
}

function hostAllowed(url) {
  const host = hostOf(url);
  if (!host) return false;
  return UPLOAD_HOSTS.some((allowed) => host === allowed || host.endsWith('.' + allowed));
}

function decodeEntities(s) {
  return String(s ?? '')
    .replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&nbsp;/g, ' ')
    .replace(/&#(\d+);/g, (_, d) => String.fromCharCode(Number(d)))
    .replace(/&#x([0-9a-f]+);/gi, (_, h) => String.fromCharCode(parseInt(h, 16)));
}

function stripTags(s) {
  return decodeEntities(String(s ?? '').replace(/<[^>]*>/g, ' ')).replace(/\s+/g, ' ').trim();
}

function absUrl(href, base) {
  try { return new URL(decodeEntities(href), base).toString(); } catch { return ''; }
}

function trimText(s, max) {
  const t = String(s ?? '').replace(/\s+/g, ' ').trim();
  return t.length > max ? t.slice(0, max - 1) + '…' : t;
}

export function sha256Hex(buf) {
  return crypto.createHash('sha256').update(buf).digest('hex');
}

// ── 单例 headless 浏览器（零依赖，裸驱 CDP） ────────────────────────────────
const BROWSER_CANDIDATES = [
  // Windows
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  // Linux
  '/usr/bin/google-chrome',
  '/usr/bin/google-chrome-stable',
  '/usr/bin/chromium',
  '/usr/bin/chromium-browser',
  '/usr/bin/microsoft-edge',
  '/snap/bin/chromium',
  // macOS
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'
];

let browserState = null; // { proc, userDataDir, port, ws, pageId, nextId, pending }
// 用固定 profile：谷歌这类站点会把「已验证」写进 cookie，临时目录一关就全丢。
const BROWSER_PROFILE_DIR = path.join(os.tmpdir(), 'eridanus-lens-profile');
// 无头 Edge 的默认 UA 里带 HeadlessChrome，谷歌一眼就判机器人，改成一个正常的 Chrome UA。
const BROWSER_UA_CHROME = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36';
let browserStarting = null;

function resolveBrowserExe(exe) {
  if (exe && fs.existsSync(exe)) return exe;
  for (const envKey of ['CHROME_PATH', 'EDGE_PATH', 'BROWSER_PATH', 'PUPPETEER_EXECUTABLE_PATH']) {
    const p = process.env[envKey];
    if (p && fs.existsSync(p)) return p;
  }
  for (const candidate of BROWSER_CANDIDATES) if (fs.existsSync(candidate)) return candidate;
  // 兜底尝试系统 PATH 中的可执行名
  const bins = process.platform === 'win32'
    ? ['msedge.exe', 'chrome.exe']
    : ['google-chrome', 'chromium-browser', 'chromium', 'microsoft-edge'];
  for (const b of bins) {
    try {
      const cmd = process.platform === 'win32' ? 'where' : 'which';
      const out = execFileSync(cmd, [b], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'], windowsHide: true }).trim();
      const first = out.split(/\r?\n/)[0].trim();
      if (first && fs.existsSync(first)) return first;
    } catch {}
  }
  return '';
}

async function waitForFile(file, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      if (fs.existsSync(file)) {
        const text = fs.readFileSync(file, 'utf8').trim();
        if (text) return text;
      }
    } catch {}
    await sleep(120);
  }
  throw new Error('浏览器没起来（等不到 DevToolsActivePort）');
}

async function startBrowser({ timeoutMs = 25000, exe, headed = false, profileDir = '', proxy = '' } = {}) {
  const exePath = resolveBrowserExe(exe);
  if (!exePath) throw new Error('找不到 Edge/Chrome 可执行文件');
  const userDataDir = profileDir || fs.mkdtempSync(path.join(os.tmpdir(), 'lens-browser-'));
  try { fs.mkdirSync(userDataDir, { recursive: true }); } catch {}
  // 上一次留下的 DevToolsActivePort 是过期值，留着会连到死端口
  try { fs.rmSync(path.join(userDataDir, 'DevToolsActivePort'), { force: true }); } catch {}
  const args = [
    ...(headed ? [] : ['--headless=new']),
    '--no-sandbox',
    '--disable-setuid-sandbox',
    '--disable-dev-shm-usage',
    '--disable-gpu',
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-extensions',
    '--disable-background-networking',
    '--disable-blink-features=AutomationControlled',
    '--disable-features=Translate,MediaRouter',
    '--lang=zh-CN',
    ...(proxy ? [`--proxy-server=${proxy}`] : []),
    '--remote-debugging-port=0',
    `--user-data-dir=${userDataDir}`,
    'about:blank'
  ];
  const proc = spawn(exePath, args, { stdio: 'ignore', windowsHide: true });
  const portFile = path.join(userDataDir, 'DevToolsActivePort');
  const raw = await waitForFile(portFile, timeoutMs);
  const port = Number(String(raw).split(/\r?\n/)[0]);
  if (!Number.isFinite(port) || port <= 0) throw new Error('DevToolsActivePort 内容异常');

  // 拿一个 page target 的 ws 地址
  const deadline = Date.now() + timeoutMs;
  let target = null;
  while (Date.now() < deadline && !target) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/json/list`, { signal: AbortSignal.timeout(3000) });
      const list = await response.json();
      target = (Array.isArray(list) ? list : []).find((t) => t.type === 'page' && t.webSocketDebuggerUrl) ?? null;
    } catch {}
    if (!target) await sleep(150);
  }
  if (!target) throw new Error('浏览器没有可用的 page target');

  const ws = new WebSocket(target.webSocketDebuggerUrl);
  const pending = new Map();
  let nextId = 1;
  const opened = new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('CDP 连接超时')), timeoutMs);
    ws.addEventListener('open', () => { clearTimeout(timer); resolve(); });
    ws.addEventListener('error', (event) => { clearTimeout(timer); reject(new Error('CDP 连接失败')); });
  });
  ws.addEventListener('message', (event) => {
    let msg;
    try { msg = JSON.parse(typeof event.data === 'string' ? event.data : String(event.data)); } catch { return; }
    if (!msg?.id) return;
    const entry = pending.get(msg.id);
    if (!entry) return;
    pending.delete(msg.id);
    if (msg.error) entry.reject(new Error(msg.error.message || 'CDP 错误'));
    else entry.resolve(msg.result);
  });
  await opened;

  browserState = {
    proc, userDataDir, port, ws, pending, proxy,
    send(method, params = {}) {
      const id = nextId++;
      return new Promise((resolve, reject) => {
        // 页面正在跳转 / 目标进程卡死时，CDP 可能永远不回 —— 没有这个超时，
        // 一条 evaluate 就能把整个任务挂住十几分钟（真实踩过）。
        const timer = setTimeout(() => {
          pending.delete(id);
          reject(new Error(`CDP 超时：${method}`));
        }, 25000);
        pending.set(id, {
          resolve: (value) => { clearTimeout(timer); resolve(value); },
          reject: (error) => { clearTimeout(timer); reject(error); }
        });
        try { ws.send(JSON.stringify({ id, method, params })); }
        catch (error) { clearTimeout(timer); pending.delete(id); reject(error); }
      });
    }
  };
  return browserState;
}

let browserProxyUrl = ''; // 这次任务要不要让浏览器单独走代理（--proxy-server）
export function setBrowserProxy(url) { browserProxyUrl = String(url ?? ''); }
export function currentBrowserProxy() { return browserProxyUrl; }

async function ensureBrowser(options = {}) {
  // 代理通道是启动参数（--proxy-server），起来之后改不了：换了通道只能重开浏览器。
  const wantProxy = String(options.proxy ?? browserProxyUrl ?? '');
  if (browserState) {
    if (String(browserState.proxy ?? '') === wantProxy) return browserState;
    await closeBrowser();
  }
  if (!browserStarting) {
    browserStarting = (async () => {
      try {
        return await startBrowser({ ...options, proxy: wantProxy, profileDir: fs.mkdtempSync(path.join(os.tmpdir(), 'lens-browser-')) });
      } catch {
        // 固定 profile 被占用/损坏时就退回临时目录：宁可丢 cookie，也不能让整条命令失败
        return await startBrowser({ ...options, proxy: wantProxy, profileDir: fs.mkdtempSync(path.join(os.tmpdir(), 'lens-browser-')) });
      }
    })().finally(() => { browserStarting = null; });
  }
  return browserStarting;
}

export async function closeBrowser() {
  const state = browserState;
  browserState = null;
  browserStarting = null;
  if (!state) return;
  try { state.ws.close(); } catch {}
  // 跨平台杀掉浏览器进程及衍生子进程
  try {
    const { spawnSync } = await import('node:child_process');
    if (process.platform === 'win32') {
      spawnSync('taskkill', ['/PID', String(state.proc.pid), '/T', '/F'], { stdio: 'ignore', windowsHide: true });
    } else {
      spawnSync('kill', ['-9', String(state.proc.pid)], { stdio: 'ignore' });
    }
  } catch {}
  try { state.proc.kill(); } catch {}
}

export function browserRunning() {
  return Boolean(browserState);
}

// 用浏览器打开一个页面并取回 DOM。串行（一个 page，一次一个引擎）。
async function browserHtml(url, { timeoutMs = 25000, exe } = {}) {
  if (!hostAllowed(url)) throw new Error(`域名不在白名单：${hostOf(url)}`);
  const state = await ensureBrowser({ timeoutMs, exe });
  await state.send('Page.enable');
  const loaded = new Promise((resolve) => {
    const timer = setTimeout(() => resolve(false), Math.min(timeoutMs, 20000));
    const onMessage = (event) => {
      let msg;
      try { msg = JSON.parse(String(event.data)); } catch { return; }
      if (msg?.method === 'Page.loadEventFired') { clearTimeout(timer); resolve(true); }
    };
    state.ws.addEventListener('message', onMessage);
    setTimeout(() => state.ws.removeEventListener('message', onMessage), Math.min(timeoutMs, 20000) + 500);
  });
  const nav = await state.send('Page.navigate', { url });
  if (nav?.errorText) throw new Error(`打开页面失败：${nav.errorText}`);
  await loaded;
  // 站点多半是 JS 渲染，等一小会儿再取 DOM
  await sleep(1200);
  const result = await state.send('Runtime.evaluate', {
    expression: 'document.documentElement ? document.documentElement.outerHTML : ""',
    returnByValue: true
  });
  return String(result?.result?.value ?? '');
}

// ── 临时公网图床（只在配置里打开时才用）────────────────────────────────────
//
// 为什么需要：必应/谷歌/ Яндекс 的以图搜图只吃「公网能访问的图片地址」，
// QQ 的图片是带 rkey 的内网链接，传不上去。所以要做真人照片这一块，
// 只能先把图放一个几分钟后失效的临时地址上。**默认关闭**，由用户在 config.json 里开。
const PUBLIC_HOST_PROVIDERS = {
  // litterbox = catbox 的临时版，自带过期时间（默认 1 小时），是这台机器上唯一通的图床。
  // 实测：0x0.st / telegra.ph / tmpfiles 连不上（CONNECT_TIMEOUT / ECONNRESET），
  // catbox 长期版 TLS 被掐，只有 litterbox 能传。
  litterbox: {
    url: 'https://litterbox.catbox.moe/resources/internals/api.php',
    build(bytes, mimeType, filename, ttl) {
      const form = new FormData();
      form.append('reqtype', 'fileupload');
      form.append('time', String(ttl || '1h'));
      form.append('fileToUpload', new Blob([bytes], { type: mimeType || 'image/jpeg' }), filename);
      return { form, headers: { Accept: 'text/plain' } };
    }
  }
};

/** 把图片传到临时图床，返回公网 URL。失败抛错（调用方决定是否降级）。 */
export async function uploadPublicImage(bytes, mimeType, { provider = 'litterbox', timeoutMs = 30000, filename = 'lens-search.jpg', ttl = '1h' } = {}) {
  const spec = PUBLIC_HOST_PROVIDERS[provider] ?? PUBLIC_HOST_PROVIDERS.litterbox;
  const { form, headers } = spec.build(bytes, mimeType, filename, ttl);
  const response = await fetch(spec.url, {
    method: 'POST',
    body: form,
    headers: { 'User-Agent': BROWSER_UA, ...headers },
    signal: AbortSignal.timeout(timeoutMs)
  });
  const text = (await response.text()).trim();
  if (!response.ok) throw new Error(`图床 ${provider} HTTP ${response.status}`);
  const url = (text.match(/https?:\/\/\S+/) ?? [])[0] ?? '';
  if (!/^https?:\/\//.test(url)) throw new Error(`图床 ${provider} 没返回地址：${trimText(text, 80)}`);
  return url;
}

// ── 各引擎适配器 ──────────────────────────────────────────────────────────

/** 打开一个页面并执行一段 JS 取回结果（探针用：看站点结构、找选择器）。 */
export async function browserProbe(url, expression, { timeoutMs = 30000, settleMs = 2000, exe } = {}) {
  if (!hostAllowed(url)) throw new Error(`域名不在白名单：${hostOf(url)}`);
  const state = await ensureBrowser({ timeoutMs, exe });
  await state.send('Page.enable');
  const loaded = new Promise((resolve) => {
    const timer = setTimeout(() => resolve(false), Math.min(timeoutMs, 25000));
    const onMessage = (event) => {
      let msg;
      try { msg = JSON.parse(String(event.data)); } catch { return; }
      if (msg?.method === 'Page.loadEventFired') { clearTimeout(timer); resolve(true); }
    };
    state.ws.addEventListener('message', onMessage);
    setTimeout(() => state.ws.removeEventListener('message', onMessage), Math.min(timeoutMs, 25000) + 500);
  });
  const nav = await state.send('Page.navigate', { url });
  if (nav?.errorText) throw new Error(`打开页面失败：${nav.errorText}`);
  await loaded;
  await sleep(settleMs);
  const result = await state.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  return result?.result?.value;
}

/**
 * 用真浏览器打开一个页面、把本地图片塞进 <input type=file>，再等结果页落地取 DOM。
 * 有些站（百度识图这类）只认「页面上真选了一个文件」，用 fetch 拼 multipart 会被判据非法
 * （graph.baidu.com 一律回 `{"status":1002,"msg":"Params illegal"}`），所以必须走这条路。
 */
export async function browserFileUploadHtml({ startUrl, filePath, fileSelector = 'input[type=file]', timeoutMs = 30000, settleMs = 4000, prepareExpression = '', submitExpression = '', waitForExpression = '', extractExpression = '', exe } = {}) {
  if (!hostAllowed(startUrl)) throw new Error(`域名不在白名单：${hostOf(startUrl)}`);
  if (!filePath || !fs.existsSync(filePath)) throw new Error('上传用的临时图片不存在');
  const state = await ensureBrowser({ timeoutMs, exe });
  await state.send('Page.enable');
  await state.send('DOM.enable');
  try {
    await state.send('Page.addScriptToEvaluateOnNewDocument', {
      source: `
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        window.chrome = { runtime: {}, loadTimes: function() {}, csi: function() {}, app: {} };
        if (!window.Notification) window.Notification = { permission: 'default' };
      `
    });
  } catch {}
  const loaded = new Promise((resolve) => {
    const timer = setTimeout(() => resolve(false), Math.min(timeoutMs, 25000));
    const onMessage = (event) => {
      let msg;
      try { msg = JSON.parse(String(event.data)); } catch { return; }
      if (msg?.method === 'Page.loadEventFired') { clearTimeout(timer); resolve(true); }
    };
    state.ws.addEventListener('message', onMessage);
    setTimeout(() => state.ws.removeEventListener('message', onMessage), Math.min(timeoutMs, 25000) + 500);
  });
  const nav = await state.send('Page.navigate', { url: startUrl });
  if (nav?.errorText) throw new Error(`打开页面失败：${nav.errorText}`);
  await loaded;
  // 有些站点（谷歌 Lens 的 v3/upload）没有页面上的上传入口，得自己塞一个 form：
  // 用 prepareExpression 在页面里造出 <input type=file>，再走同一条「真选文件」的路。
  if (prepareExpression) {
    try { await state.send('Runtime.evaluate', { expression: prepareExpression, returnByValue: true, awaitPromise: true }); } catch {}
    await sleep(300);
  }
  const nodeIdByObject = async () => {
    try {
      const evaluated = await state.send('Runtime.evaluate', { expression: `document.querySelector(${JSON.stringify(fileSelector)})` });
      const objectId = evaluated?.result?.objectId;
      if (!objectId) return 0;
      const node = await state.send('DOM.requestNode', { objectId });
      return Number(node?.nodeId) || 0;
    } catch { return 0; }
  };

  // 等 input 出现（JS 渲染的站点要等）
  const deadline = Date.now() + Math.min(timeoutMs, 20000);
  let nodeId = 0;
  while (Date.now() < deadline) {
    if (prepareExpression) {
      nodeId = await nodeIdByObject();
      if (nodeId) break;
    }
    const doc = await state.send('DOM.getDocument', { depth: 2, pierce: false });
    const found = await state.send('DOM.querySelector', { nodeId: doc.root.nodeId, selector: fileSelector });
    if (found?.nodeId) { nodeId = found.nodeId; break; }
    await sleep(400);
  }
  if (!nodeId) throw new Error(`页面上找不到 ${fileSelector}（站点结构变了或需要交互）`);
  // 记下当前 URL：上传成功后通常会发生跳转，用「URL 变了」当第一条信号。
  const beforeUrl = String((await state.send('Runtime.evaluate', { expression: 'location.href', returnByValue: true }))?.result?.value ?? '');
  await state.send('DOM.setFileInputFiles', { files: [filePath], nodeId });
  if (submitExpression) {
    try { await state.send('Runtime.evaluate', { expression: submitExpression, returnByValue: true }); } catch {}
  }
  // 等结果：优先等 waitForExpression 变真；否则等一次 navigation/load 再 settle。
  if (waitForExpression) {
    const waitDeadline = Date.now() + Math.min(timeoutMs, 30000);
    while (Date.now() < waitDeadline) {
      try {
        const probe = await state.send('Runtime.evaluate', { expression: waitForExpression, returnByValue: true });
        if (probe?.result?.value) break;
      } catch { /* 跳转中的一瞬间页面上下文会消失，忽略继续等 */ }
      await sleep(500);
    }
    // 条件满足只代表「壳子在了」，结果卡片是异步渲染的，再给一段固定渲染时间
    await sleep(settleMs);
  } else {
    await new Promise((resolve) => {
      const timer = setTimeout(resolve, Math.min(timeoutMs, 25000));
      const onMessage = (event) => {
        let msg;
        try { msg = JSON.parse(String(event.data)); } catch { return; }
        if (msg?.method !== 'Page.loadEventFired') return;
        clearTimeout(timer);
        state.ws.removeEventListener('message', onMessage);
        setTimeout(resolve, settleMs);
      };
      state.ws.addEventListener('message', onMessage);
    });
    // 页面没跳转（纯 JS 上传）也要给渲染时间
    const afterUrl = String((await state.send('Runtime.evaluate', { expression: 'location.href', returnByValue: true }))?.result?.value ?? '');
    if (afterUrl === beforeUrl) await sleep(settleMs);
  }
  const result = await state.send('Runtime.evaluate', {
    expression: 'document.documentElement ? document.documentElement.outerHTML : ""',
    returnByValue: true
  });
  const html = String(result?.result?.value ?? '');
  const url = String((await state.send('Runtime.evaluate', { expression: 'location.href', returnByValue: true }))?.result?.value ?? '');
  if (extractExpression) {
    const extracted = await state.send('Runtime.evaluate', { expression: extractExpression, returnByValue: true, awaitPromise: true });
    return { html, url, data: extracted?.result?.value };
  }
  return { html, url };
}

/**
 * 不带文件地打开一个页面、等它渲染完、把结果交回来。
 * Lens 的「完全匹配」标签页就是在同一个结果页上换 udm 参数，所以需要这个轻量版本。
 */
export async function browserVisit({ url, waitForExpression = '', settleMs = 2200, extractExpression = '', timeoutMs = 30000, exe } = {}) {
  if (!hostAllowed(url)) throw new Error(`域名不在白名单：${hostOf(url)}`);
  const state = await ensureBrowser({ timeoutMs, exe });
  await state.send('Page.enable');
  const nav = await state.send('Page.navigate', { url });
  if (nav?.errorText) throw new Error(`打开页面失败：${nav.errorText}`);
  const condition = waitForExpression || 'document.readyState === "complete"';
  const deadline = Date.now() + Math.min(timeoutMs, 30000);
  while (Date.now() < deadline) {
    try {
      const probe = await state.send('Runtime.evaluate', { expression: condition, returnByValue: true });
      if (probe?.result?.value) break;
    } catch { /* 跳转中的一瞬间页面上下文会消失，忽略继续等 */ }
    await sleep(400);
  }
  await sleep(settleMs);
  const html = String((await state.send('Runtime.evaluate', {
    expression: 'document.documentElement ? document.documentElement.outerHTML : ""',
    returnByValue: true
  }))?.result?.value ?? '');
  const finalUrl = String((await state.send('Runtime.evaluate', { expression: 'location.href', returnByValue: true }))?.result?.value ?? '');
  if (!extractExpression) return { html, url: finalUrl };
  const extracted = await state.send('Runtime.evaluate', { expression: extractExpression, returnByValue: true, awaitPromise: true });
  return { html, url: finalUrl, data: extracted?.result?.value };
}

// ── Google Lens ───────────────────────────────────────────────────────────
// 移植自 koishi-plugin-imgsearch-coser（WhiteBr1ck）的核心思路：找 coser 最准的一条路是
// Google Lens 反查图片，结果里往往直接是原帖（x.com/xxx/status/…）。
// 它没有公开 JSON 接口，只有 lens.google.com/v3/upload 这个「POST 图片 → 302 到结果页」的网页接口。
// fetch 会踩 CORS，所以这里用真浏览器在页面里造一个 form 去 POST：浏览器天然走系统代理（魔法在线时
// 才通），也天然带着谷歌自己的 cookie。
export const LENS_EXTRACT = `(() => {
  const isGoogle = (host) => /(^|\\.)google\\.[a-z.]+$/i.test(host);
  const isAsset = (host) => /(^|\\.)(gstatic|googleusercontent|googleapis|googletagmanager|google-analytics|doubleclick|adtrafficquality)\\./i.test(host);
  const cleanTitle = (node) => {
    const heading = node.querySelector('h1,h2,h3,[role=heading]');
    const text = String(
      (heading && heading.textContent) ||
      node.getAttribute('aria-label') ||
      node.textContent || ''
    ).replace(/\\s+/g, ' ').trim();
    return text.slice(0, 200);
  };
  const rows = [];
  const cards = [];
  const seen = new Set();
  for (const a of document.querySelectorAll('a[href]')) {
    if (a.closest('header, footer, nav, [role=navigation]')) continue;
    const raw = a.getAttribute('href') || '';
    let u;
    try { u = new URL(raw, location.href); } catch (e) { continue; }
    if (u.protocol !== 'https:') continue;
    const title = cleanTitle(a);
    if (!title) continue;
    // 谷歌视觉搜索的结果卡片全是 /goto?url=<不透明 token>：真实域名只有浏览器自己知道，
    // 交给外面用 CDP 请求拦截去解（页面里 fetch 会吃 CORS）。
    if (isGoogle(u.hostname) && u.pathname === '/goto' && u.searchParams.get('url')) {
      if (cards.length < 24) cards.push({ wrapper: u.href, title });
      continue;
    }
    if (isGoogle(u.hostname) || isAsset(u.hostname)) {
      const wrapped = u.searchParams.get('url') || u.searchParams.get('q') || '';
      if (!/^https?:\\/\\//.test(wrapped) || seen.has(wrapped)) continue;
      seen.add(wrapped);
      rows.push({ url: wrapped, title });
      continue;
    }
    if (seen.has(u.href)) continue;
    seen.add(u.href);
    rows.push({ url: u.href, title });
  }
  const bodyText = document.body ? document.body.innerText.slice(0, 4000) : '';
  return JSON.stringify({
    url: location.href,
    count: rows.length,
    cards: cards,
    results: rows,
    captcha: /unusual traffic|our systems have detected/i.test(bodyText) || /\\/sorry\\//.test(location.href),
    empty: /No matches|No results|找不到相符|没有找到|未找到/i.test(bodyText)
  });
})()`;

/**
 * 把 google 的 `/goto?url=<token>` 卡片解成真实域名。
 * 页面里 fetch 会被 CORS 挡死（跨域 302 → TypeError），所以让浏览器自己跳：
 * 开 Fetch 域拦请求，谷歌自己的请求放行，一旦出现非谷歌域名就记下来并中止加载 —— 不真的把目标页拉下来。
 */
async function resolveLensGoto(state, wrapperUrl, { timeoutMs = 2000 } = {}) {
  const isGoogleHost = (url) => {
    try { return /(^|\.)google\.[a-z.]+$/i.test(new URL(url).hostname); } catch { return true; }
  };
  try { await state.send('Fetch.enable', { patterns: [{ urlPattern: '*', requestStage: 'Request' }] }); } catch { return ''; }
  const hit = new Promise((resolve) => {
    const timer = setTimeout(() => resolve(''), timeoutMs);
    const onMessage = (event) => {
      let msg;
      try { msg = JSON.parse(String(event.data)); } catch { return; }
      if (msg?.method !== 'Fetch.requestPaused') return;
      const requestId = msg.params?.requestId;
      const url = String(msg.params?.request?.url ?? '');
      if (!requestId) return;
      if (isGoogleHost(url)) {
        state.send('Fetch.continueRequest', { requestId }).catch(() => {});
        return;
      }
      clearTimeout(timer);
      state.ws.removeEventListener('message', onMessage);
      state.send('Fetch.failRequest', { requestId, errorReason: 'Aborted' }).catch(() => {});
      resolve(url);
    };
    state.ws.addEventListener('message', onMessage);
    setTimeout(() => state.ws.removeEventListener('message', onMessage), timeoutMs + 500);
  });
  try { await state.send('Page.navigate', { url: wrapperUrl }); } catch {}
  const found = await hit;
  try { await state.send('Page.stopLoading'); } catch {}
  try { await state.send('Fetch.disable'); } catch {}
  return found;
}

// 只有这几类卡片值得多花时间解域名：真人 coser 的号基本只在社交平台上。
const LENS_SOCIAL_RE = /^(x|twitter|推特|instagram|ig|ins|微博|weibo|bilibili|哔哩|tiktok|抖音|facebook|fb|threads|xiaohongshu|小红书)/i;
// 已经解出真实域名时用它判断「这条是不是社交站点」，比看标题更可靠
const LENS_SOCIAL_HOST_RE = /^https?:\/\/(?:www\.|m\.)?(?:x|twitter|instagram|weibo|bilibili|tiktok|facebook|threads|xiaohongshu)\.(?:com|net)\//i;

export async function googleLensSearch(bytes, mimeType, { hl = 'zh-CN', timeoutMs = 45000, exe, tempDir, debug = false, exactPass = true } = {}) {
  if (!bytes || !bytes.length) throw new Error('没有图片');
  const dir = tempDir || os.tmpdir();
  const ext = /png/i.test(String(mimeType ?? '')) ? 'png' : 'jpg';
  const file = path.join(dir, `lens-tmp-${Date.now()}-${Math.random().toString(16).slice(2, 8)}.${ext}`);
  fs.writeFileSync(file, bytes);
  const prepare = [
    '(function () {',
    "  if (document.getElementById('lensForm')) return 'exists';",
    "  var form = document.createElement('form');",
    "  form.id = 'lensForm'; form.method = 'POST'; form.enctype = 'multipart/form-data';",
    "  form.action = 'https://lens.google.com/v3/upload?hl=" + hl + "';",
    "  form.target = '_self'; form.style.display = 'none';",
    "  var picker = document.createElement('input');",
    "  picker.type = 'file'; picker.name = 'encoded_image'; picker.id = 'lensFile';",
    '  form.appendChild(picker);',
    "  var marker = document.createElement('input');",
    "  marker.type = 'hidden'; marker.name = 'image_content'; marker.value = '';",
    '  form.appendChild(marker);',
    '  document.body.appendChild(form);',
    "  return 'ok';",
    '})()'
  ].join('\n');
  try {
    const out = await browserFileUploadHtml({
      startUrl: 'https://www.google.com/',
      filePath: file,
      fileSelector: '#lensFile',
      prepareExpression: prepare,
      submitExpression: "document.getElementById('lensForm').submit()",
      // 跳转到结果页之后还有一段 JS 渲染：只看 URL 会抓到一张空壳，必须等结果卡片真落地
      waitForExpression: 'document.body && ((document.body.innerText.length > 300 && document.querySelectorAll("a[href]").length > 15) || /unusual traffic|our systems have detected/i.test(document.body.innerText) || /\\/sorry\\//.test(location.href) || /\\/search\\?/.test(location.href))',
      extractExpression: LENS_EXTRACT,
      settleMs: 2500,
      timeoutMs: Math.max(timeoutMs, 30000),
      exe
    });
    let page = out?.data;
    if (typeof page === 'string') {
      try { page = JSON.parse(page); } catch { page = {}; }
    }
    page = page && typeof page === 'object' ? page : {};
    if (page.captcha) throw new Error('GOOGLE_CAPTCHA：谷歌要求验证，稍后再试');
    const state = await ensureBrowser({ timeoutMs: Math.max(timeoutMs, 30000), exe });
    // 一页结果分两段解析：先拿结果卡片，再逐条解出 /goto?url= 背后的真实域名。
    const collectFrom = async (parsed) => {
      const out2 = { rows: Array.isArray(parsed?.results) ? parsed.results.slice() : [], cards: Array.isArray(parsed?.cards) ? parsed.cards : [] };
      if (!out2.cards.length) return out2.rows;
      // 社交卡片优先解：它们最可能就是原帖/作者；解够 6 条就停，别把时间花在文章页上
      const social = out2.cards.filter((card) => LENS_SOCIAL_RE.test(String(card.title ?? '')));
      const queue = social.slice(0, 2).concat(out2.cards.filter((card) => !LENS_SOCIAL_RE.test(String(card.title ?? '')))).slice(0, 2);
      for (const card of queue) {
        const target = await resolveLensGoto(state, String(card.wrapper ?? ''), { timeoutMs: 2000 });
        if (!target) continue;
        if (out2.rows.some((row) => String(row?.url ?? '') === target)) continue;
        const cardTitle = String(card.title ?? '').slice(0, 200);
        out2.rows.push({ url: target, title: cardTitle, authorName: socialNameFromTitle(cardTitle) });
      }
      return out2.rows;
    };
    const visualRows = await collectFrom(page);
    const looksSocial = (list) => list.some((row) => LENS_SOCIAL_RE.test(String(row?.title ?? '')) || LENS_SOCIAL_HOST_RE.test(String(row?.url ?? '')));
    // 「完全匹配」= 同一张图在网上的原出处，通常直接就是原帖；外观相似则只是长得像。
    // 外观那页已经捞到社交账号就不再跑第二趟（省 5 秒），否则补一趟。
    let exactRows = [];
    if (exactPass !== false && !visualRows.length) {
      const exactUrl = (() => {
        try {
          const u = new URL(String(out?.url ?? ''));
          if (!/^https:\/\/www\.google\.[a-z.]+\/search/i.test(u.href)) return '';
          u.searchParams.set('udm', '48');
          return u.href;
        } catch { return ''; }
      })();
      if (exactUrl) {
        try {
          const visit = await browserVisit({
            url: exactUrl,
            waitForExpression: 'document.body && document.querySelectorAll("a[href]").length > 20',
            extractExpression: LENS_EXTRACT,
            settleMs: 2200,
            timeoutMs: Math.max(timeoutMs, 30000),
            exe
          });
          let exactPage = visit?.data;
          if (typeof exactPage === 'string') {
            try { exactPage = JSON.parse(exactPage); } catch { exactPage = {}; }
          }
          if (exactPage && !exactPage.captcha) {
            exactRows = (await collectFrom(exactPage)).map((row) => ({ ...row, exact: true }));
          }
        } catch { /* 完全匹配这趟失败不影响主结果，视觉结果已经在手上 */ }
      }
    }
    const rows = exactRows.concat(visualRows);
    const mapped = rows
      .filter((row) => row && typeof row.url === 'string')
      .map((row) => ({ url: row.url, title: String(row.title ?? '').slice(0, 200), similarity: null, sourceUrl: row.url }));
    return debug ? { rows: mapped, page, exactCount: exactRows.length, finalUrl: out?.url ?? '' } : mapped;
  } catch (error) {
    const message = String(error?.message ?? '');
    if (/ERR_CONNECTION|ERR_NAME_NOT_RESOLVED|ERR_TUNNEL|ERR_PROXY|ERR_TIMED_OUT/i.test(message)) {
      throw new Error('GOOGLE_UNREACHABLE：谷歌连不上（猫猫云没开或系统代理没开）');
    }
    throw error;
  } finally {
    try { fs.rmSync(file, { force: true }); } catch {}
  }
}

// SauceNAO：multipart POST，无 key 也能出结果；连续调用会被 403 限流。
async function saucenaoSearch(bytes, mimeType, { timeoutMs, onLog } = {}) {
  const form = new FormData();
  form.append('file', new Blob([bytes], { type: mimeType || 'image/png' }), 'image.' + (mimeType === 'image/jpeg' ? 'jpg' : 'png'));
  form.append('db', '999');
  form.append('output_type', '0');
  const url = 'https://saucenao.com/search.php';
  await validateFetchUrl(url);
  const response = await fetch(url, {
    method: 'POST',
    body: form,
    redirect: 'follow',
    headers: { 'User-Agent': BROWSER_UA, Accept: 'text/html,application/xhtml+xml' },
    signal: AbortSignal.timeout(timeoutMs)
  });
  if (response.status === 403) {
    const error = new Error('SauceNAO 限流（403），至少等 60 秒再试');
    error.code = 'RATE_LIMITED';
    throw error;
  }
  if (!response.ok) throw new Error(`SauceNAO HTTP ${response.status}`);
  const html = await response.text();
  return parseSaucenao(html);
}

export function parseSaucenao(html) {
  const text = String(html ?? '');
  const blocks = text.split(/<div class="result\b/).slice(1);
  if (!blocks.length) {
    // 有些版本用 <div id="res<index>" class="result">，退一步按 similarity 直接抓
    const fallback = [];
    const re = /resultsimilarityinfo[^>]*>\s*([\d.]+)%/g;
    let m;
    while ((m = re.exec(text))) fallback.push({ similarity: Number(m[1]) / 100 });
    return fallback;
  }
  const candidates = [];
  for (const block of blocks) {
    const simMatch = block.match(/resultsimilarityinfo[^>]*>\s*([\d.]+)%/)
      || block.match(/similarity-info[^>]*>[\s\S]{0,120}?([\d.]+)%/)
      || block.match(/([\d.]+)%/);
    const similarity = simMatch ? Number(simMatch[1]) / 100 : null;

    const titleMatch = block.match(/class="resulttitle"[\s\S]{0,400}?<strong[^>]*>([\s\S]*?)<\/strong>/i)
      || block.match(/class="resulttitle"[\s\S]{0,200}?>\s*([^<]{2,200})</i);
    const title = titleMatch ? stripTags(titleMatch[1]) : '';

    // 结果里所有外链：第一个一般就是图源
    const links = [];
    const hrefRe = /href="([^"]+)"/g;
    let hm;
    while ((hm = hrefRe.exec(block))) {
      const href = absUrl(hm[1], 'https://saucenao.com/');
      if (!href) continue;
      const host = hostOf(href);
      if (!host || host.endsWith('saucenao.com')) continue;
      if (!links.includes(href)) links.push(href);
    }

    // 作者行：SauceNAO 实际写的是 `Member: <a href=...>作者名</a>`（pixiv 老格式 member.php?id=），
    // 也有 `Author:` 的写法 —— 两种都认，抓错了顶多是空，不会误认。
    const authorMatch = block.match(/(?:Member|Author)[\s\S]{0,240}?<a\b[^>]*href="([^"]+)"[^>]*>([\s\S]*?)<\/a>/i)
      || block.match(/author[^>]*>[\s\S]{0,200}?href="([^"]+)"/i);
    const authorUrl = authorMatch ? absUrl(authorMatch[1], 'https://saucenao.com/') : '';
    // 作者名（如 `豊栄@ﾄﾞﾔｧ…`）：拿它去搜推特比拿作品标题搜准得多。
    const authorName = authorMatch && authorMatch[2] ? trimText(stripTags(authorMatch[2]), 40) : '';

    const snippet = trimText(stripTags(block), 200);
    if (!links.length && !title) continue;
    candidates.push({
      engine: 'saucenao',
      similarity,
      title,
      sourceUrl: links[0] ?? '',
      authorUrl,
      authorName,
      host: hostOf(links[0] ?? authorUrl),
      snippet,
      links
    });
  }
  return candidates;
}

// ── IQDB：multipart POST，动漫图库（danbooru / konachan / yande.re）─────────
export function parseIqdb(html) {
  const text = String(html ?? '');
  if (/Place in queue|under high load/i.test(text)) {
    const error = new Error('IQDB 在排队（站点高负载），过一会儿再试');
    error.code = 'QUEUED';
    throw error;
  }
  if (/No relevant matches/i.test(text)) return [];
  const links = [];
  const re = /<a\b[^>]*href="([^"]+)"[^>]*>([\s\S]*?)<\/a>/gi;
  let m;
  while ((m = re.exec(text))) {
    const url = absUrl(String(m[1]).replace(/^\/\//, 'https://'), 'https://iqdb.org/');
    if (!url) continue;
    const host = hostOf(url);
    if (!host || host.endsWith('iqdb.org')) continue;
    if (/\.(?:css|js|ico|png|jpe?g|gif|svg)(?:\?|$)/i.test(url)) continue;
    if (links.some((item) => item.url === url)) continue;
    links.push({ url, host, title: trimText(stripTags(m[2]), 100) });
  }
  const sim = text.match(/(\d{1,3})%\s*similarity/i);
  const similarity = sim ? Number(sim[1]) / 100 : null;
  return links.slice(0, 12).map((item) => ({
    engine: 'iqdb',
    similarity,
    title: item.title,
    sourceUrl: item.url,
    authorUrl: '',
    host: item.host,
    snippet: '',
    links: [item.url]
  }));
}

async function iqdbSearch(bytes, mimeType, { timeoutMs, onLog } = {}) {
  const form = new FormData();
  form.append('file', new Blob([bytes], { type: mimeType || 'image/png' }), 'image.' + (mimeType === 'image/jpeg' ? 'jpg' : 'png'));
  for (const n of [1, 2, 3, 4, 5, 6]) form.append('service[]', String(n));
  const url = 'https://iqdb.org/';
  await validateFetchUrl(url);
  const response = await fetch(url, {
    method: 'POST',
    body: form,
    redirect: 'follow',
    headers: { 'User-Agent': BROWSER_UA, Accept: 'text/html' },
    signal: AbortSignal.timeout(Math.max(timeoutMs, 35000))
  });
  if (!response.ok) throw new Error(`IQDB HTTP ${response.status}`);
  return parseIqdb(await response.text());
}

// ── trace.moe：动画截图反查（给的是番剧/集数，不是社媒账号）────────────────
export function parseTracemoe(payload) {
  const list = Array.isArray(payload?.result) ? payload.result : [];
  const out = [];
  const seen = new Set();
  for (const item of list.slice(0, 10)) {
    // 0.87 以下基本是「随便一个番的某帧」，真命中一般 0.9 以上 —— 低于门槛的宁可不要，
    // 否则每次都会往结果里塞十条无关番剧。
    const similarity = Number.isFinite(item?.similarity) ? item.similarity : 0;
    if (similarity < 0.87) continue;
    const anilistId = item?.anilist?.id ?? item?.anilist?.anime_id ?? null;
    const title = item?.anilist?.title?.native || item?.anilist?.title?.romaji || item?.anilist?.title?.english || item?.filename || '';
    const sourceUrl = anilistId ? `https://anilist.co/anime/${anilistId}` : '';
    if (!sourceUrl || seen.has(sourceUrl)) continue;
    seen.add(sourceUrl);
    const episode = Number.isFinite(item?.episode) ? ` 第${item.episode}集` : '';
    out.push({
      engine: 'tracemoe',
      similarity,
      title: trimText(`${title}${episode}`, 120),
      sourceUrl,
      authorUrl: '',
      host: 'anilist.co',
      snippet: trimText(String(item?.filename ?? ''), 120),
      links: [sourceUrl]
    });
    if (out.length >= 3) break;
  }
  return out;
}

async function tracemoeSearch(bytes, mimeType, { timeoutMs } = {}) {
  const form = new FormData();
  form.append('image', new Blob([bytes], { type: mimeType || 'image/png' }), 'image.' + (mimeType === 'image/jpeg' ? 'jpg' : 'png'));
  const url = 'https://api.trace.moe/search?anilistInfo';
  await validateFetchUrl(url);
  const response = await fetch(url, {
    method: 'POST',
    body: form,
    headers: { 'User-Agent': BROWSER_UA, Accept: 'application/json' },
    signal: AbortSignal.timeout(timeoutMs)
  });
  if (!response.ok) throw new Error(`trace.moe HTTP ${response.status}`);
  return parseTracemoe(await response.json());
}

// ── 百度识图（真浏览器上传）：结果是「相似图」，噪声大，只留账号主页形态的链接 ──
export function parseBaiduGraph(html) {
  const links = collectExternalLinks(html, {
    base: 'https://graph.baidu.com/',
    excludeHosts: ['baidu.com', 'bdstatic.com', 'baidupcs.com', 'bdimg.com', 'bdurl.net'],
    cap: 60
  });
  const seen = new Set();
  const out = [];
  for (const item of links) {
    const hit = matchPlatform(item.url);
    if (!hit) continue; // 文章页 / 图集页一律不要，只认账号主页形态
    const url = hit.url || item.url;
    if (seen.has(url)) continue;
    seen.add(url);
    out.push({
      engine: 'baidu',
      similarity: null,
      weak: true, // 相似图不一定同一个人，标记成弱证据
      title: item.title,
      sourceUrl: url,
      authorUrl: '',
      host: hostOf(url),
      snippet: '',
      links: [url]
    });
  }
  return out;
}

// 三家浏览器引擎的 DOM 都是「一堆外链卡片」，结构天天变，所以统一退到最稳的做法：
// 抓所有外链、去重、排除引擎自家域名，锚文本能取到就取（取不到不影响账号抽取）。
function collectExternalLinks(html, { base, excludeHosts = [], cap = 24 } = {}) {
  const text = String(html ?? '');
  const out = [];
  const seen = new Set();
  const anchorRe = /<a\b[^>]*?href="([^"]+)"[^>]*>([\s\S]*?)<\/a>/gi;
  const push = (href, label) => {
    const url = absUrl(href, base);
    const host = hostOf(url);
    if (!url || !host) return;
    if (excludeHosts.some((bad) => host === bad || host.endsWith('.' + bad))) return;
    if (seen.has(url)) return;
    seen.add(url);
    out.push({
      url,
      host,
      title: label ? trimText(stripTags(label), 120) : ''
    });
  };
  let m;
  while ((m = anchorRe.exec(text))) {
    push(m[1], m[2]);
    if (out.length >= cap * 3) break;
  }
  // 兜底：还有没被锚点包住的链接（JS 里拼的、property 里的）
  if (out.length < cap) {
    const hrefRe = /href="(https?:\/\/[^"]+)"/gi;
    while ((m = hrefRe.exec(text))) {
      push(m[1], '');
      if (out.length >= cap * 3) break;
    }
  }
  return out.slice(0, cap);
}

function linksToCandidates(engine, html, options) {
  return collectExternalLinks(html, options).map((item) => ({
    engine,
    similarity: null,
    title: item.title,
    sourceUrl: item.url,
    authorUrl: '',
    host: item.host,
    snippet: '',
    links: [item.url]
  }));
}

export function parseBingDom(html) {
  return linksToCandidates('bing', html, {
    base: 'https://www.bing.com/',
    excludeHosts: ['bing.com', 'microsoft.com', 'msn.com', 'microsofttranslator.com', 'live.com'],
    cap: 24
  });
}

export function parseYandexDom(html) {
  return linksToCandidates('yandex', html, {
    base: 'https://yandex.com/',
    excludeHosts: ['yandex.com', 'yandex.ru', 'yastatic.net', 'yandex.net'],
    cap: 24
  });
}

export function parseBaiduDom(html) {
  return linksToCandidates('baidu', html, {
    base: 'https://graph.baidu.com/',
    excludeHosts: ['baidu.com', 'bdstatic.com', 'baidupcs.com'],
    cap: 24
  });
}

// 浏览器引擎：把图片先传到一个「能收图」的临时宿主是不行的（要公网），
// 所以 Yandex/Bing/百度都只能靠「已上传到公网」的图片 URL —— 这里明确拒绝，
// 由调用方决定是否降级（当前实现：跳过并在 failures 里说明）。
async function browserEngineSearch(engine, bytes, mimeType, { timeoutMs, onLog, publicUrl }) {
  if (!publicUrl) {
    throw new Error(`${engine} 需要公网图片 URL（QQ 图片是内网 rkey，传不上去）`);
  }
  if (engine === 'bing') {
    const html = await browserHtml(`https://www.bing.com/images/search?q=${encodeURIComponent(`imgurl:${publicUrl}`)}&view=detailv2&iss=sbi`, { timeoutMs });
    return parseBingDom(html);
  }
  if (engine === 'yandex') {
    const html = await browserHtml(`https://yandex.com/images/search?rpt=imageview&url=${encodeURIComponent(publicUrl)}`, { timeoutMs });
    return parseYandexDom(html);
  }
  if (engine === 'baidu') {
    const html = await browserHtml(`https://graph.baidu.com/details?isfromtusoupc=1&tn=pc&carousel=0&image=${encodeURIComponent(publicUrl)}`, { timeoutMs });
    return parseBaiduDom(html);
  }
  if (engine === 'google') {
    const html = await browserHtml(`https://lens.google.com/uploadbyurl?url=${encodeURIComponent(publicUrl)}`, { timeoutMs });
    return parseBingDom(html); // Google Lens 的 DOM 结构本版不另写，能出外链就够
  }
  throw new Error(`未知引擎：${engine}`);
}

/**
 * 反查一张图。引擎选择由调用方从 engines config 读出后传进来。
 * 单个引擎失败不影响其它引擎；全失败返回 failures 说明原因。
 */
export async function reverseSearch(bytes, mimeType, { engines, timeoutMs = 25000, onLog, publicUrl, browserExe, tempDir, proxy = '' } = {}) {
  // 浏览器是单例、代理是启动参数：本次要走的通道先摆好（空串 = 直连）
  setBrowserProxy(proxy);
  const list = (Array.isArray(engines) && engines.length ? engines : ['saucenao'])
    .filter((id) => ENGINE_IDS.includes(id));
  const candidates = [];
  const failures = [];
  const enginesUsed = [];

  const runEngine = async (engine) => {
    if (engine === 'saucenao') return saucenaoSearch(bytes, mimeType, { timeoutMs, onLog });
    if (engine === 'iqdb') return iqdbSearch(bytes, mimeType, { timeoutMs, onLog });
    if (engine === 'tracemoe') return tracemoeSearch(bytes, mimeType, { timeoutMs, onLog });
    if (engine === 'lens') {
      return googleLensSearch(bytes, mimeType, { timeoutMs: Math.min(timeoutMs, 20000), exe: browserExe, tempDir });
    }
    if (engine === 'baidu') {
      const dir = tempDir || os.tmpdir();
      const file = path.join(dir, `lens-upload-${Date.now()}-${Math.random().toString(16).slice(2, 8)}.${mimeType === 'image/png' ? 'png' : 'jpg'}`);
      fs.writeFileSync(file, bytes);
      try {
        const { html } = await browserFileUploadHtml({
          startUrl: 'https://graph.baidu.com/pcpage/index?tpl_from=pc',
          filePath: file,
          fileSelector: 'input[type=file].general-upload-file',
          settleMs: 2500,
          timeoutMs: Math.max(timeoutMs, 30000),
          exe: browserExe,
          waitForExpression: '(() => (document.querySelectorAll(\'a[href^="http"]\').length > 12 && document.body.innerText.length > 600))()'
        });
        return parseBaiduGraph(html);
      } finally {
        try { fs.rmSync(file, { force: true }); } catch {}
      }
    }
    if (BROWSER_ENGINES.has(engine)) return browserEngineSearch(engine, bytes, mimeType, { timeoutMs, onLog, publicUrl });
    throw new Error('未实现的引擎');
  };

  const record = async (engine, task) => {
    const started = Date.now();
    try {
      const found = await task();
      enginesUsed.push(engine);
      if (Array.isArray(found) && found.length) {
        for (const item of found) candidates.push({ ...item, engine });
      } else {
        failures.push({ engine, reason: '空结果' });
      }
      if (onLog) onLog(`[Google Lens] ${engine} 完成 ${Date.now() - started}ms，结果 ${Array.isArray(found) ? found.length : 0} 条`);
    } catch (error) {
      const reason = String(error?.message ?? error);
      failures.push({ engine, reason });
      if (onLog) onLog(`[Google Lens] ${engine} 失败 ${Date.now() - started}ms：${reason}`);
    }
  };

  // 纯网络的三个引擎并发跑（互不影响），浏览器那台独占一个 page，必须串行。
  const NETWORK = new Set(['saucenao', 'iqdb', 'tracemoe']);
  const parallel = list.filter((engine) => NETWORK.has(engine));
  const serial = list.filter((engine) => !NETWORK.has(engine));
  await Promise.all(parallel.map((engine) => record(engine, () => runEngine(engine))));
  for (const engine of serial) {
    await record(engine, () => runEngine(engine));
    if (failures.some((item) => item.engine === engine && /RATE_LIMITED|403/i.test(item.reason))) await sleep(1200);
  }
  return { candidates, failures, enginesUsed };
}

// ── 账号抽取 ──────────────────────────────────────────────────────────────

const PLATFORM_RULES = [
  {
    platform: 'twitter',
    re: /^https?:\/\/(?:www\.|mobile\.|m\.)?(?:twitter|x)\.com\/(?:i\/status\/(\d+)|([A-Za-z0-9_]{2,20}))(?:\/|$|\?)/i,
    clean: (m) => {
      if (m[1]) {
        return {
          handle: '@status_' + m[1],
          handleKey: 'status_' + m[1],
          url: `https://x.com/i/status/${m[1]}`
        };
      }
      return {
        handle: '@' + m[2],
        handleKey: m[2].toLowerCase(),
        url: `https://x.com/${m[2]}`
      };
    }
  },
  {
    platform: 'weibo',
    re: /^https?:\/\/(?:www\.|m\.)?weibo\.(?:com|cn)\/(?:u\/|n\/)?(\d{6,}|[A-Za-z0-9_\-]{3,40})(?:\/|$|\?)/i,
    clean: (m) => ({ handle: m[1], handleKey: m[1].toLowerCase() })
  },
  {
    platform: 'bilibili',
    re: /^https?:\/\/(?:space\.bilibili\.com|www\.bilibili\.com\/space)\/(\d{3,})(?:\/|$|\?)/i,
    clean: (m) => ({ handle: m[1], handleKey: m[1] })
  },
  {
    platform: 'instagram',
    re: /^https?:\/\/(?:www\.)?instagram\.com\/([A-Za-z0-9_.]{2,30})\/?(?:\?|$)/i,
    clean: (m) => ({ handle: '@' + m[1], handleKey: m[1].toLowerCase() })
  },
  {
    platform: 'pixiv',
    // 两种真实形态：新站 /users/<id>，老站 /member.php?id=<id>（SauceNAO 的 Member 行就是后者）
    re: /^https?:\/\/(?:www\.)?pixiv\.net\/(?:(?:en\/)?users\/(\d{2,})|member\.php\?(?:[^#]*&)?id=(\d{2,}))/i,
    clean: (m) => {
      const id = m[1] ?? m[2];
      return { handle: id, handleKey: id, url: `https://www.pixiv.net/users/${id}` };
    }
  }
];

// bilibili 的图文/视频页里带作者 mid 时才算 direct
const BILIBILI_AUTHOR_RE = /\/(?:opus|video|read)\/.*?(?:mid=|space\.bilibili\.com\/)(\d{3,})/i;

// 同分时的平台顺序：微博 → B站 → Twitter → Instagram → Pixiv。
// 按「国内 coser 最可能留号的地方」排，回话里第 1 条就是最可能有用的那个。
// 真人 coser 的号绝大部分在推特，微博其次；Pixiv 是画作平台（画师的作品页），
// 不是「这个人自己的社交账号」，所以排在最后，回话里也要标出来。
const PLATFORM_WEIGHT = { twitter: 1, weibo: 2, bilibili: 3, instagram: 4, pixiv: 9 };

// 画作平台：pixiv 上的是画师的作品/会员号，不是 coser 的主页。
const ARTWORK_PLATFORMS = new Set(['pixiv']);

// 「看着像账号、其实是页面」的路径前缀 —— 百度识图/搜索结果里这类链接特别多，
// 不挡掉就会把 `weibo.com/ttarticle/p/show?id=…` 当成一个叫 ttarticle 的账号报出去。
const PATH_DENY = {
  weibo: ['ttarticle', 'p', 'show', 'status', 'detail', 'photo', 'video', 'article', 'fav', 'like', 'comment', 'search', 'hot', 'topic', 'tv', 'page', 's', 'weibo', 'login', 'signup', 'reg'],
  twitter: ['i', 'intent', 'share', 'home', 'search', 'hashtag', 'status', 'explore', 'notifications', 'messages', 'settings', 'login', 'signup', 'tos', 'privacy', 'account'],
  instagram: ['p', 'reel', 'reels', 'explore', 'accounts', 'stories', 'tv', 'about', 'legal', 'directory'],
  bilibili: ['video', 'read', 'opus', 'bangumi', 'search', 'account'],
  pixiv: ['artworks', 'i', 'en', 'tags', 'search', 'ranking', 'novel', 'ajax']
};

function matchPlatform(url) {
  for (const rule of PLATFORM_RULES) {
    const m = String(url ?? '').match(rule.re);
    if (!m) continue;
    const handle = String(m[2] || m[1] || '');
    const deny = PATH_DENY[rule.platform] ?? [];
    if (deny.includes(handle.toLowerCase())) continue;
    if (rule.platform === 'weibo') {
      // weibo.com/123456 这种纯数字才是 uid；weibo.com/abc 是昵称路径，也能用
      if (!/^\d+$/.test(handle) && !/^[A-Za-z0-9_\-]{3,}$/.test(handle)) continue;
    }
    if (rule.platform === 'instagram' && /^(p|reel|explore|accounts|stories)$/i.test(handle)) continue;
    if (rule.platform === 'twitter' && /^(i|intent|share|home|search)$/i.test(handle)) continue;
    const cleaned = rule.clean(m);
    // clean() 可以给出归一化后的 url（比如 pixiv 老站 member.php → /users/<id>）
    return { platform: rule.platform, ...cleaned, url: cleaned.url || String(url) };
  }
  return null;
}

/** 整条标题当人名的兜底太脏（会得到「阿抽崽on X: \"hi\" / X」这种），先过滤掉不像名字的。 */
export function looksLikePersonName(value) {
  const text = String(value ?? '').trim();
  if (text.length < 2 || text.length > 24) return false;
  if (/["':：/|]/.test(text)) return false;
  if (/\b(on|via|by)\s+(x|twitter|instagram|ig|weibo|bilibili|tiktok|facebook|threads)\b/i.test(text)) return false;
  return true;
}

/** 人名归一：小写、去空格与常见标点，用来做「这俩是不是同一串字」的粗比较。 */
export function normalizePersonName(value) {
  return String(value ?? '')
    .toLowerCase()
    .replace(/[\s\-_·・.,，。:：;；!！?？'"“”‘’()（）\[\]【】{}<>《》|/\\~—–]+/g, '');
}

/**
 * 找出「这一批结果主要在讲谁」：把候选里出现过的名字（作者行、社交卡片、主页标题）逐个拿去
 * 比对所有结果的标题，某个名字或它的前几个字命中最多条结果，就以它为主轴。
 * 只命中自己那一条的名字（hits 减掉自身后为 0）不算证据 —— 那就是搭便车的别人。
 */
export function dominantPersonName(candidates, { minHits = 1, minPrefix = 4 } = {}) {
  const list = Array.isArray(candidates) ? candidates : [];
  const titles = list
    .map((candidate) => normalizePersonName(`${candidate?.title ?? ''} ${candidate?.snippet ?? ''}`))
    .filter((text) => text.length >= minPrefix);
  if (!titles.length) return { name: '', prefix: '', hits: 0 };
  const names = new Map();
  const add = (raw) => {
    const key = normalizePersonName(raw);
    if (key.length < minPrefix || names.has(key)) return;
    names.set(key, String(raw ?? '').trim());
  };
  for (const candidate of list) {
    add(candidate?.authorName);
    add(profileTitleName(String(candidate?.title ?? '')).name);
    add(socialNameFromTitle(String(candidate?.title ?? '')));
    // 标题里写的名字（`CN : 阿薰kaOri`）也是证据：同一批结果里它出现在好几条标题上，
    // 就说明这张图讲的是这个人 —— 哪怕账号卡片是别人发的。
    add(nameFromTitleMention(String(candidate?.title ?? '')));
  }
  let best = { name: '', prefix: '', hits: 0 };
  // 短名先占位：同票时留「阿薰kaori」这种干净写法，而不是「阿薰kaOriCOSPlayerVN」。
  const keys = [...names.keys()].sort((a, b) => a.length - b.length);
  for (const key of keys) {
    // 从长到短试前缀：「阿薰kaori防盗版」整串只命中 1 条，砍到「阿薰kaori」就命中好几条
    for (let len = Math.min(key.length, 12); len >= minPrefix; len -= 1) {
      const head = key.slice(0, len);
      const hits = titles.filter((text) => text.includes(head)).length - 1;
      if (hits < minHits) continue;
      if (hits > best.hits) best = { name: names.get(key) ?? key, prefix: head, hits };
      break;
    }
  }
  return best;
}

/** 从候选结果里抽社媒账号。只认 URL 证据 —— 没有证据的 handle 一律不写。 */
export function extractAccounts(candidates, { max = 3, onDrop = null, strictNames = true } = {}) {
  const out = [];
  const seen = new Set();
  const list = Array.isArray(candidates) ? candidates : [];
  for (const candidate of list) {
    const authorHit = candidate?.authorUrl ? matchPlatform(candidate.authorUrl) : null;
    const authorKey = authorHit ? authorHit.platform + '|' + authorHit.handleKey : '';
    const urls = [];
    for (const value of [candidate?.authorUrl, candidate?.sourceUrl, candidate?.url, ...(candidate?.links ?? [])]) {
      if (value) urls.push(value);
    }
    // 标题/摘要里偶尔也带完整链接
    for (const text of [candidate?.title, candidate?.snippet]) {
      const found = String(text ?? '').match(/https?:\/\/[^\s"'<>）)]+/g);
      if (found) urls.push(...found);
    }
    for (const url of urls) {
      const hit = matchPlatform(url);
      if (!hit) continue;
      const dedupe = hit.platform + '|' + hit.handleKey;
      const profileName = profileTitleName(candidate?.title);
      const fallbackName = authorNameFromTitle(candidate?.title);
      const ownName =
        profileName.name ||
        socialNameFromTitle(candidate?.title) ||
        String(candidate?.authorName ?? '') ||
        (dedupe === authorKey || !looksLikePersonName(fallbackName) ? '' : fallbackName);
      if (seen.has(dedupe)) {
        // 同一个号被多个引擎撞见时，谁先到并不代表谁的标题更完整（扫描日期在前、作者在后很常见），
        // 所以后面再遇到带名字的就补上。
        const existing = out.find((item) => item.platform + '|' + String(item.handle ?? '').replace(/^@/, '').toLowerCase() === dedupe);
        if (existing && !existing.authorName && ownName) existing.authorName = ownName;
        continue;
      }
      seen.add(dedupe);
      out.push({
        platform: hit.platform,
        handle: hit.handle,
        url: hit.url,
        // 作者行带出来的名字（`Member: ... <a>名字</a>`）比作品标题更像「这个人叫什么」
        authorName: ownName,
        confidence: candidate.weak ? 'weak' : 'direct',
        evidence: {
          engine: candidate.engine ?? '',
          similarity: candidate.similarity ?? null,
          sourceUrl: candidate.sourceUrl ?? ''
        }
      });
    }
    // bilibili 图文页：从 sourceUrl 里挖 mid
    const bili = String(candidate?.sourceUrl ?? '').match(BILIBILI_AUTHOR_RE);
    if (bili) {
      const dedupe = 'bilibili|' + bili[1];
      if (!seen.has(dedupe)) {
        seen.add(dedupe);
        out.push({
          platform: 'bilibili',
          handle: bili[1],
          url: `https://space.bilibili.com/${bili[1]}`,
          confidence: candidate.weak ? 'weak' : 'direct',
          evidence: {
            engine: candidate.engine ?? '',
            similarity: candidate.similarity ?? null,
            sourceUrl: candidate.sourceUrl ?? ''
          }
        });
      }
    }
  }
  // 同一张图/同一条原帖只能对应一个作者：SauceNAO 常同时给出
  // `weibo.com/n/昵称` 与 `weibo.com/u/数字uid` —— 那是一个人，不能当成两个账号报出去。
  // 归一规则：按 platform + 原帖地址分组，组内只留「最正式」的那条 URL。
  const canonicalScore = (account) => {
    const url = String(account.url ?? '');
    if (/\/u\/\d{3,}/.test(url)) return 3;              // weibo.com/u/<uid>
    if (/space\.bilibili\.com\/\d+/.test(url)) return 3;
    if (/members?\.php\?|pixiv\.net\/users\/\d+/.test(url)) return 3;
    if (/\/(?:n|profile)\//.test(url)) return 1;        // weibo.com/n/<昵称>：会 302 到 uid
    return 2;
  };
  const bySource = new Map();
  const rank = (account) => (account.confidence === 'direct' ? 0 : account.confidence === 'weak' ? 1 : 2);
  for (const account of out) {
    // 没有原帖地址时退回自己的 url 分组：否则「同平台但没 sourceUrl」的两个人会被当成同一个人，
    // 只留下一个（真机上 Lens 的候选是带 sourceUrl 的，但其他引擎不一定）。
    const group = `${account.platform}|${account.evidence?.sourceUrl || account.url || ''}`;
    const prev = bySource.get(group);
    if (!prev) { bySource.set(group, account); continue; }
    if (rank(account) < rank(prev)) { bySource.set(group, account); continue; }
    if (rank(account) === rank(prev) && canonicalScore(account) > canonicalScore(prev)) bySource.set(group, account);
  }
  const deduped = [...new Set(bySource.values())];
  // 同一个 cos 角色常有好几个 coser 各拍一版，Lens 会把别人的原帖一起带回来（查「尤诺」时
  // 混进另一个 coser 的推文就是这种情况）。判断「谁是这张图的人」看出现次数：某个名字（或它
  // 的前几个字）在多条结果的标题里都出现，说明整批结果都在讲同一个人；只出现一次的就是搭便车。
  // 名字对不上的号一律不报 —— 宁可少报，也别误报为不相关的账号。
  const consensus = dominantPersonName(list);
  const artworkOnly = deduped.length > 0 && deduped.every((account) => ARTWORK_PLATFORMS.has(account.platform));
  const nameOf = (account) => normalizePersonName(account?.authorName);
  const namedMatch = consensus.prefix && !artworkOnly
    ? deduped.filter((account) => {
      const name = nameOf(account);
      if (!name) return false;
      return name.startsWith(consensus.prefix) || consensus.prefix.startsWith(name);
    })
    : [];
  // 只要认出了主轴，就只报「名字对得上」的号：对不上的、没名字的一律不报 ——
  // 报出去就是把别人的账号当成这个人（查尤诺那次报成 @Akane_ACZ 就是这么漏的）。
  // 主轴要求「同一串名字出现在 ≥2 条结果标题里」，所以单个候选的噪声名字不会触发这条。
  // strictNames=false 是给本人留的后门：有的作者压根不在标题里写名字，
  // 严格模式会变成「明明翻到了却报没查到」。关掉它就把所有号都报出来，
  // 由本人自己认。默认仍然是严格的那一套。
  const strictName = strictNames !== false && Boolean(consensus.prefix) && !artworkOnly;
  const keptList = strictName ? namedMatch : deduped;
  // 被「名字对不上主轴」挡掉的号要报给调用方：否则用户只看到「没查到」，
  // 不知道其实翻到了别人的帖子，只是没把它当成这个人。
  if (strictName && typeof onDrop === 'function') {
    for (const account of deduped) {
      if (namedMatch.includes(account)) continue;
      try {
        onDrop({ account, consensus });
      } catch {
        // 统计用的回调，出错也不能影响结果
      }
    }
  }

  // 排序：direct → weak（相似图）→ inferred；同级再按相似度降序、平台顺序
  keptList.sort((a, b) => {
    const ra = rank(a);
    const rb = rank(b);
    if (ra !== rb) return ra - rb;
    const sa = a.evidence?.similarity ?? -1;
    const sb = b.evidence?.similarity ?? -1;
    if (sb !== sa) return sb - sa;
    return (PLATFORM_WEIGHT[a.platform] ?? 9) - (PLATFORM_WEIGHT[b.platform] ?? 9);
  });
  return keptList.slice(0, Math.max(1, Number(max) || 3));
}

/** 画作平台的「相似画作」不等于图源：相似度不够的一律丢，别当 coser 的号报出去。 */
export function dropWeakArtwork(accounts, minSimilarity = 0.8) {
  const min = Number(minSimilarity);
  const limit = Number.isFinite(min) && min > 0 ? min : 0.8;
  const kept = [];
  let dropped = 0;
  for (const account of Array.isArray(accounts) ? accounts : []) {
    if (!ARTWORK_PLATFORMS.has(account?.platform)) { kept.push(account); continue; }
    const similarity = Number(account?.evidence?.similarity ?? 0);
    if (Number.isFinite(similarity) && similarity >= limit) kept.push(account);
    else dropped += 1;
  }
  return { accounts: kept, dropped };
}

function platformLabel(platform) {
  const name = ({ twitter: 'Twitter', weibo: '微博', bilibili: 'B站', instagram: 'Instagram', pixiv: 'Pixiv' })[platform] ?? platform;
  return ARTWORK_PLATFORMS.has(platform) ? `${name}（画作平台）` : name;
}

// ── inferred 账号（搜索交叉验证，最多 2 个） ──────────────────────────────
//
// 口径：**direct 优先且必须已有 direct**。只有「同一作品/作者名 + 同平台账号页」
// 在同一份搜索结果里同时出现时才采纳，否则丢弃 —— 宁缺毋滥，绝不凭名字猜 handle。

const INFER_PLATFORMS = ['twitter', 'weibo', 'bilibili'];
const INFER_QUERY_HINT = { weibo: '微博', twitter: 'Twitter', bilibili: 'B站' };

/** 从候选标题里剥出「像作者名」的片段（去掉【分组】【漫画】这类方括号内容）。 */
export function authorNameFromTitle(title) {
  const text = trimText(stripTags(String(title ?? '')), 120);
  if (!text) return '';
  const cleaned = text
    .replace(/【[^】]*】|\[[^\]]*\]|（[^）]*）|\([^)]*\)/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  const candidate = cleaned || text;
  return candidate.length >= 2 && candidate.length <= 24 ? candidate : '';
}

/**
 * 谷歌 Lens 的社交卡片标题长这样：`X吴二棒on X: "…"`、`Instagram 某coser on Instagram: 1/3`。
 * 作者名就是那个「on <站点>」前面的部分 —— 比从整段文案里猜准得多。
 */
/**
 * 从标题里挖 coser 名字。Lens 的脸书 / Coser吧 / 贴吧卡片常把名字直接写在标题里
 * （`CN : 阿薰kaOri`、`动漫博主阿薰kaOri NO.049`），那不是账号卡片，
 * 所以原来的名字来源取不到 —— 「整批结果都在讲阿薰kaOri」这条最有力的证据就丢了。
 * 只做保守提取：抓到的东西还必须在别的标题里也出现，才会被当成主轴（见 dominantPersonName）。
 */
export function nameFromTitleMention(title) {
  const text = String(title ?? '');
  if (!text) return '';
  const patterns = [
    // 注意不要写 \bCN：`FacebookCN : 阿薰kaOri` 里 k 和 C 之间没有词边界，带上 \b 就匹配不到了
    /CN\s*[:：]\s*([\p{L}\p{N}_@.]{2,24})/iu,
    /(?:coser|cosplayer|cos)\s*[:：\-_]\s*([\p{L}\p{N}_@.]{2,24})/iu,
    /(?:博主|coser|cosplayer)(?![吧网站群])([\u4e00-\u9fff][\p{L}\p{N}_@.]{1,23})/iu
  ];
  for (const pattern of patterns) {
    const hit = text.match(pattern);
    if (!hit) continue;
    // 中文里常见「Coser吧…」「博主网…」，把开头的语气词/站点词削掉再当名字
    const name = String(hit[1] ?? '').replace(/^(?:吧|网|站|群|们|的)+/, '').trim();
    if (name && looksLikePersonName(name)) return name;
  }
  return '';
}

export function socialNameFromTitle(title) {
  const text = String(title ?? '').replace(/\s+/g, ' ').trim();
  if (!text) return '';
  const m = text.match(
    /^(?:X|Twitter|推特|Instagram|IG|Ins|TikTok|抖音|微博|Weibo|Bilibili|哔哩哔哩|Facebook|Threads)\s*(.{1,32}?)\s*on\s*(?:X|Twitter|Instagram|TikTok|Facebook|Threads|微博|Bilibili)\b/i
  );
  if (!m) return '';
  return m[1].trim().replace(/[:："'“”]+$/, '').slice(0, 40);
}

/**
 * 主页卡片标题长这样：`X阿薰kaOri防盗版(@izayoill) / X`、`Instagram 某coser(@abc) • Instagram`。
 * 名字取 `(` 之前、去掉开头的平台徽标；顺带把 handle 也带出来（和 URL 互相印证）。
 */
export function profileTitleName(title) {
  const text = String(title ?? '').replace(/\s+/g, ' ').trim();
  if (!text) return { name: '', handle: '' };
  const m = text.match(
    /^(?:X|Twitter|推特|Instagram|IG|Ins|TikTok|抖音|微博|Weibo|Bilibili|哔哩哔哩|Facebook|Threads)\s*(.{1,40}?)\s*[（(]\s*@?([A-Za-z0-9_.\-]{2,30})\s*[)）]/i
  );
  if (!m) return { name: '', handle: '' };
  const name = m[1].trim().replace(/[:：]+$/, '');
  return { name, handle: m[2] };
}

function accountKeyOf(account) {
  const handle = String(account?.handle ?? '').replace(/^@/, '').toLowerCase();
  return `${account?.platform}|${handle}`;
}

/**
 * 搜索交叉验证，产出 inferred 账号。
 * @param {object} options
 * @param {Array} options.accounts  已有的 direct 账号（为空则直接返回 []）
 * @param {Array} options.candidates 引擎候选（从中取作者名）
 * @param {(query: string) => Promise<Array<{url?: string, title?: string}>>} options.search
 */
export async function inferAccounts({ accounts = [], candidates = [], search, max = 2, platforms = INFER_PLATFORMS, nameLimit = 3, onLog } = {}) {
  const direct = (Array.isArray(accounts) ? accounts : []).filter((item) => item?.confidence === 'direct');
  if (!direct.length) return [];
  if (typeof search !== 'function' || max <= 0) return [];

  // 搜索用的名字：作者行给的名字最准（`豊栄@ﾄﾞﾔｧ…`），没有才退回作品标题里的片段。
  const namesRaw = [];
  for (const candidate of Array.isArray(candidates) ? candidates : []) {
    const own = String(candidate?.authorName ?? '').replace(/[…\.]{2,}$/g, '').trim();
    const name = own || authorNameFromTitle(candidate?.title);
    if (name) namesRaw.push(name);
  }
  const names = [...new Set(namesRaw)].slice(0, Math.max(1, Number(nameLimit) || 3));
  if (!names.length) return [];

  const seen = new Set(direct.map(accountKeyOf));
  const wanted = (Array.isArray(platforms) && platforms.length ? platforms : INFER_PLATFORMS)
    .filter((platform) => !direct.some((item) => item.platform === platform));
  const out = [];

  for (const name of names) {
    for (const platform of wanted) {
      if (out.length >= max) return out;
      let results = [];
      try {
        results = await search(`${name} ${INFER_QUERY_HINT[platform] ?? platform} 账号`);
      } catch (error) {
        if (onLog) onLog(`[Google Lens] 推断搜索失败（${name} / ${platform}）：${error?.message ?? error}`);
        continue;
      }
      for (const result of Array.isArray(results) ? results : []) {
        const hit = matchPlatform(result?.url);
        if (!hit || hit.platform !== platform) continue;
        // 「同名」必须能在结果标题里看到，否则就是撞了别人的号
        if (!String(result?.title ?? '').includes(name)) continue;
        const key = hit.platform + '|' + String(hit.handle).replace(/^@/, '').toLowerCase();
        if (seen.has(key)) continue;
        seen.add(key);
        out.push({
          platform: hit.platform,
          handle: hit.handle,
          url: hit.url,
          confidence: 'inferred',
          evidence: { engine: 'search', similarity: null, sourceUrl: hit.url, name }
        });
        if (out.length >= max) return out;
      }
    }
  }
  return out;
}

/** 名字：优先 weibo 昵称形态的 handle，其次「图源那一条候选的标题里像人名的片段」，最后退回 handle。 */
export function accountNameOf(account, candidates = []) {
  const url = String(account?.url ?? '');
  const nick = url.match(/weibo\.com\/n\/([^/?#]+)/i);
  if (nick) {
    try { return decodeURIComponent(nick[1]); } catch { return nick[1]; }
  }
  const handle = String(account?.handle ?? '').replace(/^@/, '');
  const own = String(account?.authorName ?? '').trim();
  if (own) return own;
  const source = account?.evidence?.sourceUrl ?? '';
  const list = Array.isArray(candidates) ? candidates : [];
  const same = list.find((c) => c?.sourceUrl && source && c.sourceUrl === source)
    ?? list.find((c) => c?.sourceUrl && c.title);
  const fromTitle = same
    ? profileTitleName(same.title).name || authorNameFromTitle(same.title)
    : '';
  if (fromTitle) return fromTitle;
  if (handle && !/^\d+$/.test(handle)) return handle;
  // 纯数字 id（pixiv 会员号 / 微博 uid）看不出是谁，别硬编名字
  return '未知';
}

/** 账号展示：昵称类加 @，纯数字 id（微博 uid / B站 mid / pixiv 会员号）只给数字，链接另附。 */
function displayHandle(account) {
  const handle = String(account?.handle ?? '').replace(/^@/, '').trim();
  if (!handle) return '未知';
  return /^\d+$/.test(handle) ? handle : `@${handle}`;
}

/**
 * 拼回话。账号回复按用户指定的固定版式：
 *   🎯 **Google Lens 检索结果**
 *   🌐 平台：…
 *   👤 名字：…
 *   🆔 账号：…（主页链接跟在账号后面，方便点开核对）
 * 多个账号之间空一行；inferred 的账号在账号行尾标「推断」。
 */
export function formatReply({ accounts = [], candidates = [], enginesUsed = [], failures = [], cached = false, withImage = false, artworkDropped = 0, nameDropped = 0, consensusName = '', droppedHandles = [] } = {}) {
  const list = Array.isArray(accounts) ? accounts : [];
  // 认出主轴时，优先给「写着这个人名字」的原帖：那才是你要顺着找的那条。
  const pool = (Array.isArray(candidates) ? candidates : []).filter((c) => c?.sourceUrl);
  const consensusKey = normalizePersonName(consensusName);
  const decode = (value) => {
    try {
      return decodeURIComponent(String(value ?? ''));
    } catch {
      return String(value ?? '');
    }
  };
  const top = (consensusKey
    ? pool.find((candidate) => normalizePersonName(
      `${candidate?.title ?? ''} ${decode(candidate?.sourceUrl)}`
    ).includes(consensusKey))
    : null) ?? pool[0] ?? null;
  if (list.length) {
    const blocks = list.map((account) => {
      const url = String(account?.url ?? '').trim();
      const guess = account.confidence === 'inferred'
        ? '（推断，未核实）'
        : account.confidence === 'weak' ? '（相似图，未核实）' : '';
      const handle = `${displayHandle(account)}${url ? ` · ${url}` : ''}`;
      return [
        `🌐 平台：${platformLabel(account.platform)}`,
        `👤 名字：${accountNameOf(account, candidates)}`,
        `🆔 账号：${handle}${guess}`
      ].join('\n');
    });
    const head = `🎯 **Google Lens 检索结果**${cached ? '（缓存）' : ''}`;
    let text = [head, '', blocks.join('\n\n')].join('\n');
    // 只有画作平台的结果时，得说清楚这不是 coser 本人的号
    if (list.every((account) => ARTWORK_PLATFORMS.has(account?.platform))) {
      text += '\n\n· Pixiv 是画作平台（画师的作品页），不是 coser 本人的账号；真人号一般在推特';
    }
    if (text.length > 900) text = text.slice(0, 897) + '…';
    return text;
  }
  const tried = enginesUsed.length ? engineLabels(enginesUsed).join(' / ') : '';
  const why = failures.length ? `（${failures.map((f) => `${f.engine}:${trimText(f.reason, 30)}`).join('；')}）` : '';
  // 三种「没查到」要分开说，否则用户分不清是引擎没工作、还是翻到了但对不上人：
  //   · 一个引擎都没跑通 —— 是环境/网络问题（该看 why）
  //   · 跑通了、也翻到相似图 —— 是「对不上人」，比「都空」更接近事实
  //   · 跑通了但一片空白 —— 才是「私图/新图/裁过」
  const cacheTag = cached ? '（缓存）' : '';
  const head = !enginesUsed.length
    ? `❌ 这次没查成，一个引擎都没跑通${why ? ' ' + why : ''}`
    : String(candidates?.length ?? 0) > 0
      ? `❌ 没查到账号。${tried}${cacheTag}翻到 ${candidates.length} 条相似图，但没有能确认的账号${why ? ' ' + why : ''}`
      : `❌ 没查到账号。${tried}${cacheTag}，都空——这种一般是私图、新图，或者裁过${why ? ' ' + why : ''}`;
  const lines = [`🎯 **Google Lens 检索结果**`, '', head];
  if (Number(artworkDropped) > 0) {
    lines.push(`只翻到 ${Number(artworkDropped)} 张相似画作（相似度不够，没当成图源）；真人 coser 的号一般在推特`);
  }
  if (Number(nameDropped) > 0) {
    // 把被挡掉的 handle 也念出来：用户一眼能认出「这是另一个 coser 的号」。
    const handles = (Array.isArray(droppedHandles) ? droppedHandles : [])
      .map((handle) => String(handle ?? '').trim())
      .filter(Boolean)
      .slice(0, 3);
    const shown = handles.length ? `（${handles.join('、')}）` : '';
    lines.push(`翻到 ${Number(nameDropped)} 个别人的号${shown}，名字对不上${consensusName ? `「${trimText(consensusName, 24)}」` : '主轴'}，没当成这个人报`);
  }
  if (top) lines.push(`最接近的图源：${trimText(top.sourceUrl, 120)}`);
  let text = lines.join('\n');
  if (text.length > 900) text = text.slice(0, 897) + '…';
  return text;
}

// ── 配额 ──────────────────────────────────────────────────────────────────

function dayKey(nowMs) {
  const d = new Date(nowMs + 8 * 3600 * 1000); // 按北京时间分天
  return d.toISOString().slice(0, 10);
}

/** 能不能查。返回 {ok, reason}，reason 直接能拿来回话。 */
export function quotaOk(state, { key, userId, isOwner = false, now = Date.now() } = {}, cfg = {}) {
  if (isOwner) return { ok: true, reason: '' };
  const cdMs = Number(cfg.cdMs ?? 30000);
  const s = state && typeof state === 'object' ? state : {};
  const last = Number(s.last?.[key] ?? 0);
  if (cdMs > 0 && now - last < cdMs) {
    const wait = Math.ceil((cdMs - (now - last)) / 1000);
    return { ok: false, reason: `慢点，${wait} 秒后再发` };
  }
  const day = dayKey(now);
  const userCount = Number(s.day?.user?.[String(userId)]?.count ?? 0);
  const userDay = String(s.day?.user?.[String(userId)]?.day ?? '');
  const perUser = Number(cfg.perUserDay ?? 20);
  if (userDay === day && perUser > 0 && userCount >= perUser) {
    return { ok: false, reason: `今天的 ${perUser} 次用完了，明天再来` };
  }
  const globalCount = Number(s.day?.global?.count ?? 0);
  const globalDay = String(s.day?.global?.day ?? '');
  const perGlobal = Number(cfg.globalDay ?? 100);
  if (globalDay === day && perGlobal > 0 && globalCount >= perGlobal) {
    return { ok: false, reason: `今天全站 ${perGlobal} 次用完了，明天再来` };
  }
  return { ok: true, reason: '' };
}

/** 扣一次配额，返回新 state（纯函数，调用方负责原子写）。 */
export function chargeQuota(state, { key, userId } = {}, now = Date.now()) {
  const s = state && typeof state === 'object' ? state : {};
  const day = dayKey(now);
  const next = {
    ...s,
    last: { ...(s.last ?? {}), [key]: now },
    day: {
      ...(s.day ?? {}),
      user: { ...(s.day?.user ?? {}) },
      global: { ...(s.day?.global ?? {}) }
    }
  };
  const uid = String(userId);
  const prevUser = next.day.user[uid];
  next.day.user[uid] = {
    day,
    count: (prevUser?.day === day ? Number(prevUser?.count ?? 0) : 0) + 1
  };
  next.day.global = {
    day,
    count: (next.day.global?.day === day ? Number(next.day.global?.count ?? 0) : 0) + 1
  };
  return next;
}

// ── 缓存 ──────────────────────────────────────────────────────────────────

export function cacheKeyFor(bytes, enginesVersion = ENGINES_VERSION) {
  return `${sha256Hex(bytes)}:${enginesVersion}`;
}

export function cacheGet(cache, key, now = Date.now(), { cacheDays = 30 } = {}) {
  const entry = cache && typeof cache === 'object' ? cache[key] : null;
  if (!entry || typeof entry !== 'object') return null;
  const ageDays = (now - Number(entry.at ?? 0)) / 86400000;
  if (!Number.isFinite(ageDays) || ageDays > Number(cacheDays ?? 30)) return null;
  return entry.result ?? null;
}

export function cachePut(cache, key, result, now = Date.now(), { cacheMax = 500 } = {}) {
  const next = { ...(cache && typeof cache === 'object' ? cache : {}) };
  next[key] = { at: now, result };
  const keys = Object.keys(next);
  const max = Math.max(1, Number(cacheMax) || 500);
  if (keys.length > max) {
    keys.sort((a, b) => Number(next[a]?.at ?? 0) - Number(next[b]?.at ?? 0));
    for (const stale of keys.slice(0, keys.length - max)) delete next[stale];
  }
  return next;
}

// ── 引擎可用性 ────────────────────────────────────────────────────────────

// 已验证「开箱即用」的引擎：不给探针结果也跑（探针只用来记录健康度）。
// 回话里给用户看的名字：光甩 id（lens / tracemoe）没人看得懂。
export const ENGINE_LABELS = {
  saucenao: 'SauceNAO',
  lens: '谷歌 Lens',
  tracemoe: '动漫截图溯源',
  iqdb: 'IQDB',
  baidu: '百度识图',
  bing: '必应',
  yandex: 'Yandex',
  google: '谷歌识图'
};

/** 把引擎 id 列表变成人话，例如 `谷歌 Lens / SauceNAO`。 */
export function engineLabels(engines) {
  const list = Array.isArray(engines) ? engines : [];
  return list.map((id) => ENGINE_LABELS[id] ?? String(id)).filter(Boolean);
}

export const PROXY_ENGINES = new Set(['lens', 'yandex', 'google']);
export const DIRECT_ENGINES = new Set(['saucenao', 'tracemoe', 'iqdb', 'bing', 'baidu']);

/** 按「要不要外网」把引擎分两拨：直连的先跑，不够再开魔法跑另一拨。 */
export function splitEnginesByProxy(engines = []) {
  const list = Array.isArray(engines) ? engines.filter((id) => typeof id === 'string') : [];
  return {
    direct: list.filter((id) => !PROXY_ENGINES.has(id)),
    proxied: list.filter((id) => PROXY_ENGINES.has(id))
  };
}

export const ALWAYS_ON_ENGINES = new Set(['saucenao', 'iqdb', 'tracemoe', 'lens']);

/** 读探针结果，决定这次能用哪些引擎。探针没跑过 → 只开已验证的那几个。 */
export function pickEngines(cfg = {}, probe = null) {
  const wanted = Array.isArray(cfg.engines) && cfg.engines.length ? cfg.engines : ['saucenao', 'iqdb', 'tracemoe'];
  const probed = probe?.engines && typeof probe.engines === 'object' ? probe.engines : null;
  if (!probed) return wanted.filter((id) => ALWAYS_ON_ENGINES.has(id));
  return wanted
    .filter((id) => ENGINE_IDS.includes(id))
    .filter((id) => {
      if (ALWAYS_ON_ENGINES.has(id)) return probed[id]?.ok !== false;
      return probed[id]?.ok === true;
    });
}

/** 回话里说明「为什么只查了这些」。 */
export function describeEngines(engines, probe = null) {
  const list = Array.isArray(engines) && engines.length ? engines : [];
  if (!list.length) return '没有可用引擎';
  const text = engineLabels(list).join(' / ');
  const probed = probe?.engines ?? {};
  const dead = Object.entries(probed)
    .filter(([id, info]) => info && info.ok === false && !list.includes(id))
    .map(([id]) => id);
  return dead.length ? `${text}（${engineLabels(dead).join('、')} 目前不可用）` : text;
}

// ── 状态文件读写（原子） ──────────────────────────────────────────────────

export function readJsonFile(file, fallback) {
  try {
    const raw = JSON.parse(fs.readFileSync(file, 'utf8'));
    return raw && typeof raw === 'object' ? raw : fallback;
  } catch {
    return fallback;
  }
}

export function writeJsonFileAtomic(file, value) {
  const dir = path.dirname(file);
  try { fs.mkdirSync(dir, { recursive: true }); } catch {}
  const tmp = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(value));
  try {
    fs.renameSync(tmp, file);
  } catch (error) {
    try { fs.rmSync(tmp, { force: true }); } catch {}
    throw error;
  }
}

/** 「已找到鸡」素材：读得到、没超限才返回 Buffer，否则 null（调用方只发文字）。 */
export function loadFoundImage(cfg = {}, { fsModule = fs } = {}) {
  const file = String(cfg.foundImage ?? '');
  if (!file) return null;
  const cap = Number(cfg.foundImageMaxBytes ?? 4 * 1024 * 1024);
  try {
    const stat = fsModule.statSync(file);
    if (!stat.isFile() || stat.size === 0 || stat.size > cap) return null;
    const buffer = fsModule.readFileSync(file);
    return buffer?.length ? buffer : null;
  } catch {
    return null;
  }
}

// ── 猫猫云：按需开 / 关 VPN（只碰 core，不碰 GUI）─────────────────────────────
//
// 猫猫云的「连接」按钮程序点不到（窗口不可显示、无 UIA、无托盘项、无 IPC/CLI），
// 所以这里复现它自己会做的那串动作：按它日志里的写法把 core（libcore / mihomo）用
// `-d <coreDir>` 拉起来，拿到 mixed 代理端口。默认**不动系统代理**：node 侧自己用
// CONNECT 建隧道，浏览器侧单开 --proxy-server —— 用户原本的代理设置一个字都不改，
// 跑完只把自己起的那个 core 收掉。
//
// 三条底线：①不 kill 猫猫云 GUI、不起第二个实例；②只 kill 状态文件里记下的 pid，
// 绝不通配（taskkill /IM mihomo* 会误伤别人的核）；③先还原代理、再杀 core。

// VPN / 代理配置：由调用方通过 proxy 参数透传（统一由 YAMLManager 提供）
export function vpnConfig(cfg = {}) {
  const p = cfg?.proxy || '';
  return { proxy: p };
}
export function vpnProxyUrl(cfg = {}) {
  return cfg?.proxy || '';
}
export async function withVpn(task, cfg = {}) {
  return await task();
}
export async function vpnState(cfg = {}) {
  return { ok: true, proxy: cfg?.proxy || '' };
}
