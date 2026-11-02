#!/usr/bin/env node
// Google Lens 图像搜索命令行入口：输入图片（本地文件或网络地址），反查出处与网页来源。
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  reverseSearch,
  extractAccounts,
  formatReply,
  engineLabels,
  ENGINE_IDS,
  closeBrowser
} from '../src/lens_core.js';
import { safeFetchBuffer } from '../src/safe-fetch.js';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PLUGIN_ROOT = path.resolve(HERE, '..');

const DEFAULTS = {
  enabled: true,
  engines: ['lens', 'saucenao', 'tracemoe'],
  timeoutMs: 45000,
  maxAccounts: 3,
  strictConsensus: true,
  // 谷歌系引擎要看得到外网。填本机代理（猫猫云/clash 这类）就能单独让它走代理，
  // 不动系统代理 —— 空串 = 直连。
  proxy: '',
  browserExe: ''
};

const USAGE = `Google Lens 图像搜索 v1.0.0

用法：
  node bin/lens_cli.mjs <图片文件|地址>            反查出处与匹配来源
  node bin/lens_cli.mjs <图片文件> --json          输出结构化 JSON
  node bin/lens_cli.mjs <图片文件> --engines lens,saucenao
  node bin/lens_cli.mjs <图片文件> --no-strict     非严格模式
  node bin/lens_cli.mjs --check                    自检：配置与网络连通性

选项：
  --engines a,b      指定引擎（默认 lens,saucenao,tracemoe）
  --max <n>          最多报告账号/来源数（默认 5）
  --timeout <秒>     各引擎超时（默认 45）
  --proxy <url>      网络代理，如 http://127.0.0.1:7890
  --browser <路径>   指定 Edge/Chrome 可执行文件（默认自动找 Edge）
  --json             结构化输出
  -h, --help         帮助信息

引擎说明：
  lens       谷歌 Lens（主引擎，通过 CDP 无头浏览器抓取结果页）
  saucenao   插画/同人图检索（直连官方 API）
  tracemoe   动画截图出处检索（直连官方 API）
  iqdb       二次元图库（直连）
  baidu      百度识图（备选）
`;

function parseArgs(argv) {
  const out = { image: '', engines: null, max: 0, timeout: 0, proxy: null, browser: '', json: false, strict: true, config: '', check: false };
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    if (a === '-h' || a === '--help') return { help: true };
    else if (a === '--json') out.json = true;
    else if (a === '--no-strict') out.strict = false;
    else if (a === '--check') out.check = true;
    else if (a === '--engines') out.engines = String(argv[++i] ?? '').split(',').map((s) => s.trim()).filter(Boolean);
    else if (a === '--max') out.max = Number(argv[++i]) || 0;
    else if (a === '--timeout') out.timeout = Number(argv[++i]) || 0;
    else if (a === '--proxy') out.proxy = String(argv[++i] ?? '');
    else if (a === '--browser') out.browser = String(argv[++i] ?? '');
    else if (a === '--config') out.config = String(argv[++i] ?? '');
    else if (a.startsWith('-')) throw new Error(`不认识的参数：${a}`);
    else if (!out.image) out.image = a;
    else throw new Error(`多给了一个参数：${a}`);
  }
  return out;
}

function loadConfig(argv) {
  const file = argv.config ? path.resolve(argv.config) : path.join(PLUGIN_ROOT, 'config.json');
  let saved = {};
  if (fs.existsSync(file)) {
    try {
      saved = JSON.parse(fs.readFileSync(file, 'utf8'));
    } catch (error) {
      throw new Error(`config.json 读不了（${file}）：${error.message}`);
    }
  }
  const cfg = { ...DEFAULTS, ...saved };
  if (argv.engines) cfg.engines = argv.engines;
  if (argv.max) cfg.maxAccounts = argv.max;
  if (argv.timeout) cfg.timeoutMs = argv.timeout * 1000;
  if (argv.proxy !== null) cfg.proxy = argv.proxy;
  if (argv.browser) cfg.browserExe = argv.browser;
  return cfg;
}

/** 按文件头认格式，不信扩展名 —— 有人把 png 存成 .jpg，反查接口会直接拒。 */
function sniffMime(bytes) {
  if (bytes.length > 8 && bytes[0] === 0x89 && bytes[1] === 0x50) return 'image/png';
  if (bytes.length > 12 && bytes.slice(0, 4).toString('ascii') === 'RIFF' && bytes.slice(8, 12).toString('ascii') === 'WEBP') return 'image/webp';
  if (bytes.length > 3 && bytes[0] === 0x47 && bytes[1] === 0x49 && bytes[2] === 0x46) return 'image/gif';
  return 'image/jpeg';
}

