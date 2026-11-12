# developTools/adapters/milky_adapter.py
# Milky Protocol 1.3 Adapter for Eridanus
import asyncio
import json
import os
import sys
import time
import uuid
import sqlite3
import hashlib
from contextvars import ContextVar
from pathlib import Path
from typing import Type, Union, Dict, Optional, List, Any

import httpx
import websockets

from developTools.event.base import EventBase
from developTools.event.eventFactory import EventFactory
from developTools.event.events import (
    GroupMessageEvent,
    PrivateMessageEvent,
    LifecycleMetaEvent,
    NoticeEvent,
    GroupRecallNoticeEvent,
    FriendRecallNoticeEvent,
    PokeNotifyEvent,
    GroupIncreaseNoticeEvent,
    GroupDecreaseNoticeEvent,
    GroupBanNoticeEvent,
    GroupAdminNoticeEvent,
)
from developTools.message.message_chain import MessageChain
from developTools.message.message_components import MessageComponent, Text, Reply, Node, File, Image, Face, At
from developTools.utils.logger import get_logger
from framework_common.utils.utils import convert_list_to_type

_handler_peer = ContextVar("milky_handler_peer", default=None)


class EventBus:
    def __init__(self, handler_timeout_warning: float = 10.0, enable_monitoring: bool = True) -> None:
        self.handlers: dict[Type[EventBase], set] = {}
        self.handler_timeout_warning = handler_timeout_warning
        self.enable_monitoring = enable_monitoring
        self.logger = get_logger() if enable_monitoring else None
        self._handler_info_cache: Dict[Any, str] = {}

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
        self.handler_timeout_warning = timeout
        if self.logger:
            self.logger.info_msg(f"Handler超时警告阈值已设置为: {timeout}秒")

    def toggle_monitoring(self, enabled: bool):
        self.enable_monitoring = enabled
        if enabled and self.logger is None:
            self.logger = get_logger()

    async def emit(self, event_instance: EventBase) -> None:
        event_type = type(event_instance)
        if handlers := self.handlers.get(event_type):
            for handler in handlers:
                async def invoke(callback=handler):
                    scene = "group" if getattr(event_instance, "group_id", None) else "friend"
                    peer = getattr(event_instance, "group_id", None) or getattr(event_instance, "user_id", None)
                    token = _handler_peer.set((scene, peer))
                    try:
                        await callback(event_instance)
                    finally:
                        _handler_peer.reset(token)
                task = asyncio.create_task(invoke())
                task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)


