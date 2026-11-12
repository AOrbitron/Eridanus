// Live2D 桌宠渲染层
// 移植并精简自 EchoBot (MIT) 的 web/features/live2d/{model,scene}.js 与 tts/playback.js
/* global PIXI */

const canvas = document.getElementById("live2d-canvas");
const bubbleEl = document.getElementById("bubble");
const statusEl = document.getElementById("status");

// 宿主：Electron 桌宠由 preload 注入 window.desktop；网页版（/live2dchat）由 webchat.html
// 注入带 isWeb:true 的 shim。IS_WEB 用来收口两端差异（拖窗/穿透/ws 地址/历史/媒体/代理）。
const HOST = window.desktop || {};
const IS_WEB = !!HOST.isWeb;

const state = {
  config: null,
  app: null,
  model: null,
  scale: 0.18,
  // 口型
  currentMouthValue: 0,
  lipSyncIds: ["ParamMouthOpenY"],
  internalModel: null,
  lipSyncHook: null,
  motionManager: null,    // 当前模型的 motionManager（用于监听动作结束）
  motionFinishHook: null, // 动作播完回到默认姿态的回调
  // 拖拽
  dragging: false,
  lastPointer: { x: 0, y: 0 },
  pendingMove: { dx: 0, dy: 0, scheduled: false }, // 拖拽位移按帧合并，避免高频 setPosition 造成闪烁
  lastSize: { w: 0, h: 0 },                        // 上次画布逻辑尺寸，用于过滤重复 resize（防止画面逐帧变大）
  lastEmotion: null,                               // 上一次情绪：相同则不变脸
  expressionResetTimer: 0,                         // 变脸后回到默认待机表情的定时器
  bubbleTimer: 0,
  audioContext: null,
  audioQueue: [],     // 待播放的语音段（ArrayBuffer），按入队顺序串行播放
  audioPlaying: false, // 队列是否正在被消费（保证同一时刻只有一段在播）
  webuiWs: null,   // 唯一连接：webui 的 /api/ws（与浏览器前端同源）
  history: [],
  ignoringMouse: true, // 与 main.js 初始 setIgnoreMouseEvents(true) 保持一致
};

function setStatus(text) {
  statusEl.textContent = text || "";
  statusEl.style.display = text ? "block" : "none";
}

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

// ---------- 模型加载 ----------

