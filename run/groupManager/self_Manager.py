import asyncio
import base64
import os
import random
import re
import time
from asyncio import sleep
import shutil
from pathlib import Path
import pprint
from developTools.event.events import GroupMessageEvent, PrivateMessageEvent, FriendRequestEvent, GroupRequestEvent, \
    LifecycleMetaEvent
from developTools.message.message_components import Record, Text, Image, File, Node, Mface
from framework_common.database_util.User import get_user

from developTools.utils.logger import get_logger
from framework_common.framework_util.websocket_fix import ExtendBot
from run.groupManager import group_audit_rules
from run.mai_reply.service.simple_chat import simplified_chat

logger = get_logger()

JOIN_AUDIT_PROMPT_TEMPLATE = """你是QQ群「{group_id}」的加群审核员。

本群设置的加群条件如下：
{rule}

现在有用户申请加入本群，申请信息如下：
申请人QQ号：{user_id}
申请理由：{comment}

请你严格依据上面的加群条件，判断该申请人是否符合要求，不要臆测规则以外的内容。
请先用一两句话简要说明你的判断依据，然后在回复的【最后一行】严格按以下格式输出结论，不要有多余文字：

如果符合条件、可以同意加群，输出：[JOIN: TRUE] 附上一句简短理由
如果不符合条件、应当拒绝，输出：[JOIN: FALSE] 附上一句简短理由

注意：最后一行必须且只能包含 [JOIN: TRUE] 或 [JOIN: FALSE] 其中之一，后面跟简短理由，不要输出其他格式。
"""


async def judge_group_join(bot, config, group_id, user_id, comment, rule_text):
    try:
        model = config.mai_reply.config["trigger_llm"]["model"]
        api_key = config.mai_reply.config["trigger_llm"]["api_key"]
        base_url = config.mai_reply.config["trigger_llm"]["base_url"]

        prompt = JOIN_AUDIT_PROMPT_TEMPLATE.format(
            group_id=group_id, user_id=user_id, comment=comment or "（未填写）", rule=rule_text,
        )

        summary = await simplified_chat(
            base_url,
            [{"role": "user", "content": prompt}],
            model=model,
            api_key=api_key,
            system_prompt="你是一个严格、客观的QQ群加群审核员，只依据给定条件做判断，不做无关联想。",
        )

        bot.logger.info_func(f"[加群审核] 群{group_id} 用户{user_id} AI审核结果：{summary}")

        if not summary:
            raise ValueError("AI 未返回内容")

        match = re.search(r"\[JOIN:\s*(TRUE|FALSE)\]\s*(.*)", summary, re.IGNORECASE)
        if not match:
            raise ValueError("AI 返回内容未包含有效的 JOIN 判定标识")

        return match.group(1).upper(), match.group(2).strip()

    except Exception as e:
        bot.logger.error(f"[加群审核] AI 判断失败或格式不符，回退人工处理：{e}")
        return None, None
async def delete_old_files_async(folder_path):
    """
    异步删除文件夹中过期的文件
    :param folder_path:
    :return:
    """
    current_time = time.time()
    time_threshold = 3600
    deleted_file_sizes = 0

    async def process_file(file_path) -> None:
        nonlocal deleted_file_sizes
        try:
            if file_path.endswith(".py") or file_path.endswith(".ttf") or file_path.startswith("help_menu_page"):
                #print(f"跳过文件: {file_path}")
                return None

            file_mtime = os.path.getmtime(file_path)

            if current_time - file_mtime > time_threshold:
                file_size = os.path.getsize(file_path)
                deleted_file_sizes += file_size
                await asyncio.to_thread(os.remove, file_path)
                #print(f"已删除文件: {file_path} (大小: {file_size:.2f} MB)")
        except Exception as e:
            logger.error(f"处理文件失败: {file_path} - {e}")
        deleted_file_sizes = deleted_file_sizes // (1024 ** 2)
        return None

    # 获取所有文件路径
    tasks = []
    for filename in os.listdir(folder_path):
        file_path = os.path.join(folder_path, filename)

        # 检查是否是文件（跳过文件夹）
        if os.path.isfile(file_path):
            tasks.append(process_file(file_path))

    # 等待所有文件处理任务完成
    await asyncio.gather(*tasks)

    # 统计删除的文件总大小
    return deleted_file_sizes