async function readImage(target) {
  if (/^https?:\/\//i.test(target)) {
    const got = await safeFetchBuffer(target, 20 * 1024 * 1024);
    if (!got.buffer?.length) throw new Error(`这个地址没取到图：${target}`);
    return { bytes: got.buffer, mimeType: sniffMime(got.buffer), source: target };
  }
  const file = path.resolve(target);
  if (!fs.existsSync(file)) throw new Error(`找不到这个文件：${file}`);
  const stat = fs.statSync(file);
  if (!stat.isFile()) throw new Error(`这不是文件：${file}`);
  if (stat.size > 20 * 1024 * 1024) throw new Error(`图太大了（${(stat.size / 1024 / 1024).toFixed(1)}MB，上限 20MB）`);
  const bytes = fs.readFileSync(file);
  return { bytes, mimeType: sniffMime(bytes), source: file };
}

async function doCheck(cfg) {
  const list = (cfg.engines ?? []).filter((id) => ENGINE_IDS.includes(id));
  console.log(`引擎：${engineLabels(list).join(' / ') || '（空）'}`);
  const unknown = (cfg.engines ?? []).filter((id) => !ENGINE_IDS.includes(id));
  if (unknown.length) console.log(`WARN 不认识的引擎：${unknown.join(', ')}`);
  console.log(`代理：${cfg.proxy ? cfg.proxy : '直连'}`);
  console.log(`超时：${Math.round(cfg.timeoutMs / 1000)} 秒/引擎`);
  console.log('\n提示：lens/google 需要外网；saucenao/iqdb/tracemoe 直连即可。');
  console.log('连不上外网时用 --proxy http://127.0.0.1:10090 只让浏览器走代理。');
  return true;
}

async function main() {
  const argv = parseArgs(process.argv.slice(2));
  if (argv.help) {
    console.log(USAGE);
    return 0;
  }
  const cfg = loadConfig(argv);
  if (argv.check) return (await doCheck(cfg)) ? 0 : 1;
  if (!argv.image) {
    console.log(USAGE);
    return 2;
  }

  const image = await readImage(argv.image);
  try {
  const started = Date.now();
  const verb = argv.json ? null : (text) => console.log(`  ${text}`);
  if (verb) console.log(`查图：${image.source}（${(image.bytes.length / 1024).toFixed(0)}KB ${image.mimeType}）`);

  const result = await reverseSearch(image.bytes, image.mimeType, {
    engines: cfg.engines,
    timeoutMs: cfg.timeoutMs,
    proxy: cfg.proxy || '',
    browserExe: cfg.browserExe || '',
    onLog: verb ? (line) => console.log(`  ${line}`) : null
  });

  const isGoogleUrl = (u) => {
    try {
      const h = new URL(u).hostname.toLowerCase();
      return /(^|\.)google(\.[a-z.]+)?$/i.test(h) ||
             /(^|\.)(gstatic|googleapis|googletagmanager|google-analytics|doubleclick|adtrafficquality)\./i.test(h);
    } catch { return true; }
  };
  const seenWebUrls = new Set();
  const webResults = (result.candidates || [])
    .filter((c) => c?.url && !isGoogleUrl(c.url))
    .filter((c) => {
      if (seenWebUrls.has(c.url)) return false;
      seenWebUrls.add(c.url);
      return true;
    })
    .slice(0, 8)
    .map((c) => ({
      title: c.title || '',
      url: c.url,
      engine: c.engine || 'lens'
    }));

  const accounts = extractAccounts(result.candidates, { max: cfg.maxAccounts, strictNames: argv.strict });
  let text = formatReply({
    accounts,
    candidates: result.candidates,
    enginesUsed: result.enginesUsed,
    failures: result.failures,
    cached: false
  });

  if (!accounts.length && webResults.length) {
    text += '\n\n🌐 **Google Lens 相似网页出处：**\n' + webResults.slice(0, 5).map((w, idx) => `${idx + 1}. ${w.title || '网页'}\n   ${w.url}`).join('\n');
  }

  if (argv.json) {
    console.log(JSON.stringify({
      source: image.source,
      elapsedMs: Date.now() - started,
      enginesUsed: result.enginesUsed,
      failures: result.failures,
      accounts,
      webResults,
      text
    }, null, 2));
    return 0;
  }

  console.log('');
  console.log(text);
  console.log('');
  console.log(`用时 ${((Date.now() - started) / 1000).toFixed(1)} 秒 · 引擎 ${result.enginesUsed.join(', ') || '无'}`);
  if (result.failures?.length) {
    console.log(`没出结果的：${result.failures.map((f) => `${f.engine}(${f.reason})`).join('、')}`);
  }
  return 0;
  } finally {
    try { await closeBrowser(); } catch {}
  }
}

main().then(
  (code) => { process.exit(typeof code === 'number' ? code : 0); },
  (error) => {
    console.error(`出错了：${error?.message ?? error}`);
    process.exit(1);
  }
);