// 把本地路径/file:// 统一成可被渲染端正确加载的 file:// URL，并对中文等非 ASCII 字符编码
// （data/yumi 等 VTube 模型的 *.exp3.json/*.motion3.json 多为中文文件名，未编码会加载失败）。
function toFileUrl(value) {
  if (!value) return value;
  if (value.startsWith("base64://")) return "data:image/png;base64," + value.slice("base64://".length);
  if (/^https?:\/\//i.test(value) || value.startsWith("data:")) return value;
  let p = value.startsWith("file://") ? value.slice("file://".length) : value;
  p = p.replace(/\\/g, "/");
  if (/^[A-Za-z]:\//.test(p)) p = "/" + p; // Windows 盘符 D:/... -> /D:/...
  if (!p.startsWith("/")) p = "/" + p;
  return "file://" + encodeURI(p);
}

// 媒体（图片/文件）URL：桌宠走 file://（webSecurity:false 可直接加载）；网页版浏览器
// 无法加载本地 file://，改写为 WebUI 现成的 /api/chat/file（与网页前端显示图片一致，
// 它会把本地文件搬进 chat_files 再回传）。http/https/data/base64 两端都可直接用。
function mediaUrl(fileOrUrl, name) {
  const raw = fileOrUrl;
  if (!raw) return raw;
  if (!IS_WEB) return toFileUrl(raw);
  if (/^https?:\/\//i.test(raw) || raw.startsWith("data:")) return raw;
  if (raw.startsWith("base64://")) return "data:image/png;base64," + raw.slice("base64://".length);
  const p = raw.startsWith("file://") ? raw : "file://" + raw;
  let q = "path=" + encodeURIComponent(p);
  if (name) q += "&name=" + encodeURIComponent(name);
  return "/api/chat/file?" + q;
}

async function loadModel(url) {
  if (!url) {
    setStatus("未配置模型路径（model_path / model）");
    return false;
  }
  setStatus("正在加载 Live2D 模型…");

  try {
    // 桌宠：把本地路径转成 file://（webSecurity:false 直加载）。
    // 网页：model_url 已是同源 HTTP 路径（/live2dchat/model/...），原样使用——
    // 切不可再过 toFileUrl，否则会被改写成浏览器无法加载的 file:///live2dchat/...（network error）。
    const src = IS_WEB ? url : toFileUrl(url);
    // autoUpdate:false —— pixi-live2d-display 独立打包版不会自动注册 ticker，默认 autoUpdate
    // 会因“无 ticker”而静默不更新，导致模型加载成功却不渲染（空白）。这里关掉自动更新，
    // 由 app 渲染循环手动 model.update()（见 boot 里的 ticker.add），确保稳定渲染。
    const model = await PIXI.live2d.Live2DModel.from(src, { autoInteract: false, autoUpdate: false });

    disposeModel();
    state.model = model;
    state.app.stage.addChild(model);

    model.anchor.set(0.5, 0.5);
    layoutModel();
    if (IS_WEB) {
      // 网页版按视口自适应大小。立即拟合一次；再在下一帧拟合一次，兜底首帧 getBounds 尚未就绪。
      fitModelToViewport();
      window.requestAnimationFrame(fitModelToViewport);
    }
    attachLipSyncHook(model);
    attachMotionResetHook(model);

    bindModelInteractions(model);
    setStatus("");
    return true;
  } catch (err) {
    console.error("[live2d] 模型加载失败:", err);
    setStatus(`模型加载失败：${err && err.message ? err.message : err}`);
    return false;
  }
}

function layoutModel() {
  if (!state.model || !state.app) return;
  state.model.scale.set(state.scale);
  // 用 app.screen（逻辑/CSS 像素）而非 renderer.width（= 逻辑宽 × resolution 的物理像素）。
  // 在 devicePixelRatio>1 的高 DPI 屏上，renderer.width 是物理像素，除以 2 会把模型推到
  // 右侧甚至画面外，表现为“角色偏右、显示不全”。screen 才是 stage 坐标系所用的逻辑像素。
  const sw = state.app.screen.width;
  const sh = state.app.screen.height;
  let cx = sw / 2;
  let cy = sh / 2;
  if (IS_WEB) {
    // 网页版聊天布局：宽屏让模型靠左、给右侧聊天卡片留位；窄屏（移动端）默认聊天折叠，
    // 模型基本居中（略偏上，给底部输入条留位）。
    const wide = window.innerWidth >= 768;
    cx = wide ? sw * 0.34 : sw * 0.5;
    cy = wide ? sh * 0.5 : sh * 0.46;
  }
  state.model.position.set(cx, cy);
}

// 网页版：按视口高度自动缩放模型，避免大屏上角色过小（桌宠是固定小窗，无需此步）。
function fitModelToViewport() {
  if (!state.model || !state.app) return;
  let b;
  try { b = state.model.getBounds(); } catch (e) { return; }
  if (!b || b.height <= 0) return;
  const wide = window.innerWidth >= 768;
  const target = state.app.screen.height * (wide ? 0.82 : 0.62);
  state.scale = clamp(state.scale * (target / b.height), 0.04, 1.2);
  layoutModel();
}

// 网页版：缩放按钮（桌面/移动通用）+ 双指捏合缩放（移动端）。桌宠用滚轮，无需此函数。
function bindWebTouchAndZoom() {
  const zoom = (delta) => { state.scale = clamp(state.scale + delta, 0.04, 1.2); layoutModel(); };
  const zin = document.getElementById("zoom-in");
  const zout = document.getElementById("zoom-out");
  if (zin) zin.addEventListener("click", () => zoom(0.03));
  if (zout) zout.addEventListener("click", () => zoom(-0.03));

  const inUI = (t) => t && t.closest && t.closest(".chat-shell, #login-mask, .zoom-ctl");
  const dist = (ts) => Math.hypot(ts[0].clientX - ts[1].clientX, ts[0].clientY - ts[1].clientY);
  let pinch = 0;
  window.addEventListener("touchstart", (e) => {
    if (e.touches.length === 2 && !inUI(e.target)) pinch = dist(e.touches);
  }, { passive: true });
  window.addEventListener("touchmove", (e) => {
    if (e.touches.length === 2 && pinch > 0 && !inUI(e.target)) {
      const d = dist(e.touches);
      if (d > 0) { state.scale = clamp(state.scale * (d / pinch), 0.04, 1.2); pinch = d; layoutModel(); }
      e.preventDefault(); // 阻止浏览器整页缩放
    }
  }, { passive: false });
  window.addEventListener("touchend", (e) => { if (e.touches.length < 2) pinch = 0; });
}

// 仅在窗口逻辑尺寸真正变化时 resize，过滤拖动期间的伪 resize（防止画布逐帧变大）
function resizeApp() {
  if (!state.app) return;
  const w = window.innerWidth;
  const h = window.innerHeight;
  if (w === state.lastSize.w && h === state.lastSize.h) return;
  state.lastSize = { w, h };
  state.app.renderer.resize(w, h);
  layoutModel();
}

function disposeModel() {
  detachLipSyncHook();
  detachMotionResetHook();
  if (state.model) {
    try {
      state.app.stage.removeChild(state.model);
      state.model.destroy({ children: true });
    } catch (err) {
      console.warn("[live2d] 销毁模型失败:", err);
    }
  }
  state.model = null;
}

// ---------- 口型同步 ----------

function attachLipSyncHook(model) {
  detachLipSyncHook();
  const internalModel = model.internalModel;
  if (!internalModel || typeof internalModel.on !== "function") return;

  state.lipSyncHook = function () {
    const coreModel = internalModel.coreModel;
    if (!coreModel || typeof coreModel.setParameterValueById !== "function") return;
    state.lipSyncIds.forEach((id) => {
      try {
        coreModel.setParameterValueById(id, state.currentMouthValue);
      } catch (err) {
        // 某些模型没有该参数，忽略
      }
    });
  };
  internalModel.on("beforeModelUpdate", state.lipSyncHook);
  state.internalModel = internalModel;
}

function detachLipSyncHook() {
  if (state.internalModel && state.lipSyncHook && typeof state.internalModel.off === "function") {
    state.internalModel.off("beforeModelUpdate", state.lipSyncHook);
  }
  state.internalModel = null;
  state.lipSyncHook = null;
}

// ---------- 动作结束复位 ----------

// 自动发现的动作各自成组，模型没有 Idle 组，动作（如挥手 wave）播完后 MotionManager
// 停止写参数，会把最后一帧的姿态留住（用户观察到的“挥手后手不放下”）。这里监听
// motionFinish，在动作真正结束时把核心参数复位到默认值，回到自然待机姿态。
function attachMotionResetHook(model) {
  detachMotionResetHook();
  const mm = model.internalModel && model.internalModel.motionManager;
  if (!mm || typeof mm.on !== "function") return;
  state.motionFinishHook = function () { resetModelPose(); };
  mm.on("motionFinish", state.motionFinishHook);
  state.motionManager = mm;
}

function detachMotionResetHook() {
  if (state.motionManager && state.motionFinishHook && typeof state.motionManager.off === "function") {
    state.motionManager.off("motionFinish", state.motionFinishHook);
  }
  state.motionManager = null;
  state.motionFinishHook = null;
}

// 把核心参数复位到模型默认值并 saveParameters。复位后下一帧 update() 中 motionManager
// 已 finished（不再写参数），expressionManager 会把当前表情重新叠加回来，呼吸/物理从中性
// 恢复——动作残留消失而表情保留。口型由 lipSync hook 每帧单独驱动，不受影响。
function resetModelPose() {
  const core = state.model && state.model.internalModel && state.model.internalModel.coreModel;
  if (!core || typeof core.getParameterCount !== "function") return;
  try {
    const n = core.getParameterCount();
    for (let i = 0; i < n; i += 1) {
      try { core.setParameterValueByIndex(i, core.getParameterDefaultValue(i)); } catch (e) { /* ignore */ }
    }
    if (typeof core.saveParameters === "function") core.saveParameters();
  } catch (e) { /* ignore */ }
}

function smooth(prev, next, factor) {
  return prev + (next - prev) * factor;
}

// 把一段音频排入播放队列。多段语音不再同时发声，而是按入队顺序一个接一个播放
// （避免多条回复/多段语音叠在一起破坏沉浸感）。
function playAudioBuffer(arrayBuf) {
  if (!arrayBuf) return;
  state.audioQueue.push(arrayBuf);
  drainAudioQueue();
}

// 串行消费队列：始终只有一段在播，当前段 onended 后才取下一段。
async function drainAudioQueue() {
  if (state.audioPlaying) return;
  state.audioPlaying = true;
  try {
    while (state.audioQueue.length) {
      await playOneBuffer(state.audioQueue.shift());
    }
  } finally {
    state.audioPlaying = false;
  }
}

// 播放单段 ArrayBuffer 并用 AnalyserNode 音量驱动口型（移植自 EchoBot playback.js）；
// 返回的 Promise 在该段播放结束时 resolve，供队列串行等待。
async function playOneBuffer(arrayBuf) {
  if (!arrayBuf) return;
  let ctx;
  try {
    if (!state.audioContext) {
      state.audioContext = new (window.AudioContext || window.webkitAudioContext)();
    }
    ctx = state.audioContext;
    if (ctx.state === "suspended") await ctx.resume();
  } catch (err) {
    console.error("[live2d] 音频上下文初始化失败:", err);
    return;
  }

  let audioBuf;
  try {
    audioBuf = await ctx.decodeAudioData(arrayBuf.slice(0));
  } catch (err) {
    console.error("[live2d] 音频解码失败:", err);
    return;
  }

  await new Promise((resolve) => {
    const source = ctx.createBufferSource();
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 256;
    source.buffer = audioBuf;
    source.connect(analyser);
    analyser.connect(ctx.destination);

    const data = new Uint8Array(analyser.frequencyBinCount);
    let raf = 0;
    const tick = () => {
      analyser.getByteFrequencyData(data);
      let sum = 0;
      for (let i = 0; i < data.length; i += 1) sum += data[i];
      const avg = sum / data.length / 255; // 0..1
      state.currentMouthValue = smooth(state.currentMouthValue, clamp(avg * 1.8, 0, 1), 0.5);
      raf = window.requestAnimationFrame(tick);
    };

    source.onended = () => {
      window.cancelAnimationFrame(raf);
      state.currentMouthValue = 0;
      resolve();
    };

    try {
      source.start(0);
      tick();
    } catch (err) {
      console.error("[live2d] 音频播放失败:", err);
      resolve();
    }
  });
}

// 从 URL 取音频再播放（保留给图片/历史等可能的 URL 来源）
async function playAudio(src) {
  try {
    const resp = await fetch(src);
    await playAudioBuffer(await resp.arrayBuffer());
  } catch (err) {
    console.error("[live2d] 音频拉取失败:", err);
  }
}

// ---------- 本地语音合成（GPT-SoVITS /tts，参数同 run/tts_v2） ----------

// 去掉括号内的描写（动作/旁白/神态），只把“真正要说出口的话”交给语音合成；
// 气泡仍显示完整文本。覆盖全角（）、半角()、方括号【】。
function stripParenthetical(text) {
  return String(text || "")
    .replace(/（[^）]*）/g, "")
    .replace(/\([^)]*\)/g, "")
    .replace(/【[^】]*】/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

// 调用 GPT-SoVITS /tts 合成语音，返回音频 ArrayBuffer（失败抛出，由调用方兜底）。
// payload 与 run/tts_v2/service/GPT_SoVits.py 对齐，确保与 bot 端语音一致。
async function synthesizeTTS(text) {
  const cfg = state.config.tts || {};
  if (cfg.enable === false) return null;
  const t = String(text || "").trim();
  if (!t) return null;
  // 网页版：经服务端 /live2dchat/tts 代理（密钥/参数留服务端、同源无 CORS）
  if (IS_WEB) {
    const resp = await fetch("/live2dchat/tts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: t }),
    });
    if (!resp.ok) throw new Error("TTS HTTP " + resp.status);
    return await resp.arrayBuffer();
  }
  if (!cfg.api_base) return null;
  const payload = {
    text: t,
    text_lang: cfg.target_lang || "zh",
    ref_audio_path: cfg.ref_audio_path,
    prompt_text: cfg.ref_text,
    prompt_lang: cfg.ref_lang || "zh",
    top_k: cfg.top_k,
    top_p: cfg.top_p,
    temperature: cfg.temperature,
    text_split_method: cfg.text_split_method || "cut5",
    batch_size: cfg.batch_size,
    speed_factor: cfg.speed_factor,
    streaming_mode: cfg.streaming_mode,
    seed: cfg.seed,
    fragment_interval: 0.32,
    media_type: "wav",
    repetition_penalty: cfg.repetition_penalty || 1.35,
  };
  const url = cfg.api_base.replace(/\/+$/, "") + "/tts";
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!resp.ok) throw new Error("TTS HTTP " + resp.status);
  return await resp.arrayBuffer();
}

// ---------- 气泡 ----------

function _showBubbleEl(durationMs) {
  bubbleEl.classList.add("visible");
  positionBubble();
  if (state.bubbleTimer) window.clearTimeout(state.bubbleTimer);
  state.bubbleTimer = window.setTimeout(() => {
    bubbleEl.classList.remove("visible");
  }, durationMs);
}

// 把气泡放到“模型头顶上方”，并夹在窗口内。原先固定在窗口左上(left:50%/top:10px)，
// 模型居中且缩放后会显得气泡偏左上、脱离角色；改为跟随模型实际包围盒顶部居中。
function positionBubble() {
  if (!state.model || !bubbleEl.classList.contains("visible")) return;
  let b;
  try { b = state.model.getBounds(); } catch (e) { return; }
  const bw = bubbleEl.offsetWidth;
  const bh = bubbleEl.offsetHeight;
  const headX = b.x + b.width / 2;        // 模型水平中心
  let left = headX - bw / 2;              // 气泡水平居中于头顶
  let top = b.y - bh - 12;                // 头顶上方 12px
  left = clamp(left, 6, Math.max(6, window.innerWidth - bw - 6));
  top = clamp(top, 6, Math.max(6, window.innerHeight - bh - 6));
  bubbleEl.style.left = left + "px";
  bubbleEl.style.top = top + "px";
  bubbleEl.style.transform = "none";      // 覆盖 CSS 里的 translateX(-50%)
}

function showBubble(text, durationMs) {
  bubbleEl.textContent = String(text || "");
  const dur = Number.isFinite(durationMs) ? durationMs : Math.max(2500, String(text).length * 180);
  _showBubbleEl(dur);
}

function showBubbleImage(url, durationMs) {
  bubbleEl.textContent = "";
  const img = document.createElement("img");
  img.src = url;
  bubbleEl.appendChild(img);
  _showBubbleEl(Number.isFinite(durationMs) ? durationMs : 5000);
}

// ---------- 交互：拖拽移动窗口 + 滚轮缩放 ----------

function bindModelInteractions(model) {
  // 仅设光标提示；起拖改到窗口级（按包围盒判定），见 bindGlobalInteractions 的 pointerdown。
  // PIXI 的 model pointerdown 只命中模型实际不透明像素，导致角色左右两侧透明区域
  // “能进窗口却点不动模型”；改用包围盒后整块可拖拽，与鼠标穿透范围一致。
  model.interactive = true;
  model.cursor = "grab";
}

function flushPendingMove() {
  const pm = state.pendingMove;
  pm.scheduled = false;
  const { dx, dy } = pm;
  pm.dx = 0;
  pm.dy = 0;
  if (dx || dy) window.desktop.moveBy(dx, dy);
}

function bindGlobalInteractions() {
  // 起拖：落在模型包围盒内（与鼠标穿透判定一致）即可拖动整窗，不再依赖 PIXI 模型像素命中。
  // 命中输入条/历史面板时不起拖，让其正常交互。
  window.addEventListener("pointerdown", (event) => {
    if (IS_WEB) return; // 网页版不能移动标签页，禁用拖窗
    if (event.target && event.target.closest && event.target.closest("#chat-bar, #history-panel")) return;
    if (!isInteractiveAt(event.clientX, event.clientY)) return;
    state.dragging = true;
    state.lastPointer.screenX = event.screenX;
    state.lastPointer.screenY = event.screenY;
    if (state.model) state.model.cursor = "grabbing";
  });

  // 右键菜单：桌宠弹出原生菜单（含「关闭桌宠」）；网页版保留浏览器默认右键
  window.addEventListener("contextmenu", (event) => {
    if (IS_WEB) return;
    event.preventDefault();
    window.desktop.showContextMenu();
  });

  window.addEventListener("pointermove", (event) => {
    if (!state.dragging) return;
    // 用屏幕坐标增量驱动窗口移动，避免窗口移动后画布坐标漂移；
    // 同一帧内的多次 pointermove 合并为一次 moveBy，减少透明窗口高频 setPosition 的闪烁。
    if (state.lastPointer.screenX != null) {
      state.pendingMove.dx += event.screenX - state.lastPointer.screenX;
      state.pendingMove.dy += event.screenY - state.lastPointer.screenY;
      if (!state.pendingMove.scheduled) {
        state.pendingMove.scheduled = true;
        window.requestAnimationFrame(flushPendingMove);
      }
    }
    state.lastPointer.screenX = event.screenX;
    state.lastPointer.screenY = event.screenY;
  });

  window.addEventListener("pointerup", () => {
    state.dragging = false;
    state.lastPointer.screenX = null;
    state.lastPointer.screenY = null;
    if (state.model) state.model.cursor = "grab";
  });

  window.addEventListener("wheel", (event) => {
    // 历史面板内滚动不缩放模型
    if (event.target && event.target.closest && event.target.closest("#history-panel, #chat-bar")) return;
    event.preventDefault();
    const delta = event.deltaY > 0 ? -0.01 : 0.01;
    state.scale = clamp(state.scale + delta, 0.04, 1.2);
    layoutModel();
  }, { passive: false });

  // 鼠标穿透：移动时实时判断指针是否在模型/UI 上（forward:true 保证穿透时仍收到事件）。
  // 网页版整页是普通页面，无穿透需求。
  if (!IS_WEB) {
    window.addEventListener("mousemove", (event) => {
      updateMouseThrough(event.clientX, event.clientY);
    });
  }
}

// ---------- webui /api/ws：唯一连接，与浏览器前端同源的对话通道 ----------

function connectWebui() {
  let url;
  if (IS_WEB) {
    // 网页版与页面同源：用当前地址推导 ws(s)://host/api/ws。
    const proto = location.protocol === "https:" ? "wss" : "ws";
    url = `${proto}://${location.host}/api/ws`;
    // 远程访问时集线器要求 auth_token（127.0.0.1 放行）；从登录 cookie 取。
    const host = location.hostname;
    if (host !== "127.0.0.1" && host !== "localhost") {
      const m = document.cookie.match(/(?:^|;\s*)auth_token=([^;]+)/);
      if (m) url += "?auth_token=" + encodeURIComponent(m[1]);
    }
  } else {
    const w = state.config.webui || { host: "127.0.0.1", port: 5007 };
    url = `ws://${w.host || "127.0.0.1"}:${w.port || 5007}/api/ws`;
  }
  let ws;

  const connect = () => {
    ws = new WebSocket(url);
    state.webuiWs = ws;
    ws.onopen = () => {
      console.log("[live2d] 已连接对话后端", url);
    };
    ws.onmessage = (msg) => {
      let frame;
      try {
        frame = JSON.parse(msg.data);
      } catch (err) {
        return;
      }
      handleWebuiFrame(frame);
    };
    ws.onclose = () => {
      window.setTimeout(connect, 2000); // 断线重连，便于 webui/bot 重启
    };
    ws.onerror = () => {
      try { ws.close(); } catch (e) { /* ignore */ }
    };
  };
  connect();
}

// 集线器把每条帧广播给“除发送者外的所有客户端”。等价于 webui 前端 rt()/Ne()：
//   t.message 为数组 → 其它客户端的用户消息（忽略，自己输入已本地入历史）
//   t.message 为 OneBot 动作对象 → 机器人回复，取 params.message 逐段渲染
function handleWebuiFrame(t) {
  if (!t || !t.message) return;
  const m = t.message;
  if (Array.isArray(m)) return; // 其它客户端的用户消息（自己输入已本地入历史），忽略
  const segs = extractBotSegments(m);
  if (segs.length) renderBotSegments(segs);
}

// 把一个 OneBot 动作对象摊平成 segment 数组（实时渲染与历史映射共用）。
// upload_group_file 合成一个 file 段，统一交给 renderBotSegments / segmentsToBuckets。
function extractBotSegments(m) {
  const params = (m && m.params) || {};
  switch (m && m.action) {
    case "send_group_msg":
      return Array.isArray(params.message) ? params.message : [];
    case "send_group_forward_msg": {
      const out = [];
      for (const node of params.messages || []) {
        const content = node && node.data && node.data.content;
        if (Array.isArray(content)) out.push(...content);
      }
      return out;
    }
    case "upload_group_file":
      return [{ type: "file", data: { file: params.file || params.url, name: params.name || "" } }];
    default:
      return [];
  }
}

// 把 segment 数组分类成 文本/图片/文件/标签 桶（纯函数，无副作用）。
// 图片/文件 URL 经 mediaUrl 适配宿主（桌宠 file://，网页 /api/chat/file）。
function segmentsToBuckets(segments) {
  const texts = [];
  const images = [];
  const files = [];  // {url, name}
  const labels = []; // 视频等仅文字标签
  for (const seg of segments || []) {
    if (!seg || !seg.type) continue;
    const data = seg.data || {};
    switch (seg.type) {
      case "text":
        if (data.text) texts.push(String(data.text));
        break;
      case "image": {
        const url = mediaUrl(data.file || data.url);
        if (url) images.push(url);
        break;
      }
      case "video":
        labels.push("🎬 视频");
        break;
      case "file": {
        const url = mediaUrl(data.file || data.url, data.name);
        if (url) files.push({ url, name: data.name || "" });
        break;
      }
      default:
        break; // record（bot 音频）/ at / reply / face 等忽略
    }
  }
  return { texts, images, files, labels };
}

// 把数据库历史里的一条 message 映射为历史项数组（用户消息为数组，机器人为动作对象）。
function messageToHistoryItems(message) {
  const items = [];
  if (Array.isArray(message)) {
    const { texts, images, files } = segmentsToBuckets(message);
    for (const url of images) items.push({ role: "user", kind: "image", content: url });
    const joined = texts.join("\n");
    if (joined) items.push({ role: "user", kind: "text", content: joined });
    for (const f of files) items.push({ role: "user", kind: "file", content: f.url, url: f.url, name: f.name });
  } else if (message && typeof message === "object") {
    const { texts, images, files, labels } = segmentsToBuckets(extractBotSegments(message));
    for (const url of images) items.push({ role: "bot", kind: "image", content: url });
    for (const f of files) items.push({ role: "bot", kind: "file", content: f.url, url: f.url, name: f.name });
    const joined = texts.join("\n");
    if (joined) items.push({ role: "bot", kind: "text", content: joined });
    for (const lb of labels) items.push({ role: "bot", kind: "text", content: lb });
  }
  return items;
}

// 逐段渲染机器人回复：图片→缩略+历史；视频/文件→气泡标签+历史。
// 语音不再使用 bot 下发的 record 段，而是在本地对回复文本单独合成（见下），确保 100% 出声。
// 文字处理顺序：并发“合成语音 + 判定情绪” → 二者就绪后“同时”播语音、出文本气泡、变脸。
async function renderBotSegments(segments) {
  const { texts, images, files, labels } = segmentsToBuckets(segments);

  for (const url of images) {
    showBubbleImage(url);
    addHistory("bot", "image", url);
  }

  for (const f of files) {
    showBubble("📎 文件" + (f.name ? `：${f.name}` : ""));
    addHistory("bot", "file", f.url, { name: f.name });
  }

  const joined = texts.join("\n");
  if (joined) {
    const speakText = stripParenthetical(joined); // 语音只读括号外的内容
    // 并发：本地合成语音 + 判定情绪。两者就绪后再统一触发，做到“语音/文字/表情同时”。
    const [audioBuf, plan] = await Promise.all([
      speakText
        ? synthesizeTTS(speakText).catch((e) => { console.error("[live2d] TTS 合成失败:", e); return null; })
        : Promise.resolve(null),
      classifyEmotion(joined).catch(() => null),
    ]);
    if (audioBuf) playAudioBuffer(audioBuf);
    showBubble(joined);
    addHistory("bot", "text", joined);
    if (plan) applyEmotionPlan(plan); // 变脸（含“过一会回默认”）
  }

  for (const label of labels) {
    showBubble(label);
    addHistory("bot", "text", label);
  }
}

// ---------- 表情/动作自动控制（情绪/场景 → config.yaml 索引 → 变脸/播动作） ----------
//
// 流程：对话后把回复判定为某种“情绪”（emotions 索引里的 key 之一）和可选“场景”（scenes 索引），
// 再按 runtime_config.expression.{emotions,scenes} 的绑定播放。判定优先用快速 LLM，
// 失败/超时则退回本地关键词匹配，保证常见情绪也能触发，不再“几乎只待机”。
//
// 规则：情绪相对上次变化才“变脸”（情绪不变不动脸）；动作分两类——
//   · 场景动作（如打招呼→wave）：命中即播，不受“情绪未变化”限制；
//   · 情绪动作（如 cry→tear）：仅在情绪发生变化时随表情一起播。

function applyExpression(name) {
  if (!state.model) return;
  try {
    if (name) {
      state.model.expression(name);
    } else {
      // 空名 = 恢复默认待机：清掉当前持续表情
      const em = state.model.internalModel
        && state.model.internalModel.motionManager
        && state.model.internalModel.motionManager.expressionManager;
      if (em && typeof em.resetExpression === "function") em.resetExpression();
    }
  } catch (e) { /* 某些模型缺少该表情，忽略 */ }
}

function playMotion(group) {
  if (!group || !state.model) return;
  try {
    state.model.motion(group, undefined, (PIXI.live2d.MotionPriority && PIXI.live2d.MotionPriority.NORMAL) || 2);
  } catch (e) { /* ignore */ }
}

// 本地关键词兜底：LLM 不可用时也能命中最常见的情绪/场景
function keywordClassify(text) {
  const t = String(text || "");
  const has = (re) => re.test(t);
  let emotion = "";
  let scene = "";
  if (has(/(你好|您好|早上好|早安|中午好|下午好|晚上好|在吗|在不在|嗨|哈喽|hello|hi)/i)) scene = "greeting";
  else if (has(/(再见|拜拜|晚安|下次见|回头见|bye|goodbye)/i)) scene = "farewell";
  if (has(/(呜呜|哭|泪流|想哭|伤心欲绝|哽咽)/)) emotion = "cry";
  else if (has(/(难过|委屈|失落|遗憾|抱歉|对不起|可惜|心疼)/)) emotion = "sad";
  else if (has(/(生气|讨厌|可恶|烦死|气死|哼!|怒)/)) emotion = "angry";
  else if (has(/(尴尬|无语|无言|裂开|社死)/)) emotion = "awkward";
  else if (has(/(困惑|疑惑|不懂|懵|啊\?|什么意思|为什么|怎么会)/)) emotion = "confused";
  else if (has(/(喜欢你|爱你|么么|抱抱|亲亲|宝贝|想你)/)) emotion = "love";
  else if (has(/(害羞|脸红|不好意思|羞)/)) emotion = "shy";
  else if (has(/(哇|居然|竟然|不会吧|天哪|震惊|惊讶)/)) emotion = "surprised";
  else if (has(/(嘿嘿|哼哼|得意|不过如此|小意思|略略)/)) emotion = "smug";
  else if (has(/(嘻嘻|调皮|逗你|开玩笑|吐舌|皮一下)/)) emotion = "playful";
  else if (has(/(太棒了|耶|好开心|开心|高兴|哈哈|嘿|爽|赞)/)) emotion = "happy";
  else if (scene === "greeting") emotion = "happy"; // 打招呼通常是愉快的
  return { emotion, scene };
}

// 仅“判定”情绪/场景（不落地），便于与语音合成并发；返回 {emotion, scene} 或 null。
async function classifyEmotion(text) {
  const cfg = state.config.expression || {};
  if (cfg.enable === false) return null;
  const emotions = cfg.emotions || {};
  const scenes = cfg.scenes || {};
  const emotionKeys = Object.keys(emotions);
  if (!emotionKeys.length) return null; // 没有配置索引则不动
  const t = (text || "").trim();
  if (!t) return null;

  // 先尝试 LLM 判定，失败/超时/无端点则退回关键词。
  // 桌宠：cfg.base_url 直连；网页：cfg.llm 标记服务端有端点 → 走 /live2dchat/llm 代理。
  let result = null;
  if (cfg.base_url || cfg.llm) {
    try {
      const raw = await fastLLM(cfg, buildEmotionPrompt(t, emotionKeys, Object.keys(scenes)));
      result = parseEmotionJson(raw, emotionKeys, Object.keys(scenes));
    } catch (e) { /* 失败则走关键词兜底 */ }
  }
  if (!result || (!result.emotion && !result.scene)) {
    result = keywordClassify(t);
  }
  let { emotion, scene } = result;
  if (emotion && emotionKeys.indexOf(emotion) < 0) emotion = "";
  if (scene && Object.keys(scenes).indexOf(scene) < 0) scene = "";
  return { emotion, scene };
}

// 把判定结果落地：场景动作命中即播；情绪变化才变脸，并安排“过一会回默认表情”。
function applyEmotionPlan(plan) {
  const cfg = state.config.expression || {};
  const emotions = cfg.emotions || {};
  const scenes = cfg.scenes || {};
  const { emotion, scene } = plan || {};

  // 场景动作：命中即播（不受情绪未变化限制）
  const sceneMotion = scene && scenes[scene] && scenes[scene].motion;
  if (sceneMotion) playMotion(sceneMotion);

  // 情绪 → 变脸（仅在情绪变化时）+ 情绪动作
  if (emotion && emotion !== state.lastEmotion) {
    state.lastEmotion = emotion;
    const map = emotions[emotion] || {};
    applyExpression(map.expression || "");
    if (map.motion && !sceneMotion) playMotion(map.motion); // 场景动作已播则不重复
    scheduleExpressionReset(); // 变脸后过一会恢复默认待机表情
  }
}

// 变脸后延时恢复默认待机表情（reset_delay_ms<=0 则不自动恢复）。
function scheduleExpressionReset() {
  const cfg = state.config.expression || {};
  const delay = Number.isFinite(cfg.reset_delay_ms) ? cfg.reset_delay_ms : 6000;
  if (delay <= 0) return;
  if (state.expressionResetTimer) window.clearTimeout(state.expressionResetTimer);
  state.expressionResetTimer = window.setTimeout(() => {
    applyExpression("");      // 清掉持续表情，回到默认待机
    state.lastEmotion = null; // 允许之后即便相同情绪也能再次触发变脸
  }, delay);
}

function buildEmotionPrompt(text, emotionKeys, sceneKeys) {
  const parts = [
    "你是 Live2D 桌宠的情绪识别器。阅读下面这句【角色台词】，判断说话者当前的情绪，并识别是否属于某种聊天场景。",
    "只输出一行 JSON，不要任何解释：{\"emotion\":\"<情绪>\",\"scene\":\"<场景或空字符串>\"}",
    "emotion 只能从这些英文标签里精确选一个：" + emotionKeys.join(", "),
    "scene 只能为以下之一或空字符串：" + (sceneKeys.length ? sceneKeys.join(", ") + ", \"\"" : "\"\""),
    "若情绪不明显请用 neutral。",
    "【角色台词】" + text,
  ];
  return parts.join("\n");
}

function parseEmotionJson(raw, emotionKeys, sceneKeys) {
  const m = String(raw || "").match(/\{[^{}]*\}/);
  if (!m) return { emotion: "", scene: "" };
  let obj;
  try {
    obj = JSON.parse(m[0]);
  } catch (e) {
    return { emotion: "", scene: "" };
  }
  let emotion = String(obj.emotion || "").trim().toLowerCase();
  let scene = String(obj.scene || "").trim().toLowerCase();
  if (emotionKeys.indexOf(emotion) < 0) emotion = "";
  if (sceneKeys.indexOf(scene) < 0) scene = "";
  return { emotion, scene };
}

async function fastLLM(cfg, prompt) {
  // 网页版：经服务端 /live2dchat/llm 代理（api_key 不下发浏览器）
  if (IS_WEB) {
    try {
      const resp = await fetch("/live2dchat/llm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt }),
      });
      const data = await resp.json();
      return data.choices[0].message.content;
    } catch (e) {
      return null;
    }
  }
  const url = cfg.base_url.replace(/\/+$/, "") + "/chat/completions";
  const headers = { "Content-Type": "application/json" };
  if (cfg.api_key) headers.Authorization = "Bearer " + cfg.api_key;
  const body = {
    model: cfg.model || "gpt-4o-mini",
    messages: [{ role: "user", content: prompt }],
    temperature: 0.3,
    max_tokens: 60,
    stream: false,
  };
  // 加超时：避免端点缓慢/无响应时阻塞“先变脸再说话”的整条链路（语音/文字会被一直卡住）
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 2500);
  try {
    const resp = await fetch(url, { method: "POST", headers, body: JSON.stringify(body), signal: controller.signal });
    const data = await resp.json();
    return data.choices[0].message.content;
  } catch (e) {
    return null;
  } finally {
    window.clearTimeout(timer);
  }
}