async def call_operate_blandwhite(bot, event, config, target_id, type):
    if type == "添加群黑名单":
        await call_operate_group_blacklist(bot, event, config, target_id, True)
    elif type == "删除群黑名单":
        await call_operate_group_blacklist(bot, event, config, target_id, False)
    elif type == "添加群白名单":
        await call_operate_group_whitelist(bot, event, config, target_id, True)
    elif type == "取消群白名单":
        await call_operate_group_whitelist(bot, event, config, target_id, False)
    elif type == "添加用户黑名单":
        await call_operate_user_blacklist(bot, event, config, target_id, True)
    elif type == "取消用户黑名单":
        await call_operate_user_blacklist(bot, event, config, target_id, False)
    elif type == "添加用户白名单":
        await call_operate_user_whitelist(bot, event, config, target_id, True)
    elif type == "取消用户白名单":
        await call_operate_user_whitelist(bot, event, config, target_id, False)


async def call_operate_user_blacklist(bot, event, config, target_user_id, status):
    if str(target_user_id)==str(config.common_config.basic_config["master"]['id']):
        return {"msg": "你不能拉黑自己的管理员！"}

    user_info = await get_user(event.user_id, event.sender.nickname)
    if user_info.permission >= config.common_config.basic_config["user_handle_logic_operate_level"]:
        if status:
            if target_user_id not in config.common_config.censor_user["blacklist"]:
                config.common_config.censor_user["blacklist"].append(target_user_id)
                config.save_yaml("censor_user", plugin_name="common_config")
            await bot.send(event, f"已将{target_user_id}加入黑名单")
        else:
            try:
                config.common_config.censor_user["blacklist"].remove(target_user_id)
                config.save_yaml("censor_user", plugin_name="common_config")
                await bot.send(event, f"{target_user_id} 已被移出黑名单")
            except ValueError:
                await bot.send(event, f"{target_user_id} 不在黑名单中")
    else:
        await bot.send(event, f"你没有足够权限执行此操作")


async def call_operate_user_whitelist(bot, event, config, target_user_id, status):
    user_info = await get_user(event.user_id, event.sender.nickname)
    if user_info.permission >= config.common_config.basic_config["user_handle_logic_operate_level"]:
        if status:
            if target_user_id not in config.common_config.censor_user["whitelist"]:
                config.common_config.censor_user["whitelist"].append(target_user_id)
                config.save_yaml("censor_user", plugin_name="common_config")
            await bot.send(event, f"已将{target_user_id}加入白名单")
        else:
            try:
                config.common_config.censor_user["whitelist"].remove(target_user_id)
                config.save_yaml("censor_user", plugin_name="common_config")
                await bot.send(event, f"{target_user_id} 已被移出白名单")
            except ValueError:
                await bot.send(event, f"{target_user_id} 不在白名单中")
    else:
        await bot.send(event, f"你没有足够权限执行此操作")


async def call_operate_group_blacklist(bot, event, config, target_group_id, status):
    user_info = await get_user(event.user_id, event.sender.nickname)
    if user_info.permission >= config.common_config.basic_config["group_handle_logic_operate_level"]:
        if status:
            if target_group_id not in config.common_config.censor_group["blacklist"]:
                config.common_config.censor_group["blacklist"].append(target_group_id)
                config.save_yaml("censor_group", plugin_name="common_config")
            await bot.send(event, f"已将群{target_group_id}加入黑名单")
        else:
            try:
                config.common_config.censor_group["blacklist"].remove(target_group_id)
                config.save_yaml("censor_group", plugin_name="common_config")
                await bot.send(event, f"已将群{target_group_id}移出黑名单")
            except ValueError:
                await bot.send(event, f"群{target_group_id} 不在黑名单中")
    else:
        await bot.send(event, f"你没有足够权限执行此操作")


