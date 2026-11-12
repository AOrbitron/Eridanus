#实现黑白名单判断，后续aiReplyCore的阻断也将在这里实现
import asyncio
import json
from typing import Union

import websockets

from developTools.adapters.websocket_adapter import WebSocketBot
from developTools.event.base import EventBase
from developTools.event.eventFactory import EventFactory
from developTools.message.message_components import MessageComponent, Reply, Text, Music, At, Poke, File, Node
from framework_common.utils.utils import convert_list_to_type


class ExtendBot(WebSocketBot):
    def __init__(self, uri: str, config, **kwargs):
        super().__init__(uri, **kwargs)
        self.config = config
        self.id = 1000000

    # ------------------------------------------------------------------
    # 离线模式：uri 为空时跳过连接，对象保持存活
    # ------------------------------------------------------------------
    async def _connect(self):
        if not self.uri:
            self.logger.info("WebSocket URI 为空，跳过连接（离线模式）。")
            return
        await super()._connect()

    async def _connect_and_run(self):
        if not self.uri:
            self.logger.info("WebSocket URI 为空，跳过连接（离线模式）。")
            return
        await super()._connect_and_run()

    # ------------------------------------------------------------------

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
                        if event_obj and not getattr(event_obj, "adapter_source", None):
                            event_obj.adapter_source = data.get("adapter_source", "onebot_v11")
                        try:
                            if event_obj.post_type == "meta_event":
                                if event_obj.meta_event_type == "lifecycle":
                                    self.id = int(event_obj.self_id)
                                    self.logger.info_msg(f"Bot ID: {self.id}")
                        except:
                            pass
                        if hasattr(event_obj, "group_id") and event_obj.group_id is not None:
                            if self.config.common_config.basic_config["group_handle_logic"] == "blacklist":
                                if event_obj.group_id not in self.config.common_config.censor_group["blacklist"]:
                                    if hasattr(event_obj, "user_id"):
                                        if self.config.common_config.basic_config["user_handle_logic"] == "blacklist":
                                            if event_obj.user_id not in convert_list_to_type(
                                                    self.config.common_config.censor_user["blacklist"]):
                                                asyncio.create_task(self.event_bus.emit(event_obj))
                                            else:
                                                self.logger.info(f"用户{event_obj.user_id}在黑名单中，跳过处理。")
                                        elif self.config.common_config.basic_config["user_handle_logic"] == "whitelist":
                                            if event_obj.user_id in convert_list_to_type(
                                                    self.config.common_config.censor_user["whitelist"]):
                                                asyncio.create_task(self.event_bus.emit(event_obj))
                                            else:
                                                self.logger.info(f"用户{event_obj.user_id}不在白名单中，跳过处理。")
                                    else:
                                        asyncio.create_task(self.event_bus.emit(event_obj))
                                else:
                                    self.logger.info(f"群{event_obj.group_id}在黑名单中，跳过处理。")
                            elif self.config.common_config.basic_config["group_handle_logic"] == "whitelist":
                                if event_obj.group_id in convert_list_to_type(
                                        self.config.common_config.censor_group["whitelist"]):
                                    if hasattr(event_obj, "user_id"):
                                        if self.config.common_config.basic_config["user_handle_logic"] == "blacklist":
                                            if event_obj.user_id not in convert_list_to_type(
                                                    self.config.common_config.censor_user["blacklist"]):
                                                asyncio.create_task(self.event_bus.emit(event_obj))
                                            else:
                                                self.logger.info(f"用户{event_obj.user_id}在黑名单中，跳过处理。")
                                        elif self.config.common_config.basic_config["user_handle_logic"] == "whitelist":
                                            if event_obj.user_id in convert_list_to_type(
                                                    self.config.common_config.censor_user["whitelist"]):
                                                asyncio.create_task(self.event_bus.emit(event_obj))
                                            else:
                                                self.logger.info(f"用户{event_obj.user_id}不在白名单中，跳过处理。")
                                    else:
                                        asyncio.create_task(self.event_bus.emit(event_obj))
                                else:
                                    self.logger.info(f"群{event_obj.group_id}不在白名单中，跳过处理。")
                        elif hasattr(event_obj, "user_id"):
                            if self.config.common_config.basic_config["user_handle_logic"] == "blacklist":
                                if event_obj.user_id not in convert_list_to_type(
                                        self.config.common_config.censor_user["blacklist"]):
                                    asyncio.create_task(self.event_bus.emit(event_obj))
                                else:
                                    self.logger.info(f"用户{event_obj.user_id}在黑名单中，跳过处理。")
                            elif self.config.common_config.basic_config["user_handle_logic"] == "whitelist":
                                if event_obj.user_id in convert_list_to_type(
                                        self.config.common_config.censor_user["whitelist"]):
                                    asyncio.create_task(self.event_bus.emit(event_obj))
                                else:
                                    self.logger.info(f"用户{event_obj.user_id}不在白名单中，跳过处理。")
                        elif event_obj:
                            asyncio.create_task(self.event_bus.emit(event_obj))  # 不能await，
                        else:
                            self.logger.warning(f"无法匹配的事件类型，请向开发群913122269反馈。源数据：{data}。")
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

    async def send(self, event: EventBase, components: list[Union[MessageComponent, str]], Quote: bool = False):
        """
        构建并发送消息链。

        Args:
            components (list[Union[MessageComponent, str]]): 消息组件或字符串。
        """
        if isinstance(components, str):
            components = [Text(components)]
        if not isinstance(components, list):
            components = [components]
        if hasattr(event, "message_id"):
            if event.message_id==114514:   #自己构建的假事件没有真正的message_id，这里直接跳过
                Quote=False

        if self.config.common_config.basic_config["protocol"]["onebot_v11"]["adapter_name"] == "Lagrange":
            if Quote:
                components.insert(0, Reply(id=str(event.message_id)))
            for index, item in enumerate(components):
                if isinstance(item, Music):
                    item.id=str(item.id)
                elif isinstance(item, At):
                    item.qq=str(item.qq)
                elif isinstance(item, Poke):
                    item.type=str(item.type)
                    item.id=str(item.id)
                elif isinstance(item,File):
                    item.file=item.file.replace("file://","")
                elif isinstance(item,Reply):
                    item.id=str(item.id)
                elif isinstance(item,Node):
                    item.user_id=str(self.id)
                    item.nickname=str(self.config.common_config.basic_config["bot"]) #yaml
                components[index] = item
            return await super().send(event, components)
        else:
            return await super().send(event, components, Quote)

    async def delay_recall(self,msg, interval=20):
        """
        延迟撤回消息的非阻塞封装函数，撤回机器人自身消息可以先msg = await bot.send(event, 'xxx')然后调用await delay_recall(bot, msg, 20)这样来不阻塞的撤回，默认20秒后撤回

        参数:
            bot
            msg: 消息
            interval: 延迟时间（秒）
        """

        async def recall_task():
            await asyncio.sleep(interval)
            await super().recall(msg['data']['message_id'])

        asyncio.create_task(recall_task())