// ---------- 聊天输入条 ----------

function setupChatUI() {
  const chatEnabled = !state.config.chat || state.config.chat.enable !== false;
  const bar = document.getElementById("chat-bar");
  if (!chatEnabled) {
    if (bar) bar.style.display = "none";
    return;
  }
  const input = document.getElementById("chat-input");
  const sendBtn = document.getElementById("chat-send");

  const sendChat = () => {
    const text = (input.value || "").trim();
    if (!text) return;
    const ws = state.webuiWs;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      showBubble("未连接到对话后端(/api/ws)，无法发送。");
      return;
    }
    // 与 webui 前端完全一致：首元素携带 msg_id，随后自动注入 @机器人 段（qq=1000000 命中
    // core_reply 的“被@必回”），再附文本段。
    const payload = [
      { msg_id: Date.now() },
      { type: "at", data: { qq: "1000000", name: "Eridanus" } },
      { type: "text", data: { text } },
    ];
    ws.send(JSON.stringify(payload));
    addHistory("user", "text", text);
    input.value = "";
  };

  sendBtn.addEventListener("click", sendChat);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendChat();
    }
  });

  // 历史面板开关
  const panel = document.getElementById("history-panel");
  document.getElementById("history-toggle").addEventListener("click", () => {
    panel.classList.toggle("open");
    if (panel.classList.contains("open")) renderHistory();
  });
  document.getElementById("history-close").addEventListener("click", () => panel.classList.remove("open"));
  document.getElementById("history-clear").addEventListener("click", () => {
    state.history = [];
    saveHistory();
    renderHistory();
  });
}

