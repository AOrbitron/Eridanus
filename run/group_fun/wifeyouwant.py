import asyncio
import datetime
import os
import random
import re
from sre_parse import CATEGORIES
import threading
import traceback
from asyncio import sleep
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import weakref
import gc
import pprint
import aiosqlite
import httpx
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from developTools.event.events import GroupMessageEvent, LifecycleMetaEvent
from developTools.message.message_components import Node, Text, Image, At
from run.group_fun.service.wife_you_want import manage_group_status, manage_group_add, \
    manage_group_check, PIL_lu_maker, \
    run_async_task, today_check_api, query_group_users, add_or_update_user_collect


WORDS_MAPPING = {
    '今日一言': 'yan',
    '答案之书': 'yan',
    '每日一言': 'yan',
    'emo时刻': 'emo',
    'emo了': 'emo',
    '网抑云': 'emo',
    'wyy评论': 'wyy', 
    '网易云评论': 'wyy',
    '舔狗日记': 'dog'
}

CATEGORIES_MAPPING = {
    'yan': '今日一言',
    'emo': 'emo时刻',
    'wyy': 'wyy评论',
    'dog': '舔狗日记'
}

def main(bot, config):
    global last_messages, membercheck, filepath

    # 使用有限大小的双端队列
    last_messages = {}
    filepath = 'data/pictures/cache'
    if not os.path.exists(filepath):
        os.makedirs(filepath)

    membercheck = {}

    # 启动定时清理任务
    scheduler = BackgroundScheduler()
    scheduler.add_job(run_async_task, trigger=CronTrigger(hour=0, minute=0))

    def cleanup_memory():
        """定期清理内存中的无用数据"""
        global last_messages, membercheck

        try:
            current_time = datetime.now().timestamp()
            expired_keys = []

            for key, (timestamp, _) in list(membercheck.items()):
                if current_time - timestamp > 600:  # 10分钟
                    expired_keys.append(key)

            for key in expired_keys:
                membercheck.pop(key, None)

            if len(last_messages) > 100:
                sorted_groups = sorted(last_messages.keys())
                groups_to_remove = sorted_groups[:-100]
                for group_id in groups_to_remove:
                    last_messages.pop(group_id, None)

            # 强制垃圾回收
            gc.collect()

            bot.logger.info(f"内存清理完成，membercheck: {len(membercheck)}, last_messages: {len(last_messages)}")

        except Exception as e:
            bot.logger.error(f"内存清理失败: {e}")
    scheduler.add_job(cleanup_memory, trigger=CronTrigger(minute=0))  # 每小时清理一次
    scheduler.start()

    today_wife_api, header = config.group_fun.config["today_wife"]["api"], config.group_fun.config["today_wife"][
        "header"]



    @bot.on(GroupMessageEvent)
    async def today_wife(event: GroupMessageEvent):
        async with httpx.AsyncClient(timeout=30.0) as client:
            if not event.pure_text.startswith("今") or not config.group_fun.config["today_wife"]["今日老婆"]:
                return

            if ('今日' in str(event.pure_text) or '今天' in str(event.pure_text)) and '老婆' in str(event.pure_text):
                bot.logger.info("今日老婆开启！")

                if '张' in str(event.pure_text) or '个' in str(event.pure_text) or '位' in str(event.pure_text):
                    cmList = []
                    context = str(event.pure_text)
                    name_id_number = re.search(r'\d+', context)
                    if name_id_number:
                        number = int(name_id_number.group())
                        if number > 5:
                            await bot.send(event, '数量过多，渣男！！！！')
                            return

                    # 批量处理图片，避免多次创建临时文件
                    for i in range(number):
                        try:
                            response = await today_check_api(today_wife_api, header)
                            temp_path = f'{filepath}/today_wife_{i}.jpg'
                            with open(temp_path, 'wb') as file:
                                file.write(response.content)
                            bot.logger.info(f"api获取到第{i + 1}个老婆！")
                            cmList.append(Node(content=[Image(file=temp_path)]))
                        except Exception as e:
                            bot.logger.error(f"获取图片失败: {e}")
                            continue

                    if cmList:
                        cmList.append(Node(content=[Text(f'漫朔今日老婆图床地址：https://web.manshuo.ink/today-wife')]))
                        await bot.send(event, cmList)

                    # 清理临时文件
                    for i in range(number):
                        temp_path = f'{filepath}/today_wife_{i}.jpg'
                        try:
                            if os.path.exists(temp_path):
                                os.remove(temp_path)
                        except Exception:
                            pass
                else:
                    try:
                        response = await today_check_api(today_wife_api, header)
                        img_path = f'{filepath}/today_wife.jpg'
                        with open(img_path, 'wb') as file:
                            file.write(response.content)
                        await bot.send(event, Image(file=img_path))

                        # 清理临时文件
                        try:
                            if os.path.exists(img_path):
                                os.remove(img_path)
                        except Exception:
                            pass
                    except Exception as e:
                        bot.logger.error(f"获取今日老婆失败: {e}")


    @bot.on(GroupMessageEvent)
    async def api_collect(event: GroupMessageEvent):
        async with httpx.AsyncClient(timeout=30.0) as client:
            flag = 0
            url = None
            text = str(event.pure_text)
            
            if text in WORDS_MAPPING:
                category = WORDS_MAPPING[text]
                flag = 1
                bot.logger.info(CATEGORIES_MAPPING[category])
                if category == 'dog':
                    url = 'https://openapi.dwo.cc/api/dog'
                else:
                    url = f'https://openapi.dwo.cc/api/yi?api={category}&type=json'
            
            if flag == 1 and url:
                try:
                    response = await client.get(url)
                    data = response.json()
                    context = data['data'] if 'data' in data else data['text']
                    await bot.send(event, context)
                except Exception as e:
                    bot.logger.error(f"API请求失败: {e}")
                    await bot.send(event, 'api出错了喵')


    @bot.on(GroupMessageEvent)
    async def today_group_owner(event: GroupMessageEvent):
        flag_persona = 0
        target_id = None

        if event.message_chain.has(At):
            try:
                if '今日群友' in event.processed_message[0]['text'] or '今日老婆' in event.processed_message[0]['text'] or '今日' == str(event.pure_text):
                    target_id = event.message_chain.get(At)[0].qq
                    flag_persona = 3
            except Exception:
                pass
        elif '今日群主' == str(event.pure_text):
            flag_persona = 1
            check = 'owner'
        elif '今日管理' == str(event.pure_text):
            flag_persona = 2
            check = 'admin'
        elif '今日群友' == str(event.pure_text):
            flag_persona = 3

        if flag_persona != 0:
            bot.logger.info("今日群主or群友任务开启")
            target_group = int(event.group_id)

            if target_id is None:
                try:
                    friendlist_get = await bot.get_group_member_list(event.group_id)
                    data_count = len(friendlist_get["data"])

                    if flag_persona in [2, 3, 4, 5] and data_count > 1000:
                        await bot.send(event, '抱歉，群聊人数过多，bot服务压力过大，仅开放今日群主功能，谢谢')
                        return

                    friendlist = []
                    for friend in friendlist_get["data"]:
                        data_check = friend['role']
                        if flag_persona in [1, 2, 5] and data_check == check:
                            friendlist.append(friend['user_id'])
                            if flag_persona in [1, 5] and data_check == 'owner':
                                break
                        elif flag_persona in [3, 4]:
                            friendlist.append(friend['user_id'])

                    if friendlist:
                        target_id = random.choice(friendlist)
                    else:
                        await bot.send(event, '未找到合适的目标')
                        return

                except Exception as e:
                    bot.logger.error(f"获取群成员列表失败: {e}")
                    return

            try:
                #pprint.pprint((await bot.get_group_member_info(target_group, target_id))['data'])
                today_wife_api, header = config.group_fun.config["today_wife"]["api"], config.group_fun.config["today_wife"]["header"]
                response = await today_check_api(today_wife_api, header)
                img_path = f'data/pictures/wife_you_want_img/today_wife.jpg'

                with open(img_path, 'wb') as file:
                    file.write(response.content)

                if config.group_fun.config["today_wife"]["is_at"]:
                    await bot.send_group_message(target_group, [f'这里是今天的 ', At(qq=target_id), f' 哟~~~\n',
                                                                Image(file=img_path)])
                else:
                    target_name = (await bot.get_group_member_info(target_group, target_id))['data']['nickname']
                    await bot.send(event, [f'这里是今天的 {target_name} 哟~~~\n', Image(file=img_path)])

                # 清理临时文件
                try:
                    if os.path.exists(img_path):
                        os.remove(img_path)
                except Exception:
                    pass

            except Exception as e:
                bot.logger.error(f"处理今日群友失败: {e}")
                traceback.print_exc()

    handler = GroupFunHandler(bot, config)
    @bot.on(GroupMessageEvent)
    async def today_wife_recall(event: GroupMessageEvent):

        await handler.handle_message(event)