async def call_operate_group_whitelist(bot, event, config, target_group_id, status):
    user_info = await get_user(event.user_id, event.sender.nickname)
    if user_info.permission >= config.common_config.basic_config["group_handle_logic_operate_level"]:
        if status:
            if target_group_id not in config.common_config.censor_group["whitelist"]:
                config.common_config.censor_group["whitelist"].append(target_group_id)
                config.save_yaml("censor_group", plugin_name="common_config")
            await bot.send(event, f"已将群{target_group_id}加入白名单")
        else:
            try:
                config.common_config.censor_group["whitelist"].remove(target_group_id)
                config.save_yaml(str("censor_group"), plugin_name="common_config")
                await bot.send(event, f"已将群{target_group_id}移出白名单")
            except ValueError:
                await bot.send(event, f"群{target_group_id} 不在白名单中")
    else:
        await bot.send(event, f"你没有足够权限执行此操作")


async def garbage_collection(bot, event, config):
    bot.logger.info_func("开始清理缓存")
    # 普通清理的文件夹（不递归，只删文件）
    normal_folders = [
        "data/pictures/galgame",
        "data/video/cache",
        "data/voice/cache",
        "run/streaming_media/service/Link_parsing/data",
        "data/pictures/benzi"
    ]
    
    # 需要递归清理的文件夹（删除文件和子目录）
    recursive_folders = [
        "data/pictures/cache",
    ]

    async def safe_delete(folder, recursive=False):
        try:
            folder_path = Path(folder)
            if not folder_path.exists():
                bot.logger.warning(f"文件夹不存在: {folder}")
                return 0

            total_deleted = await delete_old_files_async(str(folder_path))
            
            if recursive:
                for item in folder_path.iterdir():
                    if item.is_dir():
                        try:
                            size = sum(f.stat().st_size for f in item.rglob('*') if f.is_file())
                            size_mb = size // (1024 ** 2)
                            await asyncio.to_thread(shutil.rmtree, item)
                            bot.logger.info(f"已删除子目录: {item} (大小: {size_mb:.2f} MB)")
                            total_deleted += size_mb
                        except Exception as e:
                            bot.logger.error(f"删除子目录 {item} 失败: {e}")
            
            return total_deleted
        except Exception as e:
            bot.logger.error(f"处理文件夹 {folder} 时发生错误: {e}")
            return 0

    normal_tasks = [safe_delete(folder, recursive=False) for folder in normal_folders]
    recursive_tasks = [safe_delete(folder, recursive=True) for folder in recursive_folders]
    
    folder_sizes = await asyncio.gather(*normal_tasks, *recursive_tasks, return_exceptions=True)

    total_size = sum(size for size in folder_sizes if isinstance(size, (int, float)))
    bot.logger.info_func(f"本次清理了 {total_size:.2f} MB 的缓存")
    return f"本次清理了 {total_size:.2f} MB 的缓存"


async def report_to_master(bot: ExtendBot, event, config,msg):
    #if bot.id ==3552663628 or bot.id==3377428814:
        #await bot.send_group_message(1050663831, f"用户：{event.user_id}\n{msg}")
        #群u爱看
    await bot.send_friend_message(config.common_config.basic_config["master"]['id'],msg)

    return {"status": "ok"}

async def send(bot, event, config, message, delay=0):
    await asyncio.sleep(delay)
    message_list = []
    print(message)
    for i in message:
        #print(i)
        if len(i) > 1:
            for j in i:
                if "text" in j:
                    message_list.append(Text(i[j]))
                elif "image" in j:
                    message_list.append(Image(file=i[j]))
                elif "audio" in j:
                    message_list.append(Record(file=i[j]))
                elif "video" in j:
                    message_list.append(File(file=i[j]))
        else:
            if "text" in i:
                message_list.append(Text(i["text"]))
            elif "image" in i:
                message_list.append(Image(file=i["image"]))
            elif "audio" in i:
                message_list.append(Record(file=i["audio"]))
            elif "video" in i:
                message_list.append(File(file=i["video"]))
    await bot.send(event, message_list)


async def send_contract(bot, event, config):
    return {"管理员id": config.common_config.basic_config["master"]['id']}