class MilkyAdapter:
    def __init__(
        self,
        api_url: str = "http://127.0.0.1:3001",
        event_ws_url: str = "ws://127.0.0.1:3001/event",
        access_token: str = "",
        config = None,
        blocked_loggers = None,
        enable_monitoring: bool = True,
        handler_timeout_warning: float = 10.0,
        api_timeout: float = 60.0,
        message_cache_path: Optional[str] = None,
        **kwargs
    ):
        self.api_url = api_url.rstrip("/")
        self.event_ws_url = event_ws_url
        self.access_token = access_token or ""
        self.config = config
        self.id = 1000000
        self.is_secondary = False

        self.logger = get_logger(blocked_loggers=blocked_loggers)
        self.event_bus = EventBus(handler_timeout_warning=handler_timeout_warning, enable_monitoring=enable_monitoring)

        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self._message_queue = asyncio.Queue()
        self.receive_task: Optional[asyncio.Task] = None
        self._processing_task: Optional[asyncio.Task] = None
        self._running = False
        self._message_context = {}
        self._request_context = {}
        cache_path = Path(message_cache_path) if message_cache_path else Path("data/dataBase/milky_recent_messages.db")
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._message_db = sqlite3.connect(str(cache_path))
        self._message_db.execute("PRAGMA journal_mode=WAL")
        self._message_db.execute("CREATE TABLE IF NOT EXISTS messages (account INTEGER, scene TEXT, peer INTEGER, seq INTEGER, body TEXT, saved REAL, PRIMARY KEY(account,scene,peer,seq))")
        self._message_db.execute("DELETE FROM messages WHERE saved < ?", (time.time() - 7 * 86400,))
        self._message_db.commit()

        headers = {"Content-Type": "application/json"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        # 显式关闭环境变量代理，直连本机 localhost/127.0.0.1
        self._http_client = httpx.AsyncClient(
            headers=headers, timeout=httpx.Timeout(float(api_timeout), connect=10.0), trust_env=False
        )

    @property
    def self_id(self):
        return self.id

    def on(self, event: Type[EventBase]):
        return self.event_bus.on(event)

    async def _call_api(self, action: str, params: Optional[dict] = None) -> dict:
        params = dict(params or {})
        endpoint = action
        if action == "send_group_msg":
            endpoint = "send_group_message"
            if "group_id" in params:
                params["group_id"] = int(params["group_id"])
        elif action == "send_private_msg":
            endpoint = "send_private_message"
            if "user_id" in params:
                params["user_id"] = int(params["user_id"])
        elif action == "delete_msg":
            if "group_id" in params:
                endpoint = "recall_group_message"
            elif "user_id" in params:
                endpoint = "recall_private_message"
            else:
                endpoint = "recall_group_message"
            if "message_id" in params and "message_seq" not in params:
                params["message_seq"] = int(params["message_id"])

        api_root = self.api_url if self.api_url.endswith("/api") else f"{self.api_url}/api"
        url = f"{api_root}/{endpoint}"
        headers = {"Content-Type": "application/json"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"

        try:
            resp = await self._http_client.post(url, json=params, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("retcode", 0) != 0 or data.get("status") == "failed":
                    self.logger.error(f"Milky API [{endpoint}] 失败: {data.get('message', data.get('msg', 'unknown error'))}")
                    data.setdefault("msg", data.get("message", ""))
                return data
            else:
                self.logger.error(f"Milky API [{endpoint}] HTTP 状态码: {resp.status_code}, 内容: {resp.text}")
                return {"status": "failed", "retcode": resp.status_code, "data": None, "msg": resp.text}
        except Exception as e:
            detail = f"{type(e).__name__}: {e}"
            self.logger.error(f"Milky API [{endpoint}] 调用失败: {detail}")
            # Never retry sends automatically: the server may already have sent it.
            return {"status": "failed", "retcode": -1, "data": None, "msg": detail}

    @staticmethod
    def _media_uri(value):
        value = str(value or "")
        if not value or value.startswith(("http://", "https://", "base64://", "file://")):
            return value
        return Path(value).resolve().as_uri()

    @staticmethod
    def onebot_to_milky_segments(onebot_segments: list) -> list:
        milky_segs = []
        for seg in onebot_segments:
            if isinstance(seg, str):
                milky_segs.append({"type": "text", "data": {"text": seg}})
                continue
            if isinstance(seg, dict):
                stype = seg.get("type", "text")
                sdata = seg.get("data", {})
            elif hasattr(seg, "comp_type"):
                stype = seg.comp_type
                sdata = {}
                for k, v in seg:
                    if k not in ["comp_type"]:
                        sdata[k] = v
            else:
                stype = "text"
                sdata = {"text": str(seg)}

            if stype == "text":
                milky_segs.append({"type": "text", "data": {"text": str(sdata.get("text", ""))}})
            elif stype == "node":
                content = sdata.get("content", [])
                if not isinstance(content, list):
                    content = [content]
                node = {"user_id": int(sdata.get("user_id", 0)),
                        "sender_name": sdata.get("nickname", "bot"),
                        "segments": MilkyAdapter.onebot_to_milky_segments(content)}
                if milky_segs and milky_segs[-1]["type"] == "forward":
                    milky_segs[-1]["data"]["messages"].append(node)
                else:
                    milky_segs.append({"type": "forward", "data": {"messages": [node]}})
            elif stype in ["mention", "at"]:
                qq = str(sdata.get("qq", sdata.get("user_id", "")))
                if qq in ("all", "0"):
                    milky_segs.append({"type": "mention_all", "data": {}})
                else:
                    milky_segs.append({"type": "mention", "data": {"user_id": int(qq)}})
            elif stype == "face":
                face_id = sdata.get("face_id", sdata.get("id", 0))
                milky_segs.append({"type": "face", "data": {"face_id": str(face_id)}})
            elif stype in ["image", "mface", "video"]:
                uri = MilkyAdapter._media_uri(sdata.get("uri") or sdata.get("url") or sdata.get("file"))
                milky_segs.append({"type": "video" if stype == "video" else "image", "data": {"uri": uri}})
            elif stype == "record":
                uri = MilkyAdapter._media_uri(sdata.get("uri") or sdata.get("url") or sdata.get("file"))
                milky_segs.append({"type": "record", "data": {"uri": uri}})
            elif stype == "reply":
                seq = sdata.get("message_seq", sdata.get("id", 0))
                milky_segs.append({"type": "reply", "data": {"message_seq": int(seq)}})
            else:
                milky_segs.append({"type": stype, "data": sdata})
        return milky_segs

    @staticmethod
    def milky_to_onebot_segments(milky_segments: list) -> list:
        ob_segs = []
        for seg in milky_segments:
            stype = seg.get("type", "text")
            sdata = seg.get("data", {})
            if stype == "text":
                ob_segs.append({"type": "text", "data": {"text": sdata.get("text", "")}})
            elif stype == "mention":
                ob_segs.append({"type": "at", "data": {"qq": str(sdata.get("user_id", ""))}})
            elif stype == "mention_all":
                ob_segs.append({"type": "at", "data": {"qq": "all"}})
            elif stype == "face":
                ob_segs.append({"type": "face", "data": {"id": str(sdata.get("face_id", ""))}})
            elif stype == "image":
                uri = sdata.get("temp_url") or sdata.get("uri") or ""
                ob_segs.append({
                    "type": "image",
                    "data": {
                        "file": uri,
                        "url": uri,
                        "summary": sdata.get("summary", ""),
                        "sub_type": sdata.get("sub_type", "normal")
                    }
                })
            elif stype == "record":
                uri = sdata.get("temp_url") or sdata.get("uri") or ""
                ob_segs.append({"type": "record", "data": {"file": uri, "url": uri}})
            elif stype == "video":
                uri = sdata.get("temp_url") or sdata.get("uri") or ""
                ob_segs.append({"type": "video", "data": {"file": uri, "url": uri}})
            elif stype == "reply":
                ob_segs.append({"type": "reply", "data": {"id": sdata.get("message_seq", 0)}})
            elif stype == "file":
                ob_segs.append({"type": "file", "data": {
                    "file": sdata.get("file_id", ""), "name": sdata.get("file_name", ""),
                    "file_id": sdata.get("file_id", ""), "file_size": sdata.get("file_size", 0)}})
            elif stype == "market_face":
                ob_segs.append({
                    "type": "mface",
                    "data": {
                        "summary": sdata.get("face_name", ""),
                        "url": "",
                        "emoji_id": str(sdata.get("face_id", "")),
                        "emoji_package_id": str(sdata.get("package_id", ""))
                    }
                })
            else:
                ob_segs.append({"type": stype, "data": sdata})
        return ob_segs

    async def _resolve_media_segments(self, segments, refresh=False):
        resolved = []
        for segment in segments:
            segment = {**segment, "data": dict(segment.get("data", {}))}
            media = segment["data"]
            if segment.get("type") in ("image", "record", "video") and media.get("resource_id") and (refresh or not media.get("temp_url")):
                result = await self._call_api("get_resource_temp_url", {"resource_id": media["resource_id"]})
                if result.get("status") == "ok":
                    media["temp_url"] = (result.get("data") or {}).get("url") or media.get("temp_url", "")
            resolved.append(segment)
        return resolved

    def _remember_message(self, sequence, scene, peer_id):
        contexts = self._message_context.setdefault(int(sequence), set())
        contexts.add((scene, int(peer_id)))
        if len(self._message_context) > 4096:
            self._message_context.pop(next(iter(self._message_context)))

    def _cache_message(self, message):
        scene, peer, seq = message["message_scene"], int(message["peer_id"]), int(message["message_seq"])
        self._remember_message(seq, scene, peer)
        self._message_db.execute("INSERT OR REPLACE INTO messages VALUES (?,?,?,?,?,?)",
            (self.id, scene, peer, seq, json.dumps(message, ensure_ascii=False), time.time()))
        self._message_db.execute("DELETE FROM messages WHERE rowid IN (SELECT rowid FROM messages ORDER BY saved DESC LIMIT -1 OFFSET 10000)")
        self._message_db.commit()

    def _cached_message(self, scene, peer, seq):
        row = self._message_db.execute("SELECT body FROM messages WHERE account=? AND scene=? AND peer=? AND seq=?",
            (self.id, scene, int(peer), int(seq))).fetchone()
        return json.loads(row[0]) if row else None

    def _find_quoted_original(self, scene, peer, quoted):
        # Yogurt private replies can expose seq=0 and flatten images to their summary.
        # Match only exact sender, timestamp and preview, and reject ambiguity.
        if not quoted.get("segments") or any(s.get("type") != "text" for s in quoted["segments"]):
            return None
        preview = "".join(s.get("data", {}).get("text", "") for s in quoted["segments"])
        matches = []
        rows = self._message_db.execute(
            "SELECT body FROM messages WHERE account=? AND scene=? AND peer=? ORDER BY saved DESC LIMIT 500",
            (self.id, scene, int(peer)))
        for (body,) in rows:
            message = json.loads(body)
            if (int(message.get("message_seq", 0)) <= 0 or
                    message.get("sender_id") != quoted.get("sender_id") or
                    message.get("time") != quoted.get("time")):
                continue
            segments = message.get("segments", [])
            if not segments or any(s.get("type") not in ("text", "image") for s in segments):
                continue
            summary = "".join(s.get("data", {}).get("text", "") if s.get("type") == "text"
                              else s.get("data", {}).get("summary") or "[图片]" for s in segments)
            if summary == preview:
                matches.append(message)
        return matches[0] if len(matches) == 1 else None

    def _cache_sent(self, scene, peer, result, segments):
        self._cache_message({"message_scene": scene, "peer_id": int(peer),
            "message_seq": result["message_seq"], "sender_id": self.id,
            "time": result.get("time", int(time.time())), "segments": segments})

    async def _dispatch_milky_event(self, data: dict):
        event_type = data.get("event_type", "")
        event_data = data.get("data", {})
        event_time = data.get("time", int(time.time()))

        ob_event_dict = None

        if event_type == "message_receive":
            event_data = {**event_data, "segments": [
                {**segment, "data": dict(segment.get("data", {}))}
                for segment in event_data.get("segments", [])]}
            self.id = int(data.get("self_id", self.id))
            scene = event_data.get("message_scene", "group" if "group_id" in event_data else "friend")
            peer = int(event_data.get("peer_id", event_data.get("group_id", event_data.get("sender_id", 0))))
            self._cache_message({**event_data, "message_scene": scene, "peer_id": peer})
            for segment in event_data.get("segments", []):
                if segment.get("type") == "reply":
                    quoted = segment.get("data", {})
                    if quoted.get("segments"):
                        native_seq = int(quoted["message_seq"])
                        original = self._find_quoted_original(scene, peer, quoted) if native_seq == 0 else None
                        if native_seq == 0:
                            identity = json.dumps([self.id, scene, peer, quoted], sort_keys=True, ensure_ascii=False)
                            quoted["message_seq"] = -int(hashlib.sha256(identity.encode()).hexdigest()[:15], 16) - 1
                        # Reply payloads may contain only an abbreviated image/text preview.
                        # Keep the full original if it has already been received or fetched.
                        if self._cached_message(scene, peer, quoted["message_seq"]) is None:
                            self._cache_message({"message_scene": scene, "peer_id": peer,
                                "message_seq": quoted["message_seq"], "sender_id": quoted.get("sender_id", 0),
                                "native_message_seq": original["message_seq"] if original else native_seq,
                                "time": quoted.get("time", event_time),
                                "segments": original["segments"] if original else quoted["segments"],
                                "sender": {"user_id": quoted.get("sender_id", 0), "nickname": quoted.get("sender_name") or ""}})
            sender_info = event_data.get("group_member") or event_data.get("friend") or event_data.get("sender", {})
            milky_segments = await self._resolve_media_segments(event_data.get("segments", []))
            ob_message = self.milky_to_onebot_segments(milky_segments)

            # Let the existing OneBot event parse the structured message. A CQ
            # placeholder without id previously lost Reply.id in event.get().
            raw_msg = ""

            user_id = int(event_data.get("sender_id", sender_info.get("user_id", 0)))
            message_seq = int(event_data.get("message_seq", 0))

            sender_dict = {
                "user_id": user_id,
                "nickname": sender_info.get("nickname", ""),
                "card": sender_info.get("card", ""),
                "role": sender_info.get("role", "member"),
                "title": sender_info.get("title", ""),
            }

            if scene == "group":
                group_id = int(event_data.get("peer_id", event_data.get("group_id", 0)))
                ob_event_dict = {
                    "post_type": "message",
                    "message_type": "group",
                    "sub_type": "normal",
                    "message_id": message_seq,
                    "group_id": group_id,
                    "user_id": user_id,
                    "message": ob_message,
                    "raw_message": raw_msg,
                    "font": 0,
                    "sender": sender_dict,
                    "time": event_time,
                    "adapter_source": "milky",
                }
            else:
                ob_event_dict = {
                    "post_type": "message",
                    "message_type": "private",
                    "sub_type": "friend",
                    "message_id": message_seq,
                    "user_id": user_id,
                    "message": ob_message,
                    "raw_message": raw_msg,
                    "font": 0,
                    "sender": sender_dict,
                    "time": event_time,
                    "adapter_source": "milky",
                }

        elif event_type == "group_message_recall":
            ob_event_dict = {
                "post_type": "notice",
                "notice_type": "group_recall",
                "group_id": int(event_data.get("group_id", 0)),
                "user_id": int(event_data.get("author_id", 0)),
                "operator_id": int(event_data.get("operator_id", 0)),
                "message_id": int(event_data.get("message_seq", 0)),
                "time": event_time,
                "adapter_source": "milky",
            }

        elif event_type == "friend_message_recall":
            ob_event_dict = {
                "post_type": "notice",
                "notice_type": "friend_recall",
                "user_id": int(event_data.get("user_id", 0)),
                "message_id": int(event_data.get("message_seq", 0)),
                "time": event_time,
                "adapter_source": "milky",
            }

        elif event_type in ["group_nudge", "friend_nudge"]:
            sender_id = event_data.get("sender_id", event_data.get("user_id", 0))
            target_id = event_data.get("target_id", self.id)
            if event_type == "friend_nudge":
                sender_id = self.id if event_data.get("is_self_send") else event_data.get("user_id", 0)
                target_id = self.id if event_data.get("is_self_receive") else event_data.get("user_id", 0)
            ob_event_dict = {
                "post_type": "notice",
                "notice_type": "notify",
                "sub_type": "poke",
                "sender_id": int(sender_id),
                "user_id": int(sender_id),
                "target_id": int(target_id),
                "group_id": int(event_data.get("group_id", 0)) if "group_id" in event_data else None,
                "time": event_time,
                "adapter_source": "milky",
            }

        elif event_type == "group_member_increase":
            ob_event_dict = {
                "post_type": "notice",
                "notice_type": "group_increase",
                "sub_type": "approve",
                "group_id": int(event_data.get("group_id", 0)),
                "user_id": int(event_data.get("user_id", 0)),
                "operator_id": int(event_data.get("operator_id") or 0),
                "time": event_time,
                "adapter_source": "milky",
            }

        elif event_type == "group_member_decrease":
            ob_event_dict = {
                "post_type": "notice",
                "notice_type": "group_decrease",
                "sub_type": "leave",
                "group_id": int(event_data.get("group_id", 0)),
                "user_id": int(event_data.get("user_id", 0)),
                "operator_id": int(event_data.get("operator_id") or 0),
                "time": event_time,
                "adapter_source": "milky",
            }

        if event_type in ("group_admin_change", "group_member_mute", "group_whole_mute"):
            is_admin = event_type == "group_admin_change"
            duration = int(event_data.get("duration", 0))
            muted = event_data.get("is_mute", duration > 0)
            ob_event_dict = {"post_type": "notice", "notice_type": "group_admin" if is_admin else "group_ban",
                             "sub_type": ("set" if event_data.get("is_set") else "unset") if is_admin else ("ban" if muted else "lift_ban"),
                             "group_id": int(event_data.get("group_id", 0)), "user_id": int(event_data.get("user_id", 0)),
                             "operator_id": int(event_data.get("operator_id") or 0), "duration": duration,
                             "time": event_time, "adapter_source": "milky"}
        elif event_type in ("friend_request", "group_join_request", "group_invited_join_request", "group_invitation"):
            flag = uuid.uuid4().hex
            self._request_context[flag] = (event_type, dict(event_data))
            if len(self._request_context) > 1024:
                self._request_context.pop(next(iter(self._request_context)))
            ob_event_dict = {"post_type": "request", "request_type": "friend" if event_type == "friend_request" else "group",
                             "user_id": int(event_data.get("initiator_id", 0)), "flag": flag,
                             "comment": event_data.get("comment", ""), "time": event_time, "adapter_source": "milky"}
            if event_type != "friend_request":
                ob_event_dict.update(group_id=int(event_data.get("group_id", 0)),
                                     sub_type="invite" if event_type == "group_invitation" else "add")

        if not ob_event_dict:
            self.logger.debug(f"Milky 未处理事件类型: {event_type}")
            return
        if 'self_id' not in ob_event_dict:
            ob_event_dict['self_id'] = int(data.get("self_id", self.id))

        if event_type == "message_receive":
            self._remember_message(ob_event_dict["message_id"],
                                   "group" if ob_event_dict["message_type"] == "group" else "friend",
                                   ob_event_dict.get("group_id", event_data.get("peer_id", ob_event_dict["user_id"])))
            for segment in milky_segments:
                if segment.get("type") == "reply":
                    self._remember_message(segment["data"]["message_seq"], scene,
                                           event_data.get("peer_id", ob_event_dict.get("group_id", user_id)))


        event_obj = EventFactory.create_event(ob_event_dict)
        if not event_obj:
            self.logger.warning(f"无法解析事件类型: {ob_event_dict}")
            return

        if self.config and hasattr(self.config, "common_config"):
            cfg = self.config.common_config
            basic = cfg.basic_config
            if hasattr(event_obj, "group_id") and event_obj.group_id is not None:
                grp_logic = basic.get("group_handle_logic", "blacklist")
                censor_grp = convert_list_to_type(cfg.censor_group.get(grp_logic, []))
                if grp_logic == "blacklist" and event_obj.group_id in censor_grp:
                    self.logger.info(f"群 {event_obj.group_id} 在黑名单中，跳过处理。")
                    return
                elif grp_logic == "whitelist" and event_obj.group_id not in censor_grp:
                    self.logger.info(f"群 {event_obj.group_id} 不在白名单中，跳过处理。")
                    return

            if hasattr(event_obj, "user_id") and event_obj.user_id is not None:
                usr_logic = basic.get("user_handle_logic", "blacklist")
                censor_usr = convert_list_to_type(cfg.censor_user.get(usr_logic, []))
                if usr_logic == "blacklist" and event_obj.user_id in censor_usr:
                    self.logger.info(f"用户 {event_obj.user_id} 在黑名单中，跳过处理。")
                    return
                elif usr_logic == "whitelist" and event_obj.user_id not in censor_usr:
                    self.logger.info(f"用户 {event_obj.user_id} 不在白名单中，跳过处理。")
                    return

        asyncio.create_task(self.event_bus.emit(event_obj))

    async def _receive(self):
        try:
            async for raw in self.websocket:
                await self._message_queue.put(raw)
        except websockets.exceptions.ConnectionClosed as e:
            self.logger.warning(f"Milky Event WebSocket 连接关闭: {e}")
        except Exception as e:
            self.logger.error(f"Milky Event WS 接收异常: {e}", exc_info=True)

    async def _process_messages(self):
        while self._running:
            try:
                raw = await self._message_queue.get()
                try:
                    data = json.loads(raw)
                    await self._dispatch_milky_event(data)
                finally:
                    self._message_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"处理 Milky 事件发生异常: {e}", exc_info=True)

    async def _connect(self):
        try:
            headers = {}
            if self.access_token:
                headers["Authorization"] = f"Bearer {self.access_token}"
            import inspect
            sig = inspect.signature(websockets.connect)
            conn_kwargs = {"max_size": None}
            if "proxy" in sig.parameters:
                conn_kwargs["proxy"] = None
            if "additional_headers" in sig.parameters:
                if headers:
                    conn_kwargs["additional_headers"] = headers
            else:
                if headers:
                    conn_kwargs["extra_headers"] = list(headers.items())
            self.websocket = await websockets.connect(
                self.event_ws_url,
                **conn_kwargs
            )
            self.logger.info_msg("Milky Event WebSocket 连接已建立")
        except Exception as e:
            self.websocket = None
            self.logger.error(f"Milky Event WebSocket 连接错误: {e}")

    async def _connect_and_run(self):
        self._running = True
        while self._running:
            await self._run_connection()
            if self._running:
                await asyncio.sleep(5)

    async def _run_connection(self):

        try:
            info = await self._call_api("get_login_info")
            if info.get("status") == "ok" and "data" in info:
                self.id = int(info["data"].get("uin", self.id))
                self.logger.info(f"Milky 连接成功，当前登录 UIN: {self.id}, 昵称: {info['data'].get('nickname', '')}")
                meta_event = LifecycleMetaEvent(
                    time=int(time.time()),
                    self_id=self.id,
                    post_type="meta_event",
                    meta_event_type="lifecycle",
                    sub_type="connect"
                )
                asyncio.create_task(self.event_bus.emit(meta_event))
        except Exception as e:
            self.logger.warning(f"获取 Milky 登录信息失败: {e}")

        await self._connect()
        if self.websocket:
            self.receive_task = asyncio.create_task(self._receive())
            self._processing_task = asyncio.create_task(self._process_messages())
            try:
                await self.receive_task
            except Exception as e:
                self.logger.error(f"Milky 接收任务退出: {e}")
            finally:
                if self._processing_task and not self._processing_task.done():
                    self._processing_task.cancel()
                    await asyncio.gather(self._processing_task, return_exceptions=True)
                if self.websocket:
                    await self.websocket.close()
                self.websocket = None

    async def send(self, event: EventBase, components: Union[str, list], Quote: bool = False):
        if isinstance(components, str):
            components = [Text(components)]
        elif not isinstance(components, list):
            components = [components]

        if Quote and hasattr(event, "message_id"):
            components = [Reply(id=str(event.message_id)), *components]

        if hasattr(event, "group_id") and event.group_id:
            return await self.send_group_message(event.group_id, components)
        elif hasattr(event, "user_id") and event.user_id:
            return await self.send_friend_message(event.user_id, components)
        else:
            self.logger.error(f"无法推断目标发送目标: {event}")

    async def send_group_message(self, group_id: int, components: Union[str, list]):
        if isinstance(components, str):
            components = [Text(components)]
        elif not isinstance(components, list):
            components = [components]

        if components and isinstance(components[0], Node):
            return await self.send_group_forward_msg(group_id, components)

        milky_segs = self.onebot_to_milky_segments(components)
        self._restore_native_reply_ids(milky_segs, "group", group_id)
        params = {
            "group_id": int(group_id),
            "message": milky_segs
        }
        res = await self._call_api("send_group_message", params)
        if res.get("status") == "ok" and "data" in res:
            sequence = res["data"].get("message_seq", 0)
            self._remember_message(sequence, "group", group_id)
            self._cache_sent("group", group_id, res["data"], milky_segs)
            res["data"] = {**res["data"], "message_id": sequence}
        return res

    async def send_friend_message(self, user_id: int, components: Union[str, list]):
        if isinstance(components, str):
            components = [Text(components)]
        elif not isinstance(components, list):
            components = [components]

        if components and isinstance(components[0], Node):
            return await self.send_private_forward_msg(user_id, components)

        milky_segs = self.onebot_to_milky_segments(components)
        self._restore_native_reply_ids(milky_segs, "friend", user_id)
        params = {
            "user_id": int(user_id),
            "message": milky_segs
        }
        res = await self._call_api("send_private_message", params)
        if res.get("status") == "ok" and "data" in res:
            sequence = res["data"].get("message_seq", 0)
            self._remember_message(sequence, "friend", user_id)
            self._cache_sent("friend", user_id, res["data"], milky_segs)
            res["data"] = {**res["data"], "message_id": sequence}
        return res

    async def send_to_server(self, event: EventBase, message: Union[MessageChain, dict]):
        if isinstance(message, MessageChain):
            comps = list(message)
        elif isinstance(message, list):
            comps = message
        else:
            comps = [message]

        if hasattr(event, "group_id") and event.group_id:
            return await self.send_group_message(event.group_id, comps)
        elif hasattr(event, "user_id") and event.user_id:
            return await self.send_friend_message(event.user_id, comps)

    def _restore_native_reply_ids(self, segments, scene, peer):
        for segment in segments:
            if segment.get("type") == "reply":
                sequence = int(segment["data"]["message_seq"])
                if sequence < 0:
                    cached = self._cached_message(scene, peer, sequence)
                    if cached is None or "native_message_seq" not in cached:
                        raise ValueError("引用缓存不存在，不能把本地引用ID当作Milky序列号")
                    segment["data"]["message_seq"] = cached["native_message_seq"]

    async def recall(self, message_id: int, group_id: Optional[int] = None, user_id: Optional[int] = None):
        params = {"message_seq": int(message_id)}
        if group_id:
            params["group_id"] = int(group_id)
            return await self._call_api("recall_group_message", params)
        elif user_id:
            params["user_id"] = int(user_id)
            return await self._call_api("recall_private_message", params)
        else:
            contexts = self._message_context.get(int(message_id), set())
            if len(contexts) != 1:
                return {"status": "failed", "retcode": -1, "data": None,
                        "msg": "撤回需要明确 group_id/user_id；消息上下文缺失或序列号冲突"}
            scene, peer = next(iter(contexts))
            return await self.recall(message_id, group_id=peer if scene == "group" else None,
                                     user_id=peer if scene == "friend" else None)

    async def get_login_info(self):
        result = await self._call_api("get_login_info")
        if result.get("status") == "ok" and isinstance(result.get("data"), dict):
            result["data"]["user_id"] = result["data"].get("uin", self.id)
        return result

    def run(self):
        asyncio.run(self._connect_and_run())

    async def get_status(self):
        info = await self.get_login_info()
        is_ok = info.get("status") == "ok"
        return {
            "status": "ok",
            "retcode": 0,
            "data": {
                "online": is_ok,
                "good": is_ok,
                "user_id": self.id
            }
        }

    async def get_friend_list(self):
        res = await self._call_api("get_friend_list")
        if res.get("status") == "ok" and "data" in res:
            friends = res["data"].get("friends", [])
            return {"status": "ok", "retcode": 0, "data": friends}
        return res

    async def get_group_list(self):
        res = await self._call_api("get_group_list")
        if res.get("status") == "ok" and "data" in res:
            groups = res["data"].get("groups", [])
            return {"status": "ok", "retcode": 0, "data": groups}
        return res

    async def get_group_info(self, group_id: int, no_cache: bool = False):
        res = await self._call_api("get_group_info", {"group_id": int(group_id), "no_cache": no_cache})
        if res.get("status") == "ok" and "data" in res and "group" in res["data"]:
            return {"status": "ok", "retcode": 0, "data": res["data"]["group"]}
        return res

    async def get_group_member_list(self, group_id: int):
        res = await self._call_api("get_group_member_list", {"group_id": int(group_id)})
        if res.get("status") == "ok" and "data" in res and "members" in res["data"]:
            return {"status": "ok", "retcode": 0, "data": res["data"]["members"]}
        return res

    async def get_group_member_info(self, group_id: int, user_id: int, no_cache: bool = False):
        res = await self._call_api("get_group_member_info", {"group_id": int(group_id), "user_id": int(user_id), "no_cache": no_cache})
        if res.get("status") == "ok" and "data" in res and "member" in res["data"]:
            return {"status": "ok", "retcode": 0, "data": res["data"]["member"]}
        return res

    async def mute(self, group_id: int, user_id: int, duration: int = 1800):
        return await self._call_api("set_group_member_mute", {
            "group_id": int(group_id),
            "user_id": int(user_id),
            "duration": int(duration)
        })

    async def set_group_whole_ban(self, group_id: int, enable: bool = True):
        return await self._call_api("set_group_whole_mute", {
            "group_id": int(group_id),
            "is_mute": enable
        })

    async def set_group_card(self, group_id: int, user_id: int, card: str = ""):
        return await self._call_api("set_group_member_card", {
            "group_id": int(group_id),
            "user_id": int(user_id),
            "card": card
        })

    async def set_group_name(self, group_id: int, group_name: str):
        return await self._call_api("set_group_name", {
            "group_id": int(group_id),
            "new_group_name": group_name
        })

    async def set_group_kick(self, group_id: int, user_id: int, reject_add_request: bool = False):
        return await self._call_api("kick_group_member", {
            "group_id": int(group_id),
            "user_id": int(user_id),
            "reject_add_request": reject_add_request
        })

    async def quit(self, group_id: int):
        return await self._call_api("quit_group", {"group_id": int(group_id)})

    async def group_poke(self, group_id: int, user_id: int):
        return await self._call_api("send_group_nudge", {
            "group_id": int(group_id),
            "user_id": int(user_id)
        })

    async def friend_poke(self, user_id: int):
        return await self._call_api("send_friend_nudge", {"user_id": int(user_id)})

    async def send_group_forward_msg(self, group_id: int, components: Union[str, list]):
        segments = self.onebot_to_milky_segments(components if isinstance(components, list) else [components])
        return await self._send_forward("group", group_id, segments)

    async def send_private_forward_msg(self, user_id: int, components: Union[str, list]):
        segments = self.onebot_to_milky_segments(components if isinstance(components, list) else [components])
        return await self._send_forward("friend", user_id, segments)

    async def _send_forward(self, scene, peer_id, segments):
        result = await self._call_api("send_group_message" if scene == "group" else "send_private_message",
                                      {"group_id" if scene == "group" else "user_id": int(peer_id), "message": segments})
        if result.get("status") == "ok" and isinstance(result.get("data"), dict):
            sequence = result["data"].get("message_seq", 0)
            self._remember_message(sequence, scene, peer_id)
            self._cache_sent(scene, peer_id, result["data"], segments)
            result["data"]["message_id"] = sequence
        return result

    async def get_msg(self, message_id: int, group_id=None, user_id=None):
        contexts = set(self._message_context.get(int(message_id), set()))
        contexts.update(self._message_db.execute("SELECT scene,peer FROM messages WHERE account=? AND seq=?",
                        (self.id, int(message_id))).fetchall())
        if group_id is not None:
            scene, peer = "group", int(group_id)
        elif user_id is not None:
            scene, peer = "friend", int(user_id)
        elif _handler_peer.get() is not None and _handler_peer.get()[1] is not None:
            scene, peer = _handler_peer.get()
        elif len(contexts) == 1:
            scene, peer = next(iter(contexts))
        else:
            self.logger.warning("Milky get_msg 缺少会话上下文或序列号冲突，请提供 group_id/user_id")
            return None
        cached = self._cached_message(scene, peer, message_id)
        result = {"status": "ok", "data": {"message": cached}} if cached else await self._call_api("get_message", {"message_scene": scene, "peer_id": peer, "message_seq": int(message_id)})
        if not cached and (result.get("status") != "ok" or not (result.get("data") or {}).get("message")) and int(message_id) > 0:
            history = await self._call_api("get_history_messages", {"message_scene": scene, "peer_id": peer,
                                          "start_message_seq": int(message_id), "limit": 5})
            if history.get("status") == "ok":
                for message in (history.get("data") or {}).get("messages", []):
                    self._cache_message({**message, "message_scene": scene, "peer_id": peer})
                    if int(message.get("message_seq", -1)) == int(message_id):
                        result = {"status": "ok", "data": {"message": message}}
        if result.get("status") == "ok":
            message = (result.get("data") or {}).get("message", {})
            if not message:
                return None
            self._cache_message({**message, "message_scene": scene, "peer_id": peer, "message_seq": int(message_id)})
            sender = dict(message.get("group_member") or message.get("friend") or message.get("sender") or {})
            if sender.get("level") is not None:
                sender["level"] = str(sender["level"])
            user_id = int(message.get("sender_id", sender.get("user_id", 0)))
            segments = self.milky_to_onebot_segments(await self._resolve_media_segments(message.get("segments", []), refresh=True))
            event = {"post_type": "message", "message_type": "group" if scene == "group" else "private",
                     "sub_type": "normal" if scene == "group" else "friend", "self_id": self.id,
                     "time": message.get("time", int(time.time())), "message_id": int(message_id),
                     "user_id": user_id, "sender": {**sender, "user_id": user_id},
                     "message": segments, "raw_message": "", "font": 0, "adapter_source": "milky"}
            if scene == "group":
                event["group_id"] = peer
            return EventFactory.create_event(event)
        return None

    async def get_forward_msg(self, message_id: str):
        result = await self._call_api("get_forwarded_messages", {"forward_id": str(message_id)})
        if result.get("status") == "ok":
            messages = []
            for message in (result.get("data") or {}).get("messages", []):
                messages.append({**message, "sender": {"nickname": message.get("sender_name", ""),
                                                       "user_id": message.get("user_id", 0)},
                                 "content": self.milky_to_onebot_segments(await self._resolve_media_segments(message.get("segments", [])))})
            result["data"] = {"messages": messages}
        return result

    async def send_like(self, user_id):
        return await self._call_api("send_profile_like", {"user_id": int(user_id), "count": 10})

    async def delete_friend(self, user_id):
        return await self._call_api("delete_friend", {"user_id": int(user_id)})

    async def get_stranger_info(self, user_id):
        result = await self._call_api("get_user_profile", {"user_id": int(user_id)})
        if result.get("status") == "ok":
            result["data"]["user_id"] = int(user_id)
        return result

    async def set_qq_avatar(self, file):
        return await self._call_api("set_avatar", {"uri": self._media_uri(file)})

    async def set_group_admin(self, group_id, user_id, enable):
        return await self._call_api("set_group_member_admin", {"group_id": int(group_id), "user_id": int(user_id), "is_set": bool(enable)})

    async def set_group_special_title(self, group_id, user_id, special_title):
        return await self._call_api("set_group_member_special_title", {"group_id": int(group_id), "user_id": int(user_id), "special_title": special_title})

    async def upload_private_file(self, user_id, file, name=None):
        return await self._call_api("upload_private_file", {"user_id": int(user_id), "file_uri": self._media_uri(file), "file_name": name or os.path.basename(file)})

    async def upload_group_file(self, group_id, file, name=None):
        return await self._call_api("upload_group_file", {"group_id": int(group_id), "file_uri": self._media_uri(file), "file_name": name or os.path.basename(file)})

    async def get_group_root_files(self, group_id):
        return await self._call_api("get_group_files", {"group_id": int(group_id)})

    async def delete_group_file(self, group_id, file_id):
        return await self._call_api("delete_group_file", {"group_id": int(group_id), "file_id": file_id})

    async def create_group_file_folder(self, group_id, name):
        return await self._call_api("create_group_folder", {"group_id": int(group_id), "folder_name": name})

    async def delete_group_folder(self, group_id, folder_id):
        return await self._call_api("delete_group_folder", {"group_id": int(group_id), "folder_id": folder_id})

    async def _send_group_notice(self, group_id, content, image=None):
        params = {"group_id": int(group_id), "content": content}
        if image:
            params["image_uri"] = self._media_uri(image)
        return await self._call_api("send_group_announcement", params)

    async def _get_group_notice(self, group_id):
        return await self._call_api("get_group_announcements", {"group_id": int(group_id)})

    async def handle_friend_request(self, flag, approve, remark=""):
        context = self._request_context.get(str(flag))
        if not context or context[0] != "friend_request":
            return self._unsupported("好友请求 flag 未找到；需要适配器接收到的真实请求")
        payload = {"initiator_uid": context[1]["initiator_uid"], "is_filtered": context[1].get("is_filtered", False)}
        if not approve:
            payload["reason"] = remark
        return await self._call_api("accept_friend_request" if approve else "reject_friend_request", payload)

    async def set_group_add_request(self, flag, approve, reason=""):
        context = self._request_context.get(str(flag))
        if not context or context[0] == "friend_request":
            return self._unsupported("群请求 flag 未找到；需要适配器接收到的真实请求")
        kind, data = context
        if kind == "group_invitation":
            return await self._call_api("accept_group_invitation" if approve else "reject_group_invitation",
                                        {"group_id": data["group_id"], "invitation_seq": data["invitation_seq"]})
        payload = {"group_id": data["group_id"], "notification_seq": data["notification_seq"],
                   "notification_type": "join_request" if kind == "group_join_request" else "invited_join_request",
                   "is_filtered": data.get("is_filtered", False)}
        if not approve:
            payload["reason"] = reason
        return await self._call_api("accept_group_request" if approve else "reject_group_request", payload)

    @staticmethod
    def _unsupported(message):
        return {"status": "failed", "retcode": -1, "data": None, "msg": message}

    async def get_essence_msg_list(self, group_id):
        return await self._call_api("get_group_essence_messages", {"group_id": int(group_id), "page_index": 0, "page_size": 20})

    async def set_essence_msg(self, message_id):
        return await self._set_essence(message_id, True)

    async def delete_essence_msg(self, message_id):
        return await self._set_essence(message_id, False)

    async def _set_essence(self, message_id, setting):
        contexts = self._message_context.get(int(message_id), set())
        if len(contexts) != 1 or next(iter(contexts))[0] != "group":
            return self._unsupported("精华消息需要唯一群消息上下文")
        return await self._call_api("set_group_essence_message", {"group_id": next(iter(contexts))[1],
                                    "message_seq": int(message_id), "is_set": setting})

    async def get_group_file_url(self, file_id, group_id=None):
        if group_id is None:
            return self._unsupported("Milky 下载群文件需要额外提供 group_id")
        return await self._call_api("get_group_file_download_url", {"group_id": int(group_id), "file_id": file_id})

    async def get_group_ignore_add_request(self, group_id):
        result = await self._call_api("get_group_notifications", {"is_filtered": True})
        if result.get("status") == "ok":
            result["data"]["notifications"] = [item for item in result["data"].get("notifications", []) if item.get("group_id") == int(group_id)]
        return result

    async def set_friend_remark(self, user_id, remark):
        return self._unsupported("Milky 1.3 没有设置好友备注接口")

    async def set_friend_category(self, user_id, category_id):
        return self._unsupported("Milky 1.3 没有设置好友分组接口")

    async def get_group_honor_info(self, group_id):
        return self._unsupported("Milky 1.3 没有群荣誉接口")

    async def send_group_sign(self, group_id):
        return self._unsupported("Milky 1.3 没有群签到接口")

    async def get_record(self, file, out_format="mp3"):
        return self._unsupported("Milky 1.3 没有 OneBot 语音转码接口")

    async def get_video(self, url, path):
        return self._unsupported("Milky 1.3 没有 OneBot 视频下载扩展接口")

    async def get_ai_characters(self):
        return self._unsupported("Milky 1.3 没有 AI 语音角色接口")

    async def get_ai_record(self, group_id, character, text):
        return self._unsupported("Milky 1.3 没有 AI 语音合成接口")

    # Native Milky methods supplement the existing OneBot-compatible facade.
    # Availability is decided by the running server, never by prior test status.
    async def get_impl_info(self):
        return await self._call_api("get_impl_info")

    async def get_friend_info(self, user_id, no_cache=False):
        return await self._call_api("get_friend_info", {"user_id": int(user_id), "no_cache": no_cache})

    async def get_peer_pins(self):
        return await self._call_api("get_peer_pins")

    async def set_peer_pin(self, message_scene, peer_id, is_pinned=True):
        return await self._call_api("set_peer_pin", {"message_scene": message_scene, "peer_id": int(peer_id), "is_pinned": is_pinned})

    async def set_nickname(self, new_nickname):
        return await self._call_api("set_nickname", {"new_nickname": new_nickname})

    async def set_bio(self, new_bio):
        return await self._call_api("set_bio", {"new_bio": new_bio})

    async def get_custom_face_url_list(self):
        return await self._call_api("get_custom_face_url_list")

    async def get_cookies(self, domain):
        return await self._call_api("get_cookies", {"domain": domain})

    async def get_csrf_token(self):
        return await self._call_api("get_csrf_token")

    async def get_history_messages(self, message_scene, peer_id, limit=20, start_message_seq=None):
        params = {"message_scene": message_scene, "peer_id": int(peer_id), "limit": int(limit)}
        if start_message_seq is not None:
            params["start_message_seq"] = int(start_message_seq)
        return await self._call_api("get_history_messages", params)

    async def mark_message_as_read(self, message_scene, peer_id, message_seq):
        return await self._call_api("mark_message_as_read", {"message_scene": message_scene, "peer_id": int(peer_id), "message_seq": int(message_seq)})

    async def get_friend_requests(self, limit=20, is_filtered=False):
        return await self._call_api("get_friend_requests", {"limit": int(limit), "is_filtered": is_filtered})

    async def set_group_avatar(self, group_id, image_uri):
        return await self._call_api("set_group_avatar", {"group_id": int(group_id), "image_uri": self._media_uri(image_uri)})

    async def delete_group_announcement(self, group_id, announcement_id):
        return await self._call_api("delete_group_announcement", {"group_id": int(group_id), "announcement_id": announcement_id})

    async def send_group_message_reaction(self, group_id, message_seq, reaction, is_add=True, reaction_type="face"):
        return await self._call_api("send_group_message_reaction", {"group_id": int(group_id), "message_seq": int(message_seq), "reaction": str(reaction), "is_add": is_add, "reaction_type": reaction_type})

    async def get_private_file_download_url(self, user_id, file_id, file_hash, is_self_send=False):
        return await self._call_api("get_private_file_download_url", {"user_id": int(user_id), "file_id": file_id, "file_hash": file_hash, "is_self_send": is_self_send})

    async def move_group_file(self, group_id, file_id, parent_folder_id="/", target_folder_id="/"):
        return await self._call_api("move_group_file", {"group_id": int(group_id), "file_id": file_id, "parent_folder_id": parent_folder_id, "target_folder_id": target_folder_id})

    async def rename_group_file(self, group_id, file_id, new_file_name, parent_folder_id="/"):
        return await self._call_api("rename_group_file", {"group_id": int(group_id), "file_id": file_id, "new_file_name": new_file_name, "parent_folder_id": parent_folder_id})

    async def persist_group_file(self, group_id, file_id):
        return await self._call_api("persist_group_file", {"group_id": int(group_id), "file_id": file_id})

    async def rename_group_folder(self, group_id, folder_id, new_folder_name):
        return await self._call_api("rename_group_folder", {"group_id": int(group_id), "folder_id": folder_id, "new_folder_name": new_folder_name})

    async def close(self):
        self._running = False
        tasks = [task for task in (self.receive_task, self._processing_task)
                 if task and task is not asyncio.current_task() and not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self.websocket:
            try:
                await self.websocket.close()
            except Exception:
                pass
        if hasattr(self, '_http_client') and self._http_client:
            try:
                await self._http_client.aclose()
            except Exception:
                pass
        if self._message_db is not None:
            self._message_db.close()
            self._message_db = None

    async def aclose(self):
        await self.close()
