import asyncio
import os
import sys
import threading
import time
import uuid

from asyncio import sleep
from concurrent.futures import ThreadPoolExecutor
from typing import Type, Union, Dict, Optional

import httpx
import websockets
import json
from collections.abc import Callable, Coroutine

from developTools.event.base import EventBase
from developTools.event.eventFactory import EventFactory
from developTools.message.message_chain import MessageChain
from developTools.message.message_components import MessageComponent, Text, Reply, Node, File
from developTools.utils.cq_code_handler import parse_message_2processed_message
from developTools.utils.logger import get_logger


# 引入 EventBus
class EventBus:
    def __init__(self, handler_timeout_warning: float = 10.0, enable_monitoring: bool = True) -> None:
        self.handlers: dict[Type[EventBase], set] = {}
        self.handler_timeout_warning = handler_timeout_warning
        self.enable_monitoring = enable_monitoring  # 可以完全关闭监控
        self.logger = get_logger() if enable_monitoring else None
        self._handler_info_cache: Dict[callable, str] = {}  # 缓存handler信息

    def subscribe(self, event: Type[EventBase], handler):
        if event not in self.handlers:
            self.handlers[event] = set()
        self.handlers[event].add(handler)

    def on(self, event: Type[EventBase]):
        def decorator(func):
            self.subscribe(event, func)
            return func

        return decorator

    def set_handler_timeout_warning(self, timeout: float):
        """设置handler超时警告阈值"""
        self.handler_timeout_warning = timeout
        if self.logger:
            self.logger.info_msg(f"Handler超时警告阈值已设置为: {timeout}秒")

    def toggle_monitoring(self, enabled: bool):
        """动态开启/关闭监控"""
        self.enable_monitoring = enabled
        if enabled and self.logger is None:
            self.logger = get_logger()

    async def _execute_handler_with_monitoring(self, handler, event_instance: EventBase):
        """执行handler并监控其执行时间"""
        start_time = time.perf_counter()  # 使用更精确的计时器

        try:
            # 执行handler
            if asyncio.iscoroutinefunction(handler):
                await handler(event_instance)
            else:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, handler, event_instance)
        except Exception as e:
            handler_info = self._get_handler_info_cached(handler)
            self.logger.error(f"Handler执行出错 {handler_info}: {e}", exc_info=True)
        finally:
            execution_time = time.perf_counter() - start_time

            # 只有超时时才获取handler信息和记录日志
            if execution_time > self.handler_timeout_warning:
                handler_info = self._get_handler_info_cached(handler)
                self.logger.warning(
                    f"⚠️ Handler执行时间过长: {execution_time:.3f}s (阈值: {self.handler_timeout_warning}s)\n"
                    f"   Handler信息: {handler_info}\n"
                    f"   事件类型: {type(event_instance).__name__}\n"
                    f"   建议检查是否包含阻塞代码"
                )

    def _get_handler_info_cached(self, handler) -> str:
        """获取handler信息（带缓存）"""
        if handler in self._handler_info_cache:
            return self._handler_info_cache[handler]

        try:
            if hasattr(handler, '__name__'):
                func_name = handler.__name__
            else:
                func_name = str(handler)

            # 获取源码文件信息
            if hasattr(handler, '__code__'):
                code = handler.__code__
                filename = code.co_filename
                lineno = code.co_firstlineno
                info = f"{func_name} at {filename}:{lineno}"
            elif hasattr(handler, '__call__') and hasattr(handler.__call__, '__code__'):
                code = handler.__call__.__code__
                filename = code.co_filename
                lineno = code.co_firstlineno
                info = f"{func_name} at {filename}:{lineno}"
            else:
                info = f"{func_name} (位置信息不可用)"

        except Exception as e:
            info = f"Unknown handler (获取信息失败: {e})"

        # 缓存结果
        self._handler_info_cache[handler] = info
        return info

    async def emit(self, event_instance: EventBase) -> None:
        event_type = type(event_instance)
        if handlers := self.handlers.get(event_type):
            if self.enable_monitoring:
                # 监控模式
                for handler in handlers:
                    task = asyncio.create_task(
                        self._execute_handler_with_monitoring(handler, event_instance),
                        name=f"handler-{handler.__name__ if hasattr(handler, '__name__') else 'unknown'}"
                    )
                    task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
            else:
                # 原版模式（零开销）
                for handler in handlers:
                    task = asyncio.create_task(handler(event_instance))
                    task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
        else:
            pass