def main(bot:ExtendBot, config):
    global send_next_message
    send_next_message = False

    @bot.on(LifecycleMetaEvent)
    async def _(event):
        async def send_heartbeat():
            group_list = await bot.get_group_list()
            group_list = group_list["data"]
            friend_list = await bot.get_friend_list()
            friend_list = friend_list["data"]

            encoded_strings = ['c2FsdF/or7vlj5bnvqTliJfooajmlbDph486IF9zYWx0',
                               'c2FsdF/or7vlj5blpb3lj4vliJfooajmlbDph486IF9zYWx0',
                               'c2FsdF/lkK/liqjmiJDlip8K5b2T5YmN576k5pWw6YePOiBfc2FsdA==',
                               'c2FsdF/lpb3lj4vmlbDph486IF9zYWx0',
                               'c2FsdF/pobnnm67lnLDlnYDkuI7mlofmoaMKaHR0cHM6Ly9lcmlkYW51cy1kb2MubmV0bGlmeS5hcHAvCuacrOmhueebrua6kOeggeWPiuS4gOmUruWMheWujOWFqOWFjei0ue+8jOWmguaCqOmAmui/h+S7mOi0uea4oOmBk+iOt+W+l++8jOaBreWWnOS9oOiiq+mql+S6huOAgl9zYWx0',
                               'c2FsdF9kYXRhL3N5c3RlbS93aW4geHAubXAzX3NhbHQ=']

            def decode_string(s):
                decoded_bytes = base64.b64decode(s)
                decoded_string = decoded_bytes.decode('utf-8')
                return decoded_string[5:-5]

            try:
                bot.logger.info(f"{decode_string(encoded_strings[0])}: {len(group_list)}")
                bot.logger.info(f"{decode_string(encoded_strings[1])} {len(friend_list)}")
                await bot.send_friend_message(config.common_config.basic_config["master"]['id'],
                                              f"{decode_string(encoded_strings[2])}{len(group_list)}\n{decode_string(encoded_strings[3])} {len(friend_list)}")
            except:
                pass
            if random.randint(1, 100) < 10:
                await bot.send_friend_message(config.common_config.basic_config["master"]['id'],
                                              Record(file=f"{decode_string(encoded_strings[5])}"))
            await bot.send_friend_message(config.common_config.basic_config["master"]['id'],
                                          f"{decode_string(encoded_strings[4])}")
        asyncio.create_task(send_heartbeat())
        while True:
            await garbage_collection(bot, event, config)
            await asyncio.sleep(5400)  # 每1.5h清理一次缓存
    @bot.on(GroupMessageEvent)
    async def groups_send(event: GroupMessageEvent):
        global send_next_message
        if event.user_id==config.common_config.basic_config["master"]['id'] and event.pure_text=="notice":
            send_next_message = True
            await bot.send(event,"下一条消息将被转发至所有群")
        elif send_next_message and event.user_id==config.common_config.basic_config["master"]['id']:
            send_next_message = False
            groups = await bot.get_group_list()
            mes_chain=[]
            for i in event.message_chain:
                if isinstance(i,Text):
                    mes_chain.append(Text(i.text))
                elif isinstance(i,Image):
                    mes_chain.append(Image(file=i.url or i.file))
                elif isinstance(i,Record):
                    mes_chain.append(Record(file=i.file or i.url))
                elif isinstance(i,File):
                    mes_chain.append(File(file=i.file or i.url))
                elif isinstance(i,Mface):
                    mes_chain.append(Mface(file=i.file or i.url))
                else:
                    mes_chain.append(i)
            #pprint.pprint(mes_chain)
            await bot.send(event,f"正在转发消息至所有群，请稍后...\n任务群数量：{len(groups['data'])}")
            for group in groups["data"]:
                try:
                    bot.logger.info(f"转发消息至群{group['group_id']}")
                    await bot.send_group_message(group["group_id"],mes_chain)
                    await sleep(4)
                except Exception as e:
                    bot.logger.error(f"发送群消息失败：{group['group_id']} 原因: {e}")
    @bot.on(GroupMessageEvent)
    async def _(event):
        if event.pure_text == "/gc":
            user_info = await get_user(event.user_id, event.sender.nickname)
            if user_info.permission >= 3:
                r = await garbage_collection(bot, event, config)
                await bot.send(event, r)

    @bot.on(FriendRequestEvent)
    async def FriendRequestHandler(event: FriendRequestEvent):
        if event.user_id in config.common_config.censor_user["blacklist"]:
            bot.logger.info_func(f"收到好友请求，{event.user_id}({event.comment}) 用户被加入黑名单，拒绝添加")
            await bot.handle_friend_request(event.flag, False, "拒绝添加好友")
            await bot.send_friend_message(config.common_config.basic_config["master"]['id'],
                                          f"收到好友请求，{event.user_id}({event.comment}) 用户被加入黑名单，拒绝添加")
        else:
            user_info = await get_user(event.user_id)
            if user_info.permission >= config.common_config.basic_config["申请bot好友所需权限"]:
   
                bot.logger.info_func(f"收到好友请求，{event.user_id}({event.comment}) 同意")
                await bot.handle_friend_request(event.flag, True, "")
                await bot.send_friend_message(config.common_config.basic_config["master"]['id'],
                                              f"收到好友请求，{event.user_id}({event.comment}) 同意")
            else:
                bot.logger.info_func(f"收到好友请求，{event.user_id}({event.comment}) 拒绝")
                await bot.handle_friend_request(event.flag, False, "你没有足够权限添加好友")
                await bot.send_friend_message(config.common_config.basic_config["master"]['id'],
                                              f"收到好友请求，{event.user_id}({event.comment}) 拒绝（用户权限不足）")

    @bot.on(GroupRequestEvent)
    async def GroupRequestHandler(event: GroupRequestEvent):
        if event.sub_type == "invite":
            if event.group_id in config.common_config.censor_group["blacklist"]:
                bot.logger.info_func(f"收到群邀请，{event.group_id}({event.comment}) 群被加入黑名单，拒绝邀请")
                await bot.send_friend_message(event.user_id, f"该群已被加入黑名单，无法加入")
                await bot.send_friend_message(config.common_config.basic_config["master"]['id'],
                                              f"收到来自{event.user_id})的群邀请，{event.group_id}({event.comment}) 群被加入黑名单，拒绝邀请")
            else:
                user_info = await get_user(event.user_id)
                if user_info.permission >= config.common_config.basic_config["邀请bot加群所需权限"]:
                    bot.logger.info_func(f"收到群邀请，{event.group_id}({event.comment}) 同意")
                    await bot.set_group_add_request(event.flag, True, "allow")
                    await bot.send_friend_message(config.common_config.basic_config["master"]['id'],
                                                  f"收到来自{event.user_id}的群邀请，{event.group_id}({event.comment}) 同意")
                else:
                    bot.logger.info_func(f"收到群邀请，{event.group_id}({event.comment}) 拒绝")
                    await bot.send_friend_message(event.user_id, f"你没有足够权限邀请bot加入该群")
                    await bot.send_friend_message(config.common_config.basic_config["master"]['id'],
                                                  f"收到来自{event.user_id}的群邀请，{event.group_id}({event.comment}) 拒绝（用户权限不足）")

        elif event.sub_type == "add":
            bot.logger.info_func(f"收到加群申请，{event.group_id} {event.comment}")

            if event.group_id in config.common_config.censor_group["blacklist"]:
                pass
                return

            rule_text = await group_audit_rules.get_rule(event.group_id)

            if not rule_text:
                # 该群没配置审核条件，走原来的人工通知逻辑
                await bot.send_group_message(
                    event.group_id,
                    f"有新的加群请求，请尽快处理\n申请人：{event.user_id}\n{event.comment}"
                )
                return

            # 该群配置了审核条件，交给AI判断
            decision, reason = await judge_group_join(
                bot, config, event.group_id, event.user_id, event.comment, rule_text
            )

            if decision == "TRUE":
                await bot.set_group_add_request(event.flag, True, "同意加群")
                await bot.send_group_message(
                    event.group_id,
                    f"新成员 {event.user_id} 已通过AI自动审核加入本群\n{reason or '理由：符合本群加群条件'}\n请求原始信息：\n{event.comment}"
                )
            elif decision == "FALSE":
                #await bot.set_group_add_request(event.flag, False, "不符合加群条件")
                await bot.send_group_message(
                    event.group_id,
                    f"已忽略 {event.user_id} 的加群申请\n{reason or '理由：不符合本群加群条件'}\n请求原始信息：\n{event.comment}"
                )
            else:
                # 兜底：AI没给出可解析结论，机器人不做任何处理，通知群内人工处理
                await bot.send_group_message(
                    event.group_id,
                    f"有新的加群请求，请尽快处理\n申请人：{event.user_id}\n{event.comment}"
                )

    @bot.on(GroupMessageEvent)
    async def GroupMessageHandler(event: GroupMessageEvent):
        if event.pure_text.startswith("加群审核设置"):
            user_d = await bot.get_group_member_info(event.group_id, event.user_id)
            if user_d["data"]["role"] in ["admin", "owner"]:
                rule = event.pure_text.replace("加群审核设置", "", 1).strip()
                if not rule:
                    await bot.send(event,
                                   "请在“加群审核设置”后面写明本群的加群条件，例如：\n加群审核设置 申请理由需说明来意，禁止纯数字/广告理由\n如需清除设置请发送：加群审核设置 清除")
                    return
                if rule in ("清除", "取消", "删除"):
                    removed = await group_audit_rules.remove_rule(event.group_id)
                    await bot.send(event, "已清除本群的加群审核设置" if removed else "本群未设置加群审核条件")
                    return
                await group_audit_rules.set_rule(event.group_id, rule, operator_id=event.user_id)
                await bot.send(event, f"已设置本群加群审核条件：\n{rule}\n此后加群申请将由AI依据该条件自动审核")
            else:
                await bot.send(event, "只有群管理员/群主可以设置加群审核条件")

    @bot.on(GroupMessageEvent)
    async def black_and_white_handler(event: GroupMessageEvent):
        await _handler(event)

    @bot.on(PrivateMessageEvent)
    async def black_and_white_handler(event):
        await _handler(event)

    async def _handler(event):
        if event.pure_text.startswith("/bl add "):
            try:
                target_user_id = int(event.pure_text.split(" ")[2])
            except:
                await bot.send(event, f"请输入正确的用户id")
                return
            await call_operate_user_blacklist(bot, event, config, target_user_id, True)
        elif event.pure_text.startswith("/bl remove "):
            try:
                target_user_id = int(event.pure_text.split(" ")[2])
            except:
                await bot.send(event, f"请输入正确的用户id")
                return
            await call_operate_user_blacklist(bot, event, config, target_user_id, False)
        elif event.pure_text.startswith("/blgroup add "):
            try:
                target_group_id = int(event.pure_text.split(" ")[2])
            except:
                await bot.send(event, f"请输入正确的群号")
                return
            await call_operate_group_blacklist(bot, event, config, target_group_id, True)
        elif event.pure_text.startswith("/blgroup remove "):
            try:
                target_group_id = int(event.pure_text.split(" ")[2])
            except:
                await bot.send(event, f"请输入正确的群号")
                return
            await call_operate_group_blacklist(bot, event, config, target_group_id, False)
        elif event.pure_text.startswith("/wl add "):
            try:
                target_user_id = int(event.pure_text.split(" ")[2])
                await call_operate_user_whitelist(bot, event, config, target_user_id, True)
            except:
                await bot.send(event, f"请输入正确的用户id")
                return
        elif event.pure_text.startswith("/wl remove "):
            try:
                target_user_id = int(event.pure_text.split(" ")[2])
                await call_operate_user_whitelist(bot, event, config, target_user_id, False)
            except:
                await bot.send(event, f"请输入正确的用户id")
                return
        elif event.pure_text.startswith("/wlgroup add "):
            try:
                target_group_id = int(event.pure_text.split(" ")[2])
                await call_operate_group_whitelist(bot, event, config, target_group_id, True)
            except:
                await bot.send(event, f"请输入正确的群号")
        elif event.pure_text.startswith("/wlgroup remove "):
            try:
                target_group_id = int(event.pure_text.split(" ")[2])
                await call_operate_group_whitelist(bot, event, config, target_group_id, False)
            except:
                await bot.send(event, f"请输入正确的群号")
