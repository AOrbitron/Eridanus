"""
Live2D 桌宠插件。

把 Live2D 模型直接展示在桌面（透明、无边框、置顶的桌宠窗口），而非 webui。
渲染层是一个 Electron 应用（run/live2d/desktop），由本插件按需拉起。

桌宠是 **webui 后端（/api/ws, 5007）的一个纯客户端**，与浏览器前端对话完全同源：
渲染端只连这一个连接，发送自动 @机器人 的虚拟群消息，经 webui 后端→插件管线→回复
原路返回。表情/动作完全在渲染端本地驱动：收到文字回复后，按“当前模型实际可用的
表情/动作”用一个快速 LLM 自动挑选并播放（换任何模型都自适应，无需改代码）。
本插件不再使用任何到 onebot 实现(bot1)的旁路连接或本地桥接服务。

默认关闭，需手动开启：发送 /live2d on，或把 config.yaml 的 enable 改为 true。

指令：
    /live2d on                 开启桌宠（持久化 enable=true）
    /live2d off                关闭桌宠（持久化 enable=false）
    /live2d 模型 <folder|路径>  切换模型（重启渲染窗口加载新模型，自适应其表情/动作）
    /live2d 状态               查看运行状态
"""

import atexit
import threading

from developTools.event.events import GroupMessageEvent, PrivateMessageEvent, LifecycleMetaEvent
from framework_common.framework_util.websocket_fix import ExtendBot
from framework_common.framework_util.yamlLoader import YAMLManager
from run.live2d.service.process_manager import Live2DProcessManager, find_model_entry


def _resolve_expr_endpoint(config):
    """解析表情控制用的 LLM 端点：live2d.expression 优先，否则复用 core_reply 的
    trigger_llm（快/省），再否则复用 core_reply 主 llm。让“LLM 控制表情”开箱即用。"""
    live = (config.live2d.config.get("expression", {}) or {})
    base = (live.get("base_url") or "").strip()
    key = (live.get("api_key") or "").strip()
    model = (live.get("model") or "").strip()
    enable = live.get("enable", True)
    try:
        mr = config.core_reply.config
    except Exception:
        mr = {}
    tl = (mr.get("trigger_llm") or {}) if mr else {}
    main_llm = (((mr.get("llm") or {}).get("openai")) or {}) if mr else {}
    if not base:
        base = (tl.get("base_url") or "").strip() or (main_llm.get("base_url") or "").strip()
    if not key:
        key = (tl.get("api_key") or "").strip()
        if not key:
            aks = main_llm.get("api_keys") or []
            key = (str(aks[0]).strip() if aks else "")
    if not model:
        model = (tl.get("model") or main_llm.get("model") or "gpt-4o-mini")
    # 把情绪/场景 → 表情·动作 索引一并下发给渲染端（渲染端据此变脸/播动作）
    return {
        "enable": enable,
        "base_url": base,
        "api_key": key,
        "model": model,
        "emotions": live.get("emotions", {}) or {},
        "scenes": live.get("scenes", {}) or {},
        # 变脸后回到默认待机表情的延时（ms）；<=0 表示不自动恢复
        "reset_delay_ms": live.get("reset_delay_ms", 6000),
    }


def _resolve_tts_endpoint(config):
    """解析桌宠本地语音合成端点：复用 run/tts_v2 的 gpt_sovits 配置（与 /达妮娅说 同源）。
    桌宠拿到文本后在本地直接调 GPT-SoVITS /tts 合成语音，确保语音 100% 触发，
    不再依赖 onebot bot 下发的音频。live2d.config.tts 可覆盖端点/参考音频。"""
    try:
        g = config.tts_v2.config.get("gpt_sovits", {}) or {}
    except Exception:
        g = {}
    live = (config.live2d.config.get("tts", {}) or {})
    return {
        "enable": live.get("enable", True),
        "api_base": (live.get("api_base") or g.get("api_base") or "").strip(),
        # ref_audio_path 是 TTS 服务端能访问到的路径，原样透传，不做 file:// 转换
        "ref_audio_path": live.get("ref_audio_path") or g.get("ref_audio_path") or "",
        "ref_text": live.get("ref_text") or g.get("ref_text") or "",
        "target_lang": live.get("target_lang", "zh"),
        "ref_lang": live.get("ref_lang", "zh"),
        "top_k": g.get("top_k", 15),
        "top_p": g.get("top_p", 1),
        "temperature": g.get("temperature", 1),
        "text_split_method": g.get("text_split_method", "cut5"),
        "batch_size": g.get("batch_size", 1),
        "speed_factor": g.get("speed_factor", 1),
        "streaming_mode": g.get("streaming_mode", False),
        "seed": g.get("seed", -1),
        "repetition_penalty": g.get("repetition_penalty", 1.35),
    }


