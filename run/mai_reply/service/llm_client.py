"""
llm_client.py
LLM客户端 —— 封装 OpenAI 兼容接口 & Gemini 接口的异步调用
支持：
  - 流式/非流式底层自动处理，对外统一返回纯文本(str)
  - 防网关超时：内部流式分块接收后自动拼接拼接
  - 自动拦截流式传输(SSE)中的工具调用(Function Calling)并静默执行
"""

import asyncio
import itertools
import json
import traceback
import inspect
from typing import List, Dict, Optional, Any, AsyncGenerator, Tuple, Callable, Awaitable

import httpx

from framework_common.utils.system_logger import get_logger
from framework_common.framework_util.yamlLoader import YAMLManager  # 【新增】引入框架配置管理器

logger=get_logger(__name__)

class LLMClient:

    def __init__(self, config):
        self.cfg = config
        lcfg = config.mai_reply.config.get("llm", {})
        self.provider: str = lcfg.get("provider", "openai").lower()

        # 是否在底层使用流式请求防超时
        self.use_stream: bool = lcfg.get("stream", False)
        self.max_tool_rounds: int = int(lcfg.get("max_tool_rounds", 10))

        # --- OpenAI 兼容配置
        oa = lcfg.get("openai", {})
        self._oa_keys: List[str] = oa.get("api_keys",[])
        self._oa_model: str = oa.get("model", "gpt-3.5-turbo")
        self._oa_base_url: str = oa.get("base_url", "https://api.openai.com").rstrip("/")
        self.no_extra_paramters: bool =oa.get("no_extra_paramters",False)
        self._oa_temperature: float = float(oa.get("temperature", 1.0))
        self._oa_max_tokens: int = int(oa.get("max_tokens", 1024)) if not oa.get("max_completion_tokens") else None
        self._oa_max_completion_tokens=int(oa.get("max_completion_tokens")) if oa.get("max_completion_tokens") else None

        # --- Gemini 配置
        gm = lcfg.get("gemini", {})
        self._gm_keys: List[str] = gm.get("api_keys",[])
        self._gm_model: str = gm.get("model", "gemini-2.0-flash-001")
        self._gm_base_url: str = gm.get("base_url", "https://generativelanguage.googleapis.com").rstrip("/")
        self._gm_temperature: float = float(gm.get("temperature", 1.0))
        self._gm_max_tokens: int = int(gm.get("max_output_tokens", 1024))

        # 循环迭代器（多key轮询）
        self._oa_key_cycle = itertools.cycle(self._oa_keys) if self._oa_keys else itertools.cycle([""])
        self._gm_key_cycle = itertools.cycle(self._gm_keys) if self._gm_keys else itertools.cycle([""])

        # httpx 共享客户端 (针对高并发复用连接池)
        limits = httpx.Limits(max_keepalive_connections=200, max_connections=500)
        self._http: Optional[httpx.AsyncClient] = httpx.AsyncClient(timeout=360.0, limits=limits)

    async def _get_http(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            limits = httpx.Limits(max_keepalive_connections=200, max_connections=500)
            self._http = httpx.AsyncClient(timeout=360.0, limits=limits)
        return self._http

    # ------------------------------------------------------------------ 统一入口
    async def chat(
        self,
        messages: List[Dict[str, str]],
        system_prompt: str = "",
        tools=None,
        retries: int = 3,
        stream: Optional[bool] = None,
        bot=None,
        event=None,
        model=None,
        on_intermediate_text: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> Optional[str]:
        """
        发送对话请求。
        不论内部是否使用流式传输防止网关超时，对外统一返回最终合并好的纯文本 (str)。
        """
        should_stream = self.use_stream if stream is None else stream

        if should_stream:
            return await self._chat_stream_with_retries(messages, system_prompt, tools, retries, bot, event, model, on_intermediate_text)
        else:
            return await self._chat_non_stream_with_retries(messages, system_prompt, tools, retries, bot, event, model, on_intermediate_text)

    # ==================================================================
    # 流式 (Stream) 执行引擎 (内部消费生成器，合并后返回)
    # ==================================================================
    async def _chat_stream_with_retries(self, messages, system_prompt, tools, retries, bot, event, model=None, on_intermediate_text=None) -> Optional[str]:
        for attempt in range(retries):
            try:
                full_text = ""
                if self.provider == "gemini":
                    async for chunk in self._chat_gemini_stream(messages, system_prompt, tools, bot, event, model, on_intermediate_text):
                        full_text += chunk
                else:
                    async for chunk in self._chat_openai_stream(messages, system_prompt, tools, bot, event, model, on_intermediate_text):
                        full_text += chunk

                return full_text.strip() if full_text else None
            except Exception as e:
                if attempt < retries - 1:
                    await asyncio.sleep(1.5 * (attempt + 1))
                else:
                    traceback.print_exc()
                    raise e
        return None

    async def _chat_openai_stream(self, messages: List[Dict], system_prompt: str, tools=None, bot=None, event=None, model=None, on_intermediate_text=None) -> AsyncGenerator[str, None]:
        api_key = next(self._oa_key_cycle)
        url = f"{self._oa_base_url}/chat/completions"

        full_messages =[]
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)
        tool_defs = self._build_openai_tool_defs(tools) if tools else None
        #print(tool_defs)
        for _round in range(self.max_tool_rounds):
            payload = {
                "model": self._oa_model if not model else model,
                "messages": full_messages,

                #"max_tokens": self._oa_max_tokens,
                "stream": True
            }
            if not self.no_extra_paramters:
                payload["temperature"]=self._oa_temperature
                if self._oa_max_completion_tokens:
                    payload["max_completion_tokens"]=self._oa_max_completion_tokens
                elif self._oa_max_tokens:
                    payload["max_tokens"]=self._oa_max_tokens
                if tool_defs:
                    payload["tools"] = tool_defs
                    payload["tool_choice"] = "auto"

            http = await self._get_http()
            #print(full_messages)
            #traceback.print_stack()
            api_key=api_key.strip()
            async with http.stream(
                "POST", url, json=payload,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},timeout=360
            ) as resp:
                resp.raise_for_status()

                is_tool_call = False
                tool_calls_dict = {}
                round_text = ""

                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data: "): continue
                    data_str = line[6:]
                    if data_str == "[DONE]": break
                    try:
                        data = json.loads(data_str)
                        choices = data.get("choices", [])
                        if not choices:
                            continue
                        delta = choices[0].get("delta", {})

                        if "content" in delta and delta["content"]:
                            round_text += delta["content"]
                            yield delta["content"]

                        if "tool_calls" in delta and delta["tool_calls"]:
                            is_tool_call = True
                            for tc in delta["tool_calls"]:
                                idx = tc["index"]
                                if idx not in tool_calls_dict:
                                    tool_calls_dict[idx] = {
                                        "id": tc.get("id", ""),
                                        "type": "function",
                                        "function": {"name": tc.get("function", {}).get("name", ""), "arguments": ""}
                                    }
                                else:
                                    if tc.get("id"): tool_calls_dict[idx]["id"] = tc["id"]
                                    if tc.get("function", {}).get("name"):
                                        tool_calls_dict[idx]["function"]["name"] = tc["function"]["name"]

                                func = tc.get("function", {})
                                if "arguments" in func:
                                    tool_calls_dict[idx]["function"]["arguments"] += func["arguments"]
                    except json.JSONDecodeError:
                        pass

                if not is_tool_call:
                    return

                if round_text.strip() and on_intermediate_text:
                    await on_intermediate_text(round_text)

                tool_calls_list =[tool_calls_dict[k] for k in sorted(tool_calls_dict.keys())]
                full_messages.append({"role": "assistant", "content": round_text or None, "tool_calls": tool_calls_list})
                tool_results, should_continue = await self._execute_openai_tool_calls(tool_calls_list, tools, bot, event)

                if not should_continue:
                    return
                full_messages.extend(tool_results)

    async def _chat_gemini_stream(self, messages: List[Dict], system_prompt: str, tools=None, bot=None, event=None, model=None, on_intermediate_text=None) -> AsyncGenerator[str, None]:
        api_key = next(self._gm_key_cycle)
        model=self._gm_model if not model else model
        url = f"{self._gm_base_url}/v1beta/models/{model}:streamGenerateContent?alt=sse&key={api_key}"

        gemini_tools = self._build_gemini_tool_defs(tools) if tools else None
        contents = self._build_gemini_contents(messages)
        for _round in range(self.max_tool_rounds):
            payload = {
                "contents": contents,
                "generationConfig": {"temperature": self._gm_temperature, "maxOutputTokens": self._gm_max_tokens},
            }
            if system_prompt:
                payload["system_instruction"] = {"parts":[{"text": system_prompt}]}
            if gemini_tools:
                payload["tools"] = gemini_tools

            http = await self._get_http()

            async with http.stream("POST", url, json=payload, headers={"Content-Type": "application/json"},timeout=360) as resp:
                resp.raise_for_status()

                is_tool_call = False
                func_call_parts_accum =[]
                round_text_parts = []

                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data: "): continue
                    data_str = line[6:]
                    try:
                        data = json.loads(data_str)
                        if "candidates" not in data or not data["candidates"]: continue
                        candidate = data["candidates"][0]
                        parts = candidate.get("content", {}).get("parts",[])

                        for part in parts:
                            if "text" in part:
                                round_text_parts.append(part["text"])
                                yield part["text"]
                            elif "functionCall" in part:
                                is_tool_call = True
                                func_call_parts_accum.append(part)
                    except json.JSONDecodeError:
                        pass

                if not is_tool_call:
                    return

                round_text = "".join(round_text_parts)
                if round_text.strip() and on_intermediate_text:
                    await on_intermediate_text(round_text)

                model_parts = []
                if round_text:
                    model_parts.append({"text": round_text})
                model_parts.extend(func_call_parts_accum)
                contents.append({"role": "model", "parts": model_parts})
                response_parts, should_continue = await self._execute_gemini_function_calls(func_call_parts_accum, tools, bot, event)

                if not should_continue:
                    return
                contents.append({"role": "user", "parts": response_parts})

    # ==================================================================
    # 非流式 (Non-Stream) 传统执行引擎
    # ==================================================================
    async def _chat_non_stream_with_retries(self, messages, system_prompt, tools, retries, bot, event, model=None, on_intermediate_text=None) -> Optional[str]:
        for attempt in range(retries):
            try:
                if self.provider == "gemini":
                    return await self._chat_gemini_non_stream(messages, system_prompt, tools, bot, event, model, on_intermediate_text)
                else:
                    return await self._chat_openai_non_stream(messages, system_prompt, tools, bot, event, model, on_intermediate_text)
            except Exception as e:
                if attempt < retries - 1:
                    await asyncio.sleep(1.5 * (attempt + 1))
                else:
                    traceback.print_exc()
                    raise e
        return None

    async def _chat_openai_non_stream(self, messages: List[Dict], system_prompt: str, tools=None, bot=None, event=None, model=None, on_intermediate_text=None) -> Optional[str]:
        api_key = next(self._oa_key_cycle)
        url = f"{self._oa_base_url}/chat/completions"
        full_messages =[{"role": "system", "content": system_prompt}] if system_prompt else[]
        full_messages.extend(messages)
        tool_defs = self._build_openai_tool_defs(tools) if tools else None
        temp_model=model if model else self._oa_model
        accumulated_text = ""
        for _round in range(self.max_tool_rounds):
            payload: Dict[str, Any] = {
                "model": temp_model, "messages": full_messages,
                #"max_tokens": self._oa_max_tokens,
            }
            if not self.no_extra_paramters:
                payload["temperature"]=self._oa_temperature
                if self._oa_max_completion_tokens:
                    payload["max_completion_tokens"]=self._oa_max_completion_tokens
                elif self._oa_max_tokens:
                    payload["max_tokens"]=self._oa_max_tokens
                if tool_defs:
                    payload["tools"] = tool_defs
                    payload["tool_choice"] = "auto"

            http = await self._get_http()
            resp = await http.post(url, json=payload, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},timeout=360)
            resp.raise_for_status()
            data = resp.json()

            choice = data["choices"][0]
            message = choice["message"]
            finish_reason = choice.get("finish_reason", "")

            if finish_reason != "tool_calls" or not message.get("tool_calls"):
                final_text = accumulated_text + (message.get("content") or "")
                return final_text.strip() or None

            text_before_tool = message.get("content") or ""
            if text_before_tool.strip() and on_intermediate_text:
                await on_intermediate_text(text_before_tool)
            accumulated_text += text_before_tool

            full_messages.append(message)
            tool_results, should_continue = await self._execute_openai_tool_calls(message["tool_calls"], tools, bot, event)

            if not should_continue:
                return accumulated_text.strip() or None
            full_messages.extend(tool_results)
        return None

    async def _chat_gemini_non_stream(self, messages: List[Dict], system_prompt: str, tools=None, bot=None, event=None, model=None, on_intermediate_text=None) -> Optional[str]:
        api_key = next(self._gm_key_cycle)
        temp_model=model if model else self._gm_model
        url = f"{self._gm_base_url}/v1beta/models/{temp_model}:generateContent?key={api_key}"
        contents = self._build_gemini_contents(messages)
        gemini_tools = self._build_gemini_tool_defs(tools) if tools else None
        accumulated_text = ""
        for _round in range(self.max_tool_rounds):
            payload: Dict[str, Any] = {
                "contents": contents,
                "generationConfig": {"temperature": self._gm_temperature, "maxOutputTokens": self._gm_max_tokens},
            }
            if system_prompt: payload["system_instruction"] = {"parts": [{"text": system_prompt}]}
            if gemini_tools: payload["tools"] = gemini_tools

            http = await self._get_http()
            resp = await http.post(url, json=payload, headers={"Content-Type": "application/json"},timeout=360)
            resp.raise_for_status()
            data = resp.json()

            candidate = data["candidates"][0]
            parts = candidate.get("content", {}).get("parts",[])
            func_call_parts =[p for p in parts if "functionCall" in p]
            text_parts =[p for p in parts if "text" in p]

            if not func_call_parts:
                final_text = accumulated_text + "".join(p["text"] for p in text_parts)
                return final_text.strip() or None

            text_before_tool = "".join(p["text"] for p in text_parts)
            if text_before_tool.strip() and on_intermediate_text:
                await on_intermediate_text(text_before_tool)
            accumulated_text += text_before_tool

            contents.append({"role": "model", "parts": text_parts + func_call_parts})
            response_parts, should_continue = await self._execute_gemini_function_calls(func_call_parts, tools, bot, event)

            if not should_continue:
                return accumulated_text.strip() or None
            contents.append({"role": "user", "parts": response_parts})
        return None

    # ==================================================================
    # 辅助构建与执行方法
    # ==================================================================
    def _build_gemini_contents(self, messages: List[Dict]) -> List[Dict]:
        contents = []
        for msg in messages:
            role = "user" if msg["role"] == "user" else "model"
            content = msg.get("content")

            if isinstance(content, str):
                contents.append({"role": role, "parts": [{"text": content}]})

            elif msg.get("role") == "tool":
                contents.append({
                    "role": "user",
                    "parts": [{"functionResponse": {
                        "name": msg.get("name", ""),
                        "response": {"result": msg.get("content", "")}
                    }}]
                })

            elif isinstance(content, list):
                parts = []
                for part in content:
                    if isinstance(part, dict):
                        if part.get("type") == "text":
                            parts.append({"text": part["text"]})
                        elif part.get("type") == "image_url":
                            # 支持 OpenAI vision 格式：data URI 或普通 URL
                            url_val = part.get("image_url", {}).get("url", "")
                            if url_val.startswith("data:"):
                                # data:image/png;base64,<b64data>
                                try:
                                    header, b64data = url_val.split(",", 1)
                                    mime = header.split(":")[1].split(";")[0]
                                    parts.append({
                                        "inlineData": {
                                            "mimeType": mime,
                                            "data": b64data
                                        }
                                    })
                                except Exception:
                                    pass
                            else:
                                # 普通 URL —— Gemini 支持 fileUri
                                parts.append({"fileData": {"fileUri": url_val, "mimeType": "image/jpeg"}})
                        elif "functionCall" in part:
                            parts.append(part)
                if parts:
                    contents.append({"role": role, "parts": parts})

        return contents

    @staticmethod
    def _build_openai_tool_defs(tools) -> List[Dict]:
        """
        将工具定义转换为 OpenAI 标准格式：
        [{"type": "function", "function": {"name": ..., "description": ..., "parameters": {...}}}]

        输入支持：
        - 已是 OpenAI 格式的 list（直接透传）
        - dict，值为 {"func": callable, "declaration": <Gemini 格式 decl>}（_load_tools 产出的标准结构）
        - dict，值为已经是 OpenAI 格式的 dict（含 "type" 字段）
        - dict，值为纯 callable（降级，仅用函数名/docstring）
        """
        if isinstance(tools, list):
            return tools

        if not isinstance(tools, dict):
            return []

        result = []
        for name, val in tools.items():
            # ── 情况 1：标准结构 {"func": ..., "declaration": <Gemini decl>} ──
            if isinstance(val, dict) and "func" in val:
                decl = val.get("declaration")
                if isinstance(decl, dict):
                    # Gemini 格式：{"name": ..., "description": ..., "parameters": {...}}
                    params = decl.get("parameters", {"type": "object", "properties": {}})
                    # 确保 required 字段存在（Gemini 有时省略它）
                    if "required" not in params:
                        params = dict(params)  # 浅拷贝，不污染原始数据
                        params["required"] = []
                    result.append({
                        "type": "function",
                        "function": {
                            "name": decl.get("name", name),
                            "description": decl.get("description", f"调用 {name}"),
                            "parameters": params,
                        }
                    })
                else:
                    # 没有 declaration，降级用 docstring
                    func = val["func"]
                    result.append({
                        "type": "function",
                        "function": {
                            "name": name,
                            "description": (getattr(func, "__doc__", None) or f"调用 {name}").strip(),
                            "parameters": {"type": "object", "properties": {}, "required": []},
                        }
                    })

            # ── 情况 2：已是 OpenAI 格式 {"type": "function", ...} ──
            elif isinstance(val, dict) and val.get("type") == "function":
                result.append(val)

            # ── 情况 3：旧式 {"declaration": ...} 结构（无 func 字段） ──
            elif isinstance(val, dict) and "declaration" in val:
                decl = val["declaration"]
                if isinstance(decl, dict):
                    # 可能是已包装好的 OpenAI 格式
                    if decl.get("type") == "function":
                        result.append(decl)
                    else:
                        # Gemini 格式
                        params = decl.get("parameters", {"type": "object", "properties": {}})
                        if "required" not in params:
                            params = dict(params)
                            params["required"] = []
                        result.append({
                            "type": "function",
                            "function": {
                                "name": decl.get("name", name),
                                "description": decl.get("description", f"调用 {name}"),
                                "parameters": params,
                            }
                        })

            # ── 情况 4：纯 callable（最低降级） ──
            elif callable(val):
                result.append({
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": (getattr(val, "__doc__", None) or f"调用 {name}").strip(),
                        "parameters": {"type": "object", "properties": {}, "required": []},
                    }
                })

        return result

    @staticmethod
    def _build_gemini_tool_defs(tools) -> List[Dict]:
        declarations =[]
        if isinstance(tools, dict):
            for name, val in tools.items():
                if isinstance(val, dict) and "declaration" in val:
                    decl = val["declaration"]
                    if "functionDeclarations" in decl:
                        declarations.extend(decl["functionDeclarations"])
                        continue
                    fn = decl.get("function", decl)
                    declarations.append({"name": fn.get("name", name), "description": fn.get("description", ""), "parameters": fn.get("parameters", {"type": "object", "properties": {}})})
                else:
                    declarations.append({"name": name, "description": getattr(val, "__doc__", f"调用 {name}") or "", "parameters": {"type": "object", "properties": {}}})
        return [{"functionDeclarations": declarations}] if declarations else[]

    async def _execute_openai_tool_calls(self, tool_calls: List[Dict], tools, bot=None, event=None) -> Tuple[List[Dict], bool]:
        """执行工具，动态注入上下文。若发生异常，自动终止下一轮调用防止死循环。"""
        func_map = {name: val["func"] if isinstance(val, dict) and "func" in val else val for name, val in tools.items()} if isinstance(tools, dict) else {}
        results =[]
        should_continue = True

        for tc in tool_calls:
            call_id, func_name = tc.get("id", ""), tc.get("function", {}).get("name", "")
            try: args = json.loads(tc.get("function", {}).get("arguments", "{}") or "{}")
            except: args = {}

            func = func_map.get(func_name)
            if not func:
                content = json.dumps({"error": f"未找到工具 {func_name}"}, ensure_ascii=False)
            else:
                try:
                    # 【核心修复】动态注入框架所需的对象
                    sig = inspect.signature(func)
                    if 'bot' in sig.parameters and bot is not None:
                        args['bot'] = bot
                    if 'event' in sig.parameters and event is not None:
                        args['event'] = event
                    if 'config' in sig.parameters:
                        # 【更新】通过单例获取全局 config
                        args['config'] = YAMLManager.get_instance()
                    logger.info(f"[MaiReply] 正在执行工具 {func_name}，参数: {args.keys()}")
                    ret = await func(**args) if asyncio.iscoroutinefunction(func) else await asyncio.to_thread(func, **args)

                    if ret is None:
                        should_continue = False

                    content = json.dumps(ret, ensure_ascii=False) if not isinstance(ret, str) else ret
                except Exception as e:
                    traceback.print_exc()
                    logger.error(
                        f"[MaiReply] 执行工具 {func_name} 时发生系统异常: {e!r}",
                        exc_info=True,
                    )
                    content = json.dumps({"error": str(e)}, ensure_ascii=False)
                    # 【防刷屏死循环机制】遇到崩溃级别的异常，直接强制中断
                    should_continue = False

            results.append({"role": "tool", "tool_call_id": call_id, "content": content})

        return results, should_continue

    async def _execute_gemini_function_calls(self, func_call_parts: List[Dict], tools, bot=None, event=None) -> Tuple[List[Dict], bool]:
        func_map = {name: val["func"] if isinstance(val, dict) and "func" in val else val for name, val in tools.items()} if isinstance(tools, dict) else {}
        response_parts =[]
        should_continue = True

        for part in func_call_parts:
            fc = part["functionCall"]
            func_name, args = fc.get("name", ""), fc.get("args", {})

            func = func_map.get(func_name)
            if not func:
                result = {"error": f"未找到工具 {func_name}"}
            else:
                try:
                    # 【核心修复】动态注入框架所需的对象
                    sig = inspect.signature(func)
                    if 'bot' in sig.parameters and bot is not None:
                        args['bot'] = bot
                    if 'event' in sig.parameters and event is not None:
                        args['event'] = event
                    if 'config' in sig.parameters:
                        # 【更新】通过单例获取全局 config
                        args['config'] = YAMLManager.get_instance()

                    ret = await func(**args) if asyncio.iscoroutinefunction(func) else await asyncio.to_thread(func, **args)

                    if ret is None:
                        should_continue = False

                    result = ret if isinstance(ret, dict) else {"result": str(ret)}
                except Exception as e:
                    logger.error(
                        f"[MaiReply] 执行工具 {func_name} 时发生系统异常: {e!r}",
                        exc_info=True,
                    )
                    result = {"error": str(e)}
                    # 【防刷屏死循环机制】遇到崩溃级别的异常，直接强制中断
                    should_continue = False

            response_parts.append({"functionResponse": {"name": func_name, "response": result}})

        return response_parts, should_continue

    async def aclose(self):
        if self._http and not self._http.is_closed:
            await self._http.aclose()
