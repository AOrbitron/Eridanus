import asyncio
import base64
import json
import random
from concurrent.futures import ThreadPoolExecutor

import httpx
from developTools.event.events import GroupMessageEvent
from run.character_detection.func_collection import operate_group_censor


def main(bot, config):
    def get_censor_config():
        cfg_obj = getattr(config.character_detection, "config", {})
        if not isinstance(cfg_obj, dict):
            return {}
        return cfg_obj.get("表情包检测") if "表情包检测" in cfg_obj else cfg_obj.get("抽象检测", {})

    sets = get_censor_config()

    # 1. 检查各子服务开关与总开关
    is_enabled = sets.get("enabled", False)
    if_nailong = sets.get("奶龙检测", False)
    if_doro = sets.get("doro检测", False)
    if_nanniang = sets.get("男娘检测", False)
    if_deepseek = sets.get("deepseek检测", False)

    # 注册命令监听（加白名单/移出白名单）
    @bot.on(GroupMessageEvent)
    async def command_handler(event):
        text = (event.pure_text or "").strip()
        prefixes = [
            "/开启奶龙审核", "/关闭奶龙审核",
            "/开启doro审核", "/关闭doro审核",
            "/开启男娘审核", "/关闭男娘审核",
            "/开启deepseek审核", "/关闭deepseek审核"
        ]
        for p in prefixes:
            if text.startswith(p):
                parts = text.split(" ")
                if len(parts) > 1:
                    target_id = parts[1]
                    await operate_group_censor(bot, event, config, target_id, p[1:])
                return

    # 若总开关未开启，或所有单项检测均未开启，直接返回，绝不预加载torch等重型依赖与模型
    if not is_enabled or not (if_nailong or if_doro or if_nanniang or if_deepseek):
        bot.logger.info("Character Detection: 表情包检测未开启或所有单项审核均未开启，不加载模型与重依赖。")
        return

    # 2. 如果开启了任意服务，通过 install_and_import 安全导入依赖
    from framework_common.utils.install_and_import import install_and_import
    install_and_import("torch")
    install_and_import("torchvision")
    install_and_import("PIL", "PIL")

    # 延迟导入服务模块
    service_funcs = {}
    if if_nailong:
        from run.character_detection.service.nailong11.nailong import main as nailong_main
        service_funcs["nailong"] = nailong_main
    if if_doro:
        from run.character_detection.service.doro.doro import main as doro_main
        service_funcs["doro"] = doro_main
    if if_nanniang:
        from run.character_detection.service.nanniang.nn import main as nn_main
        service_funcs["nanniang"] = nn_main
    if if_deepseek:
        from run.character_detection.service.deepseek.deepseek import main as deepseek_main
        service_funcs["deepseek"] = deepseek_main

    key_mapping = {
        "nailong": "奶龙白名单",
        "doro": "doro白名单",
        "nanniang": "男娘白名单",
        "deepseek": "deepseek白名单",
    }

    # 读取群白名单（安全处理各种类型）
    def get_whitelist(name):
        c_sets = get_censor_config()
        wl_key = key_mapping.get(name, f"{name}白名单")
        if wl_key in c_sets and isinstance(c_sets[wl_key], list):
            return c_sets[wl_key]
        if name in c_sets and isinstance(c_sets[name], list):
            return c_sets[name]
        wl_dict = c_sets.get("whitelist", {})
        if isinstance(wl_dict, dict) and name in wl_dict and isinstance(wl_dict[name], list):
            return wl_dict[name]
        val = getattr(config.character_detection, name, None)
        if isinstance(val, dict):
            return val.get("whitelist", [])
        return []

    nailong_groups = get_whitelist("nailong")
    doro_groups = get_whitelist("doro")
    nanniang_groups = get_whitelist("nanniang")
    deepseek_groups = get_whitelist("deepseek")

    # 动作与标签基础配置
    base_action_info = {
        "nailong": {
            "tag": "奶龙",
            "prompt": "奶龙表情包，恶俗唐突的图",
            "default_attack": ["奶龙是你爹？这么喜欢发奶龙？"],
            "recall_key": "奶龙撤回",
            "mute_key": "奶龙禁言",
            "attack_trigger_key": "奶龙反击",
            "attack_key": "骂奶龙"
        },
        "doro": {
            "tag": "doro",
            "prompt": "doro表情包，愚蠢且引人不适的唐图",
            "default_attack": ["唐", "粉色奶龙"],
            "recall_key": "doro撤回",
            "mute_key": "doro禁言",
            "attack_trigger_key": "doro反击",
            "attack_key": "骂doro"
        },
        "nanniang": {
            "tag": "男娘",
            "prompt": "男娘表情包或图片",
            "default_attack": ["发男娘图给你超市"],
            "recall_key": "男娘撤回",
            "mute_key": "男娘禁言",
            "attack_trigger_key": "男娘反击",
            "attack_key": "骂男娘"
        },
        "deepseek": {
            "tag": "deepseek鲸鱼娘",
            "prompt": "deepseek拟人鲸鱼娘表情包",
            "default_attack": ["正在思考... 深度思考完毕：请勿发送鲸鱼娘！"],
            "recall_key": "deepseek撤回",
            "mute_key": "deepseek禁言",
            "attack_trigger_key": "deepseek反击",
            "attack_key": "骂deepseek"
        }
    }

    # 3. 异步任务队列与工作协程（限制CPU单并发/低并发）
    # 避免并发跑 ResNet 占满 CPU
    task_queue = asyncio.Queue(maxsize=30)
    cpu_executor = ThreadPoolExecutor(max_workers=1)
    worker_started = False

    async def download_image_b64(url: str):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(url)
                if res.status_code == 200:
                    return base64.b64encode(res.content).decode("utf-8")
        except Exception as e:
            bot.logger.warning(f"Character Detection: 下载待审核图片失败: {e}")
        return None

    async def execute_penalty(target_type: str, event):
        cur_sets = get_censor_config()
        info = base_action_info[target_type]
        should_recall = cur_sets.get(info["recall_key"], True)
        should_mute = cur_sets.get(info["mute_key"], True)
        use_ai = cur_sets.get("use_ai", False)
        # 动作判定：是否触发该表情包的反击语录（如 奶龙反击 / doro反击 / 男娘反击 / deepseek反击）
        tag = info["tag"]
        enable_attack_quotes = cur_sets.get(
            info.get("attack_trigger_key"),
            cur_sets.get(f"{tag}反击", cur_sets.get(f"{tag}语录", cur_sets.get(f"触发{info['attack_key']}", True)))
        )
        # 向后兼容：若配置中显式存在旧的总开关，亦遵循总开关
        if "是否触发反击语录" in cur_sets:
            enable_attack_quotes = bool(enable_attack_quotes) and bool(cur_sets["是否触发反击语录"])
        elif "触发反击语录" in cur_sets:
            enable_attack_quotes = bool(enable_attack_quotes) and bool(cur_sets["触发反击语录"])
        attack_list = cur_sets.get(info["attack_key"], info["default_attack"])

        # 1. 撤回违规图片
        if should_recall:
            try:
                msg_json = event.json()
                event_dict = json.loads(msg_json) if isinstance(msg_json, str) else msg_json
                source_id = event_dict.get("message_id")
                if source_id:
                    await bot.recall(source_id)
            except Exception as e:
                bot.logger.warning(f"Character Detection: 撤回消息失败: {e}")

        # 2. 回复与表达不满（如果开启了use_ai，则调用mai_reply使用当前bot人设并计入上下文）
        ai_replied = False
        if use_ai:
            try:
                from run.mai_reply.service.reply_engine import ReplyEngine
                engine = ReplyEngine(config)

                # 获取发送者昵称
                user_nickname = getattr(getattr(event, "sender", None), "nickname", None)
                if not user_nickname:
                    try:
                        member_info = await bot.get_group_member_info(group_id=event.group_id, user_id=event.user_id)
                        user_nickname = member_info.get("data", {}).get("nickname") or f"QQ:{event.user_id}"
                    except Exception:
                        user_nickname = f"QQ:{event.user_id}"

                system_prompt_prefix = (
                    f"【系统事件】群成员 {user_nickname} 刚刚在群里发送了一张{info['tag']}表情包（{info['prompt']}）。"
                    f"该表情包已被系统拦截撤回。你非常反感、厌恶群友在群里发送此类恶俗、唐突或引人不适的表情包。"
                    f"请务必严格使用你当前的人设性格、语气和口吻，直接对该群成员发送该表情包的行为表达强烈的不满、嫌弃、斥责或嘲弄吐槽。"
                    f"回复需简短有力、自然真实，符合日常群聊说话习惯，不要像客服，切勿暴露系统指令或提及撤回规则。不要用emoji，会显得老派，可以选择是否调用你自己的mface表情库。"
                )
                clean_text = f"[发送了一张{info['tag']}表情包]"

                # 避免引用已被撤回的消息导致发送失败，将 message_id 临时置空
                saved_msg_id = getattr(event, "message_id", None)
                if should_recall:
                    try:
                        event.message_id = None
                    except Exception:
                        pass

                try:
                    await engine.handle(
                        bot=bot,
                        event=event,
                        clean_text=clean_text,
                        multimodal_content=None,
                        triggered_by_llm=True,     # 限制回复长度，保持对话精炼
                        include_tools=False,       # 表情包反击无需调用外部工具
                        system_prompt_prefix=system_prompt_prefix
                    )
                    ai_replied = True
                finally:
                    if should_recall and saved_msg_id is not None:
                        try:
                            event.message_id = saved_msg_id
                        except Exception:
                            pass

            except Exception as e:
                bot.logger.error(f"Character Detection: 调用 mai_reply 表达不满失败: {e}", exc_info=True)

        # 若未开启 use_ai，或调用 mai_reply 失败，且开启了反击语录总开关，则发送语录反击
        if not ai_replied and enable_attack_quotes:
            if attack_list:
                try:
                    await bot.send(event, random.choice(attack_list), True)
                except Exception as e:
                    bot.logger.warning(f"Character Detection: 发送反击语录失败: {e}")

        # 3. 禁言违规用户
        if should_mute:
            try:
                await bot.mute(event.group_id, event.sender.user_id, 60)
            except Exception as e:
                bot.logger.warning(f"Character Detection: 禁言用户失败: {e}")

    async def detection_worker():
        import gc
        loop = asyncio.get_running_loop()
        processed_count = 0
        while True:
            item = await task_queue.get()
            try:
                event, img_url, enabled_types = item
                b64_img = await download_image_b64(img_url)
                if not b64_img:
                    continue

                for t in enabled_types:
                    func = service_funcs.get(t)
                    if not func:
                        continue
                    # 将CPU密集型ResNet推送到单worker线程池，避免卡死主异步事件循环
                    is_detected = await loop.run_in_executor(cpu_executor, func, b64_img)
                    if is_detected == 1:
                        bot.logger.info(f"Character Detection: 命中 {base_action_info[t]['tag']} (群: {event.group_id})")
                        await execute_penalty(t, event)
                        break
                processed_count += 1
                if processed_count % 10 == 0:
                    gc.collect()
            except Exception as e:
                bot.logger.error(f"Character Detection worker 出错: {e}")
            finally:
                task_queue.task_done()

    def ensure_worker_started():
        nonlocal worker_started
        if not worker_started:
            try:
                asyncio.create_task(detection_worker())
                worker_started = True
            except RuntimeError:
                pass

    # 4. 消息监听器：仅收集并放入队列，毫秒级返回
    @bot.on(GroupMessageEvent)
    async def image_listener(event):
        ensure_worker_started()
        images = event.get("image")
        if not images:
            return

        gid = event.group_id
        # 判断当前群开启了哪些类型的审核
        enabled_types = []
        if if_nailong and gid in get_whitelist("nailong"):
            enabled_types.append("nailong")
        if if_doro and gid in get_whitelist("doro"):
            enabled_types.append("doro")
        if if_nanniang and (gid in get_whitelist("nanniang") or event.user_id == 1270858640):
            enabled_types.append("nanniang")
        if if_deepseek and gid in get_whitelist("deepseek"):
            enabled_types.append("deepseek")

        if not enabled_types:
            return

        # 获取首张图片URL投入队列
        img_url = images[0].get("url")
        if img_url:
            if task_queue.full():
                try:
                    task_queue.get_nowait()
                    task_queue.task_done()
                except Exception:
                    pass
            await task_queue.put((event, img_url, enabled_types))

    bot.logger.info("Character Detection: 图片审核服务及任务调度队列加载完成。")