// ---------- 历史对话（桌宠：localStorage；网页版：复用 WebUI 数据库） ----------

const HISTORY_KEY = "live2d_history";
const HISTORY_MAX = 300;

async function loadHistory() {
  if (IS_WEB) {
    // 网页版：拉 WebUI 的对话数据库（与网页前端同一份记录）。需该浏览器已登录 WebUI
    // 以带上 auth cookie；未登录则返回 Unauthorized，这里安静地从空历史开始。
    try {
      const resp = await fetch("/api/chat/get_history?start=0&end=" + (HISTORY_MAX - 1), { credentials: "include" });
      const data = await resp.json();
      const rows = (data && data.data) || [];
      const items = [];
      // 数据库按 msg_id（时间）倒序返回，这里反转为正序后逐条映射成历史项。
      for (const row of rows.slice().reverse()) {
        let rec;
        try { rec = JSON.parse(row[0]); } catch (e) { continue; }
        for (const it of messageToHistoryItems(rec.message)) {
          it.ts = rec.message_id || 0;
          items.push(it);
        }
      }
      state.history = items.slice(-HISTORY_MAX);
    } catch (e) {
      console.warn("[live2d] 历史加载失败（可能未登录 WebUI）:", e);
      state.history = [];
    }
    return;
  }
  try {
    state.history = JSON.parse(window.localStorage.getItem(HISTORY_KEY) || "[]");
  } catch (e) {
    state.history = [];
  }
}