def main(bot: ExtendBot, config: YAMLManager):
    cfg = config.live2d.config
    manager = Live2DProcessManager(
        cfg,
        expression_endpoint=_resolve_expr_endpoint(config),
        tts_endpoint=_resolve_tts_endpoint(config),
    )

    # bot 正常退出时同步终止 Electron 渲染进程，避免桌宠窗口残留
    # （manager.stop 内部已用 taskkill /T 整树终止，未运行时为空操作）。
    atexit.register(manager.stop)

    def _persist_enable(value: bool):
        """改写 config.yaml 的 enable 并持久化（触发 YAMLManager 保存）。"""
        new_data = dict(config.live2d.config)
        new_data["enable"] = value
        config.live2d.config = new_data  # __setattr__ 会调用 save

    def _start_async():
        """启动渲染进程（含首次 npm install），放后台线程避免阻塞插件加载。"""
        threading.Thread(target=manager.start, name="Live2DStart", daemon=True).start()

    def _restart_async():
        threading.Thread(target=manager.restart, name="Live2DRestart", daemon=True).start()

    if cfg.get("enable"):
        # 桌宠是 webui 后端(/api/ws, 5007)的**纯客户端**，与主 bot(onebot 实现)是否连接无关。
        # 插件 main() 在主 bot 连接之前就会被加载，这里直接拉起渲染窗口（和 webui 一样，
        # 不依赖主 bot 连接成功）；渲染端对 webui 的连接自带断线重连，webui 尚未就绪也会自动重试。
        bot.logger.server("🔧 Live2D 桌宠已启用，正在拉起桌面渲染窗口（不依赖主 bot 连接）…")
        _start_async()
    else:
        bot.logger.info("[Live2D] 已加载（默认关闭，发送 /live2d on 开启）")

    def _is_authorized(event):
        if not cfg.get("master_only", True):
            return True
        master = config.common_config.basic_config["master"]["id"]
        try:
            return int(event.user_id) == int(master)
        except (TypeError, ValueError):
            return str(event.user_id) == str(master)

    async def _handle(event):
        text = event.pure_text.strip()
        if not text.startswith("/live2d"):
            return
        if not _is_authorized(event):
            await bot.send(event, "你没有权限操作 Live2D 桌宠。")
            return

        args = text[len("/live2d"):].strip()

        if args in ("on", "开启", "启动"):
            _persist_enable(True)
            _start_async()
            await bot.send(event, "正在开启 Live2D 桌宠（首次启用会下载 Electron，请稍候）…")
            return

        if args in ("off", "关闭", "停止"):
            _persist_enable(False)
            manager.stop()
            await bot.send(event, "已关闭 Live2D 桌宠。")
            return

        if args in ("status", "状态"):
            running = manager.is_running()
            cur_model = cfg.get("model_path") or cfg.get("model")
            webui = cfg.get("webui", {}) or {}
            expr = _resolve_expr_endpoint(config)
            await bot.send(
                event,
                f"Live2D 桌宠状态：\n运行中：{running}\n当前模型：{cur_model}\n"
                f"对话后端：ws://{webui.get('host', '127.0.0.1')}:{webui.get('port', 5007)}/api/ws\n"
                f"表情控制：{'开启' if expr['enable'] and expr['base_url'] else '关闭'}"
                f"（{expr['model']} @ {expr['base_url'] or '未配置端点'}）",
            )
            return

        if args.startswith("模型"):
            target = args[len("模型"):].strip()
            if not target:
                await bot.send(event, "用法：/live2d 模型 <内置文件夹名 或 自定义路径>")
                return
            if not find_model_entry(target):
                await bot.send(event, f"未找到模型：{target}（该目录下需有 *.model3.json）")
                return
            # 自定义路径写入 model_path，内置名写入 model
            new_data = dict(config.live2d.config)
            if "/" in target or "\\" in target:
                new_data["model_path"] = target
            else:
                new_data["model_path"] = ""
                new_data["model"] = target
            config.live2d.config = new_data
            cfg.update(new_data)
            manager.config.update(new_data)
            # 重启渲染进程：重写 runtime_config（新模型 + 其可用表情/动作）后由渲染端加载
            _restart_async()
            await bot.send(event, f"已切换模型并重启桌宠窗口：{target}")
            return

        await bot.send(
            event,
            "Live2D 指令：\n/live2d on | off | 状态\n/live2d 模型 <folder>\n"
            "（表情/动作由桌宠按回复内容自动播放，无需手动指令）",
        )

    @bot.on(LifecycleMetaEvent)
    async def _on_lifecycle(event: LifecycleMetaEvent):
        # 仅作兜底：桌宠已在插件加载时启动，这里在主 bot（重）连接后顺带补一次，
        # 万一渲染进程曾异常退出可自愈。manager.start 内部有锁与 is_running 判断，重复调用安全。
        if cfg.get("enable") and not manager.is_running():
            _start_async()

    @bot.on(GroupMessageEvent)
    async def _on_group(event: GroupMessageEvent):
        await _handle(event)

    @bot.on(PrivateMessageEvent)
    async def _on_private(event: PrivateMessageEvent):
        await _handle(event)