import random
import re
import os
from asyncio import sleep


class GroupFunHandler:
    """群娱乐功能处理器"""

    def __init__(self, bot, config):
        self.bot = bot
        self.config = config.group_fun.config["today_wife"]
        self.wife_prefix = self.config["wifePrefix"]

        # 命令映射
        self.command_map = {
            '透群主': {'persona': 1, 'check': 'owner'},
            '透管理': {'persona': 2, 'check': 'admin'},
            '透群友': {'persona': 3, 'check': None},
            #'透': {'persona': 3, 'check': None},
            '娶群友': {'persona': 4, 'check': None},
            '离婚': {'persona': 'divorce', 'check': None},
            '/今日群主': {'persona': 5, 'check': 'owner'}
        }

        # 拒绝回复列表
        self.reject_replies = [
            '不许瑟瑟！！！！', '你是坏蛋！！', '色色是不允许的！', '不给！',
            '笨蛋哥哥', '为什么不是我？', '看着我啊，我才不会帮你呢！', '逃跑喵'
        ]

    async def handle_message(self, event):
        """主消息处理入口"""
        context = event.pure_text or event.raw_message
        if event.message_chain.has(At) and event.message_chain.has(Text):
            userid, context = event.message_chain.get(At)[0].qq, event.message_chain.get(Text)[0].text
            context = f'{context} {userid}'
            #print(context)
        # 检查前缀 - 如果前缀不匹配，直接返回，不执行任何后续逻辑
        if not context or not context.startswith(self.wife_prefix):
            return

        self.bot.logger.debug(f"透群友功能触发，消息内容: {context}")

        # 处理记录查询
        if self._is_record_query(context):
            self.bot.logger.debug("处理记录查询")
            await self._handle_record_query(event)
            return

        # 处理透群友相关命令
        self.bot.logger.debug("处理透群友命令")
        await self._handle_wife_commands(event, context)

    def _is_record_query(self, context):
        """判断是否为记录查询"""
        return ('记录' in context and
                any(keyword in context for keyword in ['色色', '瑟瑟', '涩涩']))

    async def _handle_wife_commands(self, event, context):
        """处理透群友相关命令"""
        # 解析命令 - 如果没有匹配的命令，直接返回
        command_info = self._parse_command(context)
        if not command_info:
            return

        # 更新热门群友统计
        await self._update_hot_member_stats(event)

        # 处理离婚特殊情况
        if command_info['persona'] == 'divorce':
            await self._handle_divorce(event)
            return

        # 处理透群友逻辑
        await self._handle_wife_action(event, context, command_info)

    async def _update_hot_member_stats(self, event):
        """更新热门群友统计"""
        if not self.config["仅热门群友"]:
            return

        try:
            target_group = int(event.group_id)
            from_id = int(event.sender.user_id)
            count_check = await manage_group_status(from_id, target_group, 'group_owner_record')
            await manage_group_status(from_id, target_group, 'group_owner_record', (count_check or 0) + 1)
        except Exception as e:
            self.bot.logger.error(f"更新热门群友统计失败: {e}")

    def _parse_command(self, context):
        """解析命令类型"""
        for keyword, info in self.command_map.items():
            if keyword in context:
                return info
        return None

    async def _handle_divorce(self, event):
        """处理离婚命令"""
        try:
            from_id = int(event.sender.user_id)
            target_group = int(event.group_id)

            if await manage_group_status(from_id, target_group, 'wife_you_get') != 0:
                await manage_group_status(from_id, target_group, 'wife_you_get', 0)
                await self.bot.send(event, '离婚啦，您现在是单身贵族咯~')
        except Exception as e:
            self.bot.logger.error(f"离婚处理失败: {e}")

    async def _handle_wife_action(self, event, context, command_info):
        """处理透群友行为"""
        persona = command_info['persona']

        # 随机拒绝 (5%概率)
        if random.randint(1, 20) == 1:
            await self.bot.send(event, random.choice(self.reject_replies))
            return

        from_id = int(event.sender.user_id)
        target_group = int(event.group_id)

        # 获取目标用户
        target_id, existing_wife = await self._get_target_user(event, context, persona, from_id, target_group)
        if not target_id:
            return

        # 检查重婚
        if persona == 4 and existing_wife and target_id != existing_wife:
            await self.bot.send(event, '渣男！吃着碗里的想着锅里的！', True)
            return

        # 执行透群友功能
        await self._execute_wife_action(event, persona, target_id, from_id, target_group, command_info['check'])

    async def _get_target_user(self, event, context, persona, from_id, target_group):
        """获取目标用户ID"""
        existing_wife = None
        #print(context)
        # 处理娶群友的特殊逻辑
        if persona == 4:
            try:
                existing_wife = await manage_group_status(from_id, target_group, 'wife_you_get')
                if existing_wife != 0:
                    return existing_wife, existing_wife
            except Exception:
                pass
        #print(context)
        # 解析指定目标
        target_id = await self._parse_target_from_context(event, context, persona)
        #print(target_id)
        if target_id:
            # 验证目标用户 (85%概率通过)
            if random.randint(1, 20) > 3:
                if await self._validate_target_user(target_group, target_id):
                    return target_id, existing_wife

        # 随机选择目标
        return await self._get_random_target(event, persona, target_group), existing_wife

    async def _parse_target_from_context(self, event, context, persona):
        """从上下文解析目标用户"""
        if persona not in [3, 4] or any(keyword in context for keyword in ["管理", "群主"]):
            return None

        # 解析数字ID
        name_id_number = re.search(r'\d+', context)
        if name_id_number:
            return int(name_id_number.group())

        # 按昵称搜索
        # search_term = self._extract_search_term(context)
        # if search_term:
        #     return await self._search_member_by_name(event.group_id, search_term)

        return None

    def _extract_search_term(self, context):
        """提取搜索关键词"""
        if "群友" in context:
            return None

        for keyword in ["透", "娶"]:
            if keyword in context:
                index = context.find(keyword)
                return context[index + len(keyword):]
        return None

    async def _search_member_by_name(self, group_id, search_term):
        """根据昵称搜索群成员"""
        try:
            friendlist_get = await self.bot.get_group_member_list(group_id)
            for friend in friendlist_get["data"]:
                friend_names = [name for name in [friend.get("nickname"), friend.get("card")] if name]
                if any(search_term == name for name in friend_names):
                    return friend['user_id']
        except Exception as e:
            self.bot.logger.error(f"搜索群友失败: {e}")
        return None

    async def _validate_target_user(self, target_group, target_id):
        """验证目标用户是否在群内"""
        try:
            group_member_check = await self.bot.get_group_member_info(target_group, target_id)
            return group_member_check['status'] == 'ok'
        except Exception:
            return False

    async def _get_random_target(self, event, persona, target_group):
        """随机获取目标用户"""
        try:
            friendlist_get = await self.bot.get_group_member_list(event.group_id)

            # 大群限制
            if persona in [2, 3, 4] and len(friendlist_get["data"]) > 1000:
                await self.bot.send(event, '抱歉，群聊人数过多，bot服务压力过大，仅开放/透群主功能，谢谢')
                return None

            # 获取候选列表
            candidates = await self._get_candidates(friendlist_get["data"], persona, target_group)
            return random.choice(candidates) if candidates else None

        except Exception as e:
            self.bot.logger.error(f"获取群成员列表失败: {e}")
            return None

    async def _get_candidates(self, members, persona, target_group):
        """获取候选用户列表"""
        candidates = []

        # 尝试获取热门群友
        if self.config["仅热门群友"] and persona not in [1, 2]:
            try:
                friendlist_check = await query_group_users('group_owner_record', target_group)
                candidates = [member[0] for member in friendlist_check[:50]]
            except Exception:
                self.bot.logger.error('透热门群友列表加载出错，执行全局随机')

        # 使用全员列表
        if not candidates:
            for member in members:
                if persona in [1, 2, 5]:  # 需要特定角色
                    if member['role'] == ('owner' if persona in [1, 5] else 'admin'):
                        candidates.append(member['user_id'])
                        if persona in [1, 5] and member['role'] == 'owner':
                            break
                else:  # 普通群友
                    candidates.append(member['user_id'])

        return candidates

    async def _execute_wife_action(self, event, persona, target_id, from_id, target_group, check):
        """执行透群友动作"""
        try:
            from_name = str(event.sender.nickname)

            # 获取目标用户信息
            target_name = await self._get_target_name(target_id, from_id, target_group, persona)
            if not target_name:
                return

            # 更新统计
            if persona == 1:
                await manage_group_status(from_id, target_group, 'group_owner')

            # 发送消息
            recall_id = await self._send_wife_message(event, persona, target_id, target_name, from_name)

            # 处理撤回
            await self._handle_message_recall(recall_id)

            print(f"透群友成功: {from_name} -> {event.message_chain}")
            await manage_group_add(from_id, target_id, target_group)

        except Exception as e:
            self.bot.logger.error(f"透群友功能异常: {e}")

    async def _get_target_name(self, target_id, from_id, target_group, persona):
        """获取目标用户名称"""
        try:
            if persona == 4:
                existing_wife = await manage_group_status(from_id, target_group, 'wife_you_get')
                if existing_wife != 0:
                    return str(existing_wife)
                else:
                    await manage_group_status(from_id, target_group, 'wife_you_get', target_id)

            group_member_check = await self.bot.get_group_member_info(target_group, target_id)
            return str(group_member_check['data']['nickname'])
        except Exception as e:
            self.bot.logger.error(f"获取目标用户信息失败: {e}")
            return None

    async def _send_wife_message(self, event, persona, target_id, target_name, from_name):
        """发送透群友消息"""
        target_img = f"https://q1.qlogo.cn/g?b=qq&nk={target_id}&s=640"

        message_templates = {
            1: lambda times: [
                f'@{from_name} 恭喜你涩到群主！！！！',
                Image(file=target_img),
                f'群主【{target_name}】这是第{times}次被透了呢'
            ],
            2: lambda: [
                f'@{from_name} 恭喜你涩到管理！！！！',
                Image(file=target_img),
                f'【{target_name}】 ({target_id})哒！'
            ],
            3: lambda: [
                f'@{from_name} 恭喜你涩到了群友！！！！',
                Image(file=target_img),
                f'【{target_name}】 ({target_id})哒！'
            ],
            4: lambda: [
                f'@{from_name} 恭喜你娶到了群友！！！！',
                Image(file=target_img),
                f'【{target_name}】 ({target_id})哒！'
            ]
        }

        if persona == 1:
            times = await manage_group_status(target_id, event.group_id, 'group_owner') or 0
            times += 1
            await manage_group_status(target_id, event.group_id, 'group_owner', times)
            message = message_templates[1](times)
        elif persona == 5:
            return await self._send_today_wife_message(event, target_name)
        else:
            message = message_templates[persona]()

        return await self.bot.send(event, message)

    async def _send_today_wife_message(self, event, target_name):
        """发送今日群主消息"""
        try:
            api = self.config["api"]
            header = self.config["header"]
            response = await today_check_api(api, header)

            img_path = 'data/pictures/wife_you_want_img/today_wife.jpg'
            with open(img_path, 'wb') as file:
                file.write(response.content)

            result = await self.bot.send(event, [
                f'这里是今天的{target_name}哟~~~\n',
                Image(file=img_path)
            ])

            # 清理临时文件
            try:
                if os.path.exists(img_path):
                    os.remove(img_path)
            except Exception:
                pass

            return result
        except Exception as e:
            self.bot.logger.error(f"发送今日群主消息失败: {e}")
            return None

    async def _handle_message_recall(self, recall_id):
        """处理消息撤回"""
        if (self.config["透群友撤回"] and recall_id and 'data' in recall_id):
            try:
                await sleep(20)
                await self.bot.recall(recall_id['data']['message_id'])
            except Exception as e:
                self.bot.logger.error(f"撤回消息失败: {e}")

    async def _handle_record_query(self, event):
        """处理记录查询"""
        context = event.pure_text or event.raw_message
        target_group = int(event.group_id)

        try:
            # 确定查询类型
            query_type, type_context = self._get_query_type(context)

            # 获取记录数据
            list_from, list_target = await manage_group_check(target_group, query_type)
            if not list_from or not list_target:
                await self.bot.send(event, '本群好像还没有一个人开过趴捏~')
                return

            # 生成消息
            await self._send_record_message(event, list_from, list_target, type_context)

        except Exception as e:
            self.bot.logger.error(f"生成色色记录失败: {e}")
            await self.bot.send(event, '生成记录时出现错误，请稍后重试')

    def _get_query_type(self, context):
        """获取查询类型"""
        if any(keyword in context for keyword in ['本周', '每周', '星期']):
            return 'week', '以下是本周色色记录：'
        elif any(keyword in context for keyword in ['本月', '月份', '月']):
            return 'month', '以下是本月色色记录：'
        elif '年' in context:
            return 'Year', '以下是年度色色记录：'
        else:
            return 'day', '以下是本日色色记录：'

    async def _send_record_message(self, event, list_from, list_target, type_context):
        """发送记录消息"""
        # 获取群成员信息
        friendlist_get = await self.bot.get_group_member_list(event.group_id)
        member_dict = {str(member['user_id']): member['nickname'] for member in friendlist_get['data']}

        # 构建消息节点
        cmList = [Node(content=[Text(type_context)])]

        # 添加透别人最多的人
        self._add_top_member_node(cmList, list_from, member_dict, '透群友最多的人诞生了！！')

        # 添加透别人次数列表
        self._add_ranking_node(cmList, list_from, member_dict, '以下是透别人的次数~\n')

        # 添加被透最多的人
        self._add_top_member_node(cmList, list_target, member_dict, '被群友透最多的人诞生了！！')

        # 添加被透次数列表
        self._add_ranking_node(cmList, list_target, member_dict, '以下是被别人透的次数~\n')

        await self.bot.send(event, cmList)

    def _add_top_member_node(self, cmList, user_list, member_dict, title):
        """添加榜首用户节点"""
        top_user_id = user_list[0][0]
        top_user_name = member_dict.get(top_user_id, '未知用户')
        cmList.append(Node(content=[
            Text(title),
            Image(file=f"https://q1.qlogo.cn/g?b=qq&nk={top_user_id}&s=640"),
            Text(f'是【{top_user_name}】 ({top_user_id})哦~')
        ]))

    def _add_ranking_node(self, cmList, user_list, member_dict, title):
        """添加排行榜节点"""
        ranking_text = title
        for user_id, count in user_list:
            user_name = member_dict.get(user_id, '未知用户')
            ranking_text += f'{user_name} ({user_id}): {count} 次\n'
        cmList.append(Node(content=[Text(ranking_text)]))