function saveHistory() {
  if (IS_WEB) return; // 网页版：集线器已把消息落库，无需另存
  try {
    window.localStorage.setItem(HISTORY_KEY, JSON.stringify(state.history.slice(-HISTORY_MAX)));
  } catch (e) { /* ignore */ }
}

function addHistory(role, kind, content, extra) {
  if (!state.history) state.history = [];
  state.history.push({ role, kind, content, ts: Date.now(), ...(extra || {}) });
  if (state.history.length > HISTORY_MAX) state.history = state.history.slice(-HISTORY_MAX);
  saveHistory();
  const panel = document.getElementById("history-panel");
  if (panel && panel.classList.contains("open")) renderHistory();
}

// 从 URL（file:// / http / data:）取字节并弹原生保存对话框另存。
// 渲染端 webSecurity:false，可直接 fetch 上述三类来源。
async function downloadUrl(url, suggestedName) {
  if (!url) return;
  try {
    const resp = await fetch(url);
    const buf = await resp.arrayBuffer();
    let name = suggestedName;
    if (!name) {
      const clean = String(url).split(/[?#]/)[0];
      name = decodeURIComponent(clean.split("/").pop() || "") || "download";
    }
    await window.desktop.saveFile(name, new Uint8Array(buf));
  } catch (err) {
    console.error("[live2d] 下载失败:", err);
    showBubble("保存失败：" + (err && err.message ? err.message : err));
  }
}

function renderHistory() {
  const log = document.getElementById("history-log");
  if (!log) return;
  log.innerHTML = "";
  for (const item of state.history || []) {
    const line = document.createElement("div");
    line.className = `h-line ${item.role === "user" ? "h-user" : "h-bot"}`;
    if (item.kind === "image") {
      const img = document.createElement("img");
      img.src = item.content;
      img.style.cursor = "pointer";
      img.title = "点击保存图片";
      img.addEventListener("click", () => downloadUrl(item.content, item.name));
      line.appendChild(img);
    } else if (item.kind === "file") {
      // 文件：可点的「📎 文件名」，点击弹保存对话框另存
      line.textContent = "📎 " + (item.name || "文件");
      line.style.cursor = "pointer";
      line.title = "点击保存文件";
      line.addEventListener("click", () => downloadUrl(item.url || item.content, item.name));
    } else {
      line.textContent = item.content;
    }
    log.appendChild(line);
  }
  log.scrollTop = log.scrollHeight;
}

// ---------- 鼠标穿透：仅模型与 UI 可交互，透明区域点击直达桌面 ----------

function isInteractiveAt(clientX, clientY) {
  if (state.dragging) return true;
  // 命中 UI（输入条 / 历史面板）
  const el = document.elementFromPoint(clientX, clientY);
  if (el && el.closest && el.closest("#chat-bar, #history-panel")) return true;
  // 命中模型包围盒
  if (state.model) {
    try {
      const b = state.model.getBounds();
      const pad = 6;
      if (clientX >= b.x - pad && clientX <= b.x + b.width + pad &&
          clientY >= b.y - pad && clientY <= b.y + b.height + pad) {
        return true;
      }
    } catch (e) { /* ignore */ }
  }
  return false;
}

function updateMouseThrough(clientX, clientY) {
  const interactive = isInteractiveAt(clientX, clientY);
  const ignore = !interactive;
  if (ignore !== state.ignoringMouse) {
    state.ignoringMouse = ignore;
    window.desktop.setIgnoreMouse(ignore);
  }
}

// ---------- 启动 ----------

async function boot() {
  state.config = await window.desktop.getConfig();
  state.scale = (state.config.window && state.config.window.scale) || 0.18;
  if (Array.isArray(state.config.lip_sync_parameter_ids) && state.config.lip_sync_parameter_ids.length) {
    state.lipSyncIds = state.config.lip_sync_parameter_ids;
  }

  // 不用 resizeTo:window：透明无边框窗口被拖动时 Electron 偶发派发 resize，
  // 配合 autoDensity 会让画布逐帧累积放大（用户观察到的“每次闪烁都会变长”）。
  // 改为显式给定初始尺寸 + 受控 resize（仅在逻辑尺寸真正变化时执行）。
  state.lastSize = { w: window.innerWidth, h: window.innerHeight };
  state.app = new PIXI.Application({
    view: canvas,
    backgroundAlpha: 0,
    antialias: true,
    width: window.innerWidth,
    height: window.innerHeight,
    autoDensity: true,
    resolution: window.devicePixelRatio || 1,
  });

  // 每帧手动驱动 Live2D 更新（模型以 autoUpdate:false 加载）。app 渲染循环本就在跑，
  // 在同一循环里 update，避免依赖 Ticker.shared 是否启动，是“加载成功却空白”的根因修复。
  state.app.ticker.add(() => {
    if (state.model) {
      try { state.model.update(state.app.ticker.deltaMS); } catch (e) { /* ignore */ }
    }
    positionBubble(); // 气泡可见时持续贴着模型头顶（缩放/拖动后也跟随）
  });

  await loadHistory();
  bindGlobalInteractions();
  setupChatUI();
  // 网页版：宽屏聊天记录常驻展开（右侧整列）；窄屏（移动端）默认折叠，只留输入条，
  // 由 📜 按钮打开历史抽屉。渲染端仅在面板 .open 时随新消息刷新，故这里按宽度决定初始态。
  const hp = document.getElementById("history-panel");
  if (IS_WEB) {
    if (hp && window.innerWidth >= 768) hp.classList.add("open");
    bindWebTouchAndZoom();
  }
  if (hp && hp.classList.contains("open")) renderHistory();
  window.addEventListener("resize", resizeApp);

  await loadModel(state.config.model_url);
  connectWebui();    // 唯一连接：webui 的 /api/ws（对话 + 表情/动作由回复内容在本地驱动）
}

boot().catch((err) => {
  console.error("[live2d] 启动失败:", err);
  setStatus(`启动失败：${err && err.message ? err.message : err}`);
});