class WebSocketBot:
    def __init__(self, uri: str,blocked_loggers=None,enable_monitoring=True,handler_timeout_warning=10.0):
        self.uri = uri
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.logger = get_logger(blocked_loggers=blocked_loggers)
        self.event_bus = EventBus(handler_timeout_warning=handler_timeout_warning, enable_monitoring=enable_monitoring)
        self.response_callbacks: Dict[str, asyncio.Future] = {}
        self.receive_task: Optional[asyncio.Task] = None

        self._message_queue = asyncio.Queue()  # 添加消息队列
        self._processing_task: Optional[asyncio.Task] = None  # 添加处理任务

    async def _receive(self):
        """
        接收服务端消息并放入队列。
        """
        try:
            async for response in self.websocket:
                await self._message_queue.put(response)
        except websockets.exceptions.ConnectionClosedError as e:
            self.logger.warning(f"WebSocket 连接关闭: {e}")
            self.logger.warning("5秒后尝试重连")
            await asyncio.sleep(5)
            await self._connect_and_run()
        except Exception as e:
            self.logger.error(f"接收消息时发生错误: {e}", exc_info=True)
        finally:
            # 取消所有未完成的 Future
            for future in self.response_callbacks.values():
                if not future.done():
                    future.cancel()
            self.response_callbacks.clear()
            self.receive_task = None

    async def _process_messages(self):
        """
        从队列中处理消息。
        """
        try:
            while True:
                try:
                    # 从队列中获取消息
                    response = await self._message_queue.get()
                    data = json.loads(response)
                    self.logger.info_msg(f"收到服务端响应: {data}")

                    # 如果是响应消息
                    if "status" in data and "echo" in data:
                        echo = data["echo"]
                        future = self.response_callbacks.pop(echo, None)
                        if future and not future.done():
                            future.set_result(data)
                    elif "post_type" in data:
                        event_obj = EventFactory.create_event(data)
                        try:
                            if event_obj.post_type == "meta_event":
                                if event_obj.meta_event_type == "lifecycle":
                                    self.id = int(event_obj.self_id)
                                    self.logger.info_msg(f"Bot ID: {self.id}")
                        except:
                            pass
                        if event_obj:
                            # 创建独立任务处理事件，避免阻塞消息处理
                            asyncio.create_task(self.event_bus.emit(event_obj))
                        else:
                            self.logger.warning("无法匹配事件类型，跳过处理。")
                    else:
                        self.logger.warning("收到未知消息格式，已忽略。")

                    # 标记任务完成
                    self._message_queue.task_done()

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    self.logger.error(f"处理消息时发生错误: {e}", exc_info=True)

        except asyncio.CancelledError:
            pass
        finally:
            self._processing_task = None

    async def _connect_and_run(self):
        """
        建立 WebSocket 连接并开始接收消息。
        """
        await self._connect()
        if self.websocket:
            self.receive_task = asyncio.create_task(self._receive())
            self._processing_task = asyncio.create_task(self._process_messages())

            # 等待接收任务完成（通常是连接断开时）
            try:
                await self.receive_task
            except Exception as e:
                self.logger.error(f"接收任务出错: {e}")
            finally:
                if self._processing_task and not self._processing_task.done():
                    self._processing_task.cancel()

    async def _connect(self):
        try:
            self.websocket = await websockets.connect(self.uri,max_size=None)
            self.logger.info_msg("WebSocket 连接已建立")
        except Exception as e:
            self.logger.error(f"WebSocket 连接出现错误: {e}")
            self.logger.warning("WebSocket 连接失败，5秒后尝试重连")
            await asyncio.sleep(5)
            await self._connect_and_run()

    async def _call_api(self, action: str, params: dict, timeout: int = 10) -> dict:
        if self.websocket is None:
            self.logger.warning("WebSocket 未连接，无法调用 API。")
            return {"status": "failed", "retcode": -1, "data": None, "echo": str(uuid.uuid4())}

        echo = str(uuid.uuid4())
        message = {"action": action, "params": params, "echo": echo}

        # 创建 Future，用于等待 API 响应
        future = asyncio.Future()
        self.response_callbacks[echo] = future
        await self.websocket.send(json.dumps(message))

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self.logger.error(f"调用 API 超时: {action}")
            if echo in self.response_callbacks:
                del self.response_callbacks[echo]
            return {"status": "failed", "retcode": 98, "data": None, "msg": "API call timeout", "echo": echo}



    def run(self):
        if sys.platform == 'win32':  #asyncio 默认事件循环策略与 Playwright 的兼容性问题
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        asyncio.run(self._connect_and_run())

    def on(self, event: Type[EventBase]):
        """
        用于订阅事件的装饰器。
        """
        return self.event_bus.on(event)


    """
    以下为消息发送相关函数
    """
    async def send_to_server(self, event: EventBase, message: Union[MessageChain, dict]):
        """
        发送消息，可以接受 MessageChain 或原始字典格式的消息。

        Args:
            message (Union[MessageChain, dict]): 消息链或字典。
        """
        try:
            if self.websocket:
                if hasattr(event, "group_id"):
                    action = "send_group_msg"
                    params = {
                            "group_id": event.group_id,
                            "message": message.to_dict()
                        }

                    if isinstance(message[0], Node):
                        r = await self.send_group_forward_msg(event.group_id, message)
                        return r
                    if all(isinstance(item, File) for item in message):
                        for f in message:
                            r=await self.upload_group_file(event.group_id, f.file)
                        return r
                elif hasattr(event, "user_id"):
                    action = "send_private_msg"
                    params = {
                            "user_id": event.user_id,
                            "message": message.to_dict()
                        }

                    if isinstance(message[0], Node):
                        r = await self.send_private_forward_msg(event.user_id, message)
                        return r
                    if all(isinstance(item, File) for item in message):
                        for f in message:
                            r=await self.upload_private_file(event.user_id, f.file)
                        return r
                self.logger.info_func(f"发送的消息: {message.to_dict()}")
                return await self._call_api(action, params)
            else:
                self.logger.warning("WebSocket 未连接，无法发送消息")
        except Exception as e:
            self.logger.error(f"发送消息时出现错误: {e}", exc_info=True)

    async def send(self, event: EventBase, components: list[Union[MessageComponent, str]],Quote: bool=False):
        """
        构建并发送消息链。

        Args:
            components (list[Union[MessageComponent, str]]): 消息组件或字符串。
        """
        try:
            # 将字符串自动转换为 Text 对象
            if isinstance(components, str):
                components = [Text(components)]
            if not isinstance(components, list):
                components = [components]
            if Quote:
                components.insert(0, Reply(id=event.message_id))
                #components.append(Reply(id=event.message_id))  # 消息引用
            else:
                # 将列表中的字符串转换为 Text 对象
                components = [
                    Text(component) if isinstance(component, str) else component
                    for component in components
                ]

            message_chain = MessageChain(components)
            return await self.send_to_server(event, message_chain)
        except Exception as e:
            self.logger.error(f"发送消息时出现错误: {e}", exc_info=True)
    async def send_friend_message(self, user_id: int, components: list[Union[MessageComponent, str]]):

        if isinstance(components, str):
            components = [Text(components)]
        if not isinstance(components, list):
            components = [components]
        else:
            # 将列表中的字符串转换为 Text 对象
            components = [
                Text(component) if isinstance(component, str) else component
                for component in components
            ]

        message = MessageChain(components)
        data = {
            "action": "send_private_msg",
            "params": {
                "user_id": user_id,
                "message": message.to_dict()
            }
        }
        if isinstance(message[0], Node):
            r = await self.send_private_forward_msg(user_id, message)
            return r
        return await self._call_api(data["action"], data["params"])
    async def send_group_message(self, group_id: int, components: list[Union[MessageComponent, str]]):
        if isinstance(components, str):
            components = [Text(components)]
        if not isinstance(components, list):
            components = [components]
        else:
            # 将列表中的字符串转换为 Text 对象
            components = [
                Text(component) if isinstance(component, str) else component
                for component in components
            ]

        message = MessageChain(components)
        data = {
            "action": "send_group_msg",
            "params": {
                "group_id": group_id,
                "message": message.to_dict()
            }
        }
        if isinstance(message[0], Node):
            r = await self.send_group_forward_msg(group_id, message)
            return r
        return await self._call_api(data["action"], data["params"])

    async def get_status(self):
        """
        获取服务状态
        :return:
        """
        return await self._call_api("get_status", {})

    """
    消息发送
    """

    async def send_group_forward_msg(self, group_id: int, components: Union[str, list[Union[MessageComponent, str]]]):
        """
        发送群消息
        :param group_id:
        :param components:
        :return:
        """
        # 如果是字符串，将其包装为 [Text(str)]
        if isinstance(components, str):
            components = [Text(components)]
        if not isinstance(components,list):
            components = [components]
        else:
            components = [
                Text(component) if isinstance(component, str) else component
                for component in components
            ]

        message = MessageChain(components)
        data = {
            "group_id": group_id,
            "messages": message.to_dict(),
        }
        self.logger.info_msg(f"发送消息: {data}")
        return await self._call_api("send_group_forward_msg", data)
    async def send_private_forward_msg(self,user_id: int, components: Union[str, list[Union[MessageComponent, str]]]):
        """
        发送私聊合并转发消息
        :param user_id:
        :param components:
        :return:
        """
        # 如果是字符串，将其包装为 [Text(str)]
        if isinstance(components, str):
            components = [Text(components)]
        if not isinstance(components,list):
            components = [components]
        else:
            components = [
                Text(component) if isinstance(component, str) else component
                for component in components
            ]

        message = MessageChain(components)
        data = {
            "user_id": user_id,
            "messages": message.to_dict(),
        }
        self.logger.info_msg(f"发送消息: {data}")
        return await self._call_api("send_private_forward_msg", data)

    async def get_msg(self, message_id: int):
        """
        获取历史消息，返回事件对象
        :param message_id:
        :return:
        """
        source_msg = await self._call_api("get_msg", {"message_id": message_id})
        if source_msg["data"].get("post_type") is None:
            source_msg["data"]["post_type"] = "message"
        if source_msg["data"].get("sub_type") is None:
            source_msg["data"]["sub_type"] = "normal"
        if source_msg["data"].get("font") is None:
            source_msg["data"]["font"] = 0
        if source_msg["data"].get("user_id") is None:
            source_msg["data"]["user_id"] = source_msg["data"]["sender"]["user_id"]
        if source_msg["data"].get("group_id") is None:
            source_msg["data"]["group_id"] = 0
        event_obj = EventFactory.create_event(source_msg['data'])
        if hasattr(event_obj,"processed_message"):
            if event_obj.processed_message==[]:
                event_obj.processed_message=parse_message_2processed_message(event_obj.message)
        return event_obj
    async def get_forward_msg(self, message_id: str):
        source_msg = await self._call_api("get_forward_msg", {"id": message_id})
        return source_msg
    """
    撤回、禁言等群管类
    """
    async def recall(self, message_id: int):
        """
        撤回消息
        :param message_id:
        :return:
        """
        return await self._call_api("delete_msg", {"message_id": message_id})

    async def send_like(self,user_id):
        """
        发送点赞
        :param user_id:
        :return:
        """
        return await self._call_api("send_like", {"user_id": user_id,"times":10})

    """
    私聊相关
    """
    async def get_friend_list(self):
        """
        获取好友列表
        :return:
        """
        return await self._call_api("get_friend_list", {"no_cache": False})

    async def delete_friend(self,user_id):
        """
        删除好友
        :param user_id:
        :return:
        """
        #删好友
        return await self._call_api("delete_friend", {"user_id":user_id})
    async def handle_friend_request(self,flag: str,approve: bool,remark: str):
        """
        处理好友请求
        :param flag:
        :param approve:
        :param remark:
        :return:
        """
        return await self._call_api("set_friend_add_request", {"flag":flag,"approve":approve,"remark":remark})
    async def set_friend_remark(self,user_id: int,remark: str):
        """
        设置好友备注
        :param user_id:
        :param remark:
        :return:
        """
        return await self._call_api("set_friend_remark", {"user_id":user_id,"remark":remark})
    async def set_friend_category(self,user_id: int,category_id: int):
        """
        设置好友分组
        :param user_id:
        :param category_id:
        :return:
        """
        data={"user_id":user_id,"category_id":category_id}
        return await self._call_api("set_friend_category", data)


    async def get_stranger_info(self,user_id: int):
        """
        获取陌生人信息
        :param user_id:
        :return:
        """
        data={"user_id":user_id}
        return await self._call_api("get_stranger_info", data)

    async def set_qq_avatar(self,file: str):
        """
        设置QQ头像
        :param file:
        :return:
        """
        data={"file":file}
        return await self._call_api("set_qq_avatar", data)

    async def friend_poke(self,user_id: int):
        data={"user_id":user_id}
        return await self._call_api("friend_poke", data)

    async def upload_private_file(self,user_id: int,file: str,name: str=None):
        """
        上传私聊文件
        :param user_id:
        :param file:
               "file": "https://www.yujn.cn/api/heisis.php",
                // 本地文件
                // "file": "file://d:\\1.mp4"

                // base64文件
                // "file": "base64://xxxxxxxxxxxxx"
        :param name:
        :return:
        """
        if name is None:
            file_name = os.path.basename(file)
            name = file_name
        data={"user_id":user_id,"file":file,"name":name}
        return await self._call_api("upload_private_file", data)

    """
    群聊相关
    """
    async def get_group_list(self):
        """
        获取群列表
        :return:
        """
        data={"no_cache": False}
        return await self._call_api("get_group_list", data)

    async def get_group_info(self,group_id: int):
        """
        获取群信息
        :param group_id:
        :return:
        """
        data={"group_id":group_id}
        return await self._call_api("get_group_info", data)
    async def get_group_member_list(self,group_id: int):
        """
        获取群成员列表
        :param group_id:
        :return:
        """
        data={"group_id":group_id,"no_cache": True}
        return await self._call_api("get_group_member_list", data)

    async def get_group_member_info(self,group_id: int,user_id: int):
        """
        获取群成员信息
        :param group_id:
        :param user_id:
        :return:
        """
        data={"group_id":group_id,"user_id":user_id}
        return await self._call_api("get_group_member_info", data)

    async def group_poke(self,group_id: int,user_id: int):
        """
        群戳一戳
        :param group_id:
        :param user_id:
        :return:
        """
        data={"group_id":group_id,"user_id":user_id}
        return await self._call_api("group_poke", data)

    async def set_group_add_request(self,flag: str,approve: bool,reason: str):
        """
        处理加群请求
        :param flag: 请求id
        :param approve:
        :param reason:
        :return:
        """
        data={"flag":flag,"approve":approve,"reason":reason}
        return await self._call_api("set_group_add_request", data)

    async def quit(self,group_id: int):
        """
        退出群聊
        :param group_id:
        :return:
        """
        data={"group_id":group_id}
        return await self._call_api("set_group_leave", data)

    async def set_group_admin(self,group_id: int,user_id: int,enable: bool):
        """
        设置群管理员
        :param group_id:
        :param user_id:
        :param enable: 设置/取消
        :return:
        """
        data={"group_id":group_id,"user_id":user_id,"enable":enable}
        return await self._call_api("set_group_admin", data)

    async def set_group_card(self,group_id: int,user_id: int,card: str):
        """
        设置群名片
        :param group_id:
        :param user_id:
        :param card:
        :return:
        """
        data={"group_id":group_id,"user_id":user_id,"card":card}
        return await self._call_api("set_group_card", data)

    async def mute(self,group_id: int,user_id: int,duration: int):
        """
        禁言群成员
        :param group_id:
        :param user_id:
        :param duration: 秒，0为解除禁言
        :return:
        """
        data={"group_id":group_id,"user_id":user_id,"duration":duration}
        return await self._call_api("set_group_ban", data)

    async def set_group_whole_ban(self,group_id: int,enable: bool):
        """
        设置全员禁言
        :param group_id:
        :param enable:
        :return:
        """
        data={"group_id":group_id,"enable":enable}
        return await self._call_api("set_group_whole_ban", data)

    async def set_group_name(self,group_id: int,group_name: str):
        """
        设置群名称
        :param group_id:
        :param group_name:
        :return:
        """
        data={"group_id":group_id,"group_name":group_name}
        return await self._call_api("set_group_name", data)

    async def set_group_special_title(self,group_id: int,user_id: int,special_title: str):
        """
        设置群头衔
        :param group_id:
        :param user_id:
        :param special_title:
        :return:
        """
        data={"group_id":group_id,"user_id":user_id,"special_title":special_title}
        return await self._call_api("set_group_special_title", data)

    async def set_group_kick(self,group_id: int,user_id: int,reject_add_request: bool=True):
        """
        踢出群成员
        :param group_id:
        :param user_id:
        :param reject_add_request:
        :return:
        """
        data={"group_id":group_id,"user_id":user_id,"reject_add_request":reject_add_request}
        return await self._call_api("set_group_kick", data)

    async def get_group_honor_info(self,group_id: int):
        """
        获取群荣誉信息. 壁画王。
        :param group_id:
        :return:
        """
        data={"group_id":group_id}
        return await self._call_api("get_group_honor_info", data)

    async def get_essence_msg_list(self,group_id: int):
        """
        获取精华消息列表
        :param group_id:
        :return:
        """
        data={"group_id":group_id}
        return await self._call_api("get_essence_msg_list", data)

    async def set_essence_msg(self,message_id: int|str):
        """
        设置精华消息
        :param message_id:
        :return:
        """
        if isinstance(message_id,str):
            message_id=int(message_id)
        data={"message_id":message_id}
        return await self._call_api("set_essence_msg", data)

    async def delete_essence_msg(self,message_id: int):
        """
        删除精华消息
        :param message_id:
        :return:
        """
        data={"message_id":message_id}
        return await self._call_api("delete_essence_msg", data)

    async def get_group_root_files(self,group_id: int):
        """
        获取群根目录文件列表，暂时看不出来有啥用
        :param group_id:
        :return:
        """
        data={"group_id":group_id}
        return await self._call_api("get_group_root_files", data)
    async def upload_group_file(self,group_id: int,file: str,name: str=None):
        """
        上传群文件。传好东西
        :param group_id:
        :param file:
        :param name:
        :return:
        """
        if name is None:
            file_name = os.path.basename(file)
            name = file_name
        data={"group_id":group_id,"file":file,"name":name}
        return await self._call_api("upload_group_file", data)

    async def delete_group_file(self,group_id: int,file_id: str):
        """
        删除群文件。那个id是上传的时候给的
        :param group_id:
        :param file_id:
        :return:
        """
        data={"group_id":group_id,"file_id":file_id}
        return await self._call_api("delete_group_file", data)

    async def create_group_file_folder(self,group_id: int,name: str):
        """
        创建群文件夹
        :param group_id:
        :param name:
        :return:
        """
        data={"group_id":group_id,"name":name}
        return await self._call_api("create_group_file_folder", data)

    async def delete_group_folder(self,group_id: int,folder_id: str):
        """
        删除群文件夹
        :param group_id:
        :param folder_id:
        :return:
        """
        data={"group_id":group_id,"folder_id":folder_id}
        return await self._call_api("delete_group_folder", data)

    async def get_group_file_url(self,file_id: str):
        """
        获取群文件下载链接,估计不大好用
        :param file_id:
        :return:
        """
        data={"file_id":file_id}
        return await self._call_api("get_group_file_url", data)

    async def _send_group_notice(self,group_id: int,content: str,image: str):
        """
        发送群公告
        :param group_id:
        :param content:
        :param image:  支持http://, file://, base64://
        :return:
        """
        data={"group_id":group_id,"content":content,"image":image}
        return await self._call_api("_send_group_notice", data)

    async def _get_group_notice(self,group_id: int):
        """
        获取群公告
        :param group_id:
        :return:
        """
        data={"group_id":group_id}
        return await self._call_api("_get_group_notice", data)

    async def get_group_ignore_add_request(self,group_id: int):
        """
        获取群组忽略的加群请求
        :param group_id:
        :return:
        """
        data={"group_id":group_id}
        return await self._call_api("get_group_ignore_add_request", data)

    async def send_group_sign(self,group_id: int):
        """
        发送群签到
        :param group_id:
        :return:
        """
        data={"group_id":group_id}
        return await self._call_api("send_group_sign", data)


    async def get_record(self,file: str,out_format="mp3"):
        data={"file":file,"out_format":out_format}
        return await self._call_api("get_record", data)

    async def get_video(self,url:str,path:str):

        async with httpx.AsyncClient(timeout=200) as client:
            r=await client.get(url)
            with open(path,"wb") as f:
                f.write(r.content)
            return path
    """
    napcat专有接口实现
    """
    async def get_ai_characters(self):
        """
        获取ai声聊所有可用角色
        :return:
        """
        data={
            "group_id": 0,
            "chat_type": 1,
        }
        return await self._call_api("get_ai_characters", data)
    async def get_ai_record(self,group_id: int,character: str,text: str):
        """
        获取ai声音合成的语音
        :param character:
        :param text:
        :return:
        """
        data={
          "group_id": group_id,
          "character": character,
          "text": text,
        }
        return await self._call_api("get_ai_record", data)
