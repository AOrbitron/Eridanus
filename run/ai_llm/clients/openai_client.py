# https://github.com/spawner1145/llm-api-backup/blob/main/openai_advance.py

import httpx
import json
import mimetypes
import asyncio
import base64
import os
import uuid
from typing import AsyncGenerator, Dict, List, Optional, Union, Callable
import aiofiles
import logging
from openai import AsyncOpenAI

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class OpenAIAPI:
    def __init__(
        self,
        apikey: str,
        baseurl: str = "https://api-inference.modelscope.cn",
        model: str = "deepseek-ai/DeepSeek-R1",
        proxies: Optional[Dict[str, str]] = None
    ):
        self.apikey = apikey
        self.baseurl = baseurl.rstrip('/')
        self.model = model
        self.client = AsyncOpenAI(
            api_key=apikey,
            base_url=baseurl,
            http_client=httpx.AsyncClient(proxies=proxies, timeout=60.0) if proxies else None
        )

    async def upload_file(self, file_path: str, display_name: Optional[str] = None) -> Dict[str, Union[str, None]]:
        """上传单个文件，使用 client.files.create，目的为 user_data"""
        try:
            file_size = os.path.getsize(file_path)
            if file_size > 32 * 1024 * 1024:  # 32MB 限制
                raise ValueError(f"文件 {file_path} 大小超过 32MB 限制")
        except FileNotFoundError:
            logger.error(f"文件 {file_path} 不存在")
            return {"fileId": None, "mimeType": None, "error": f"文件 {file_path} 不存在"}

        mime_type, _ = mimetypes.guess_type(file_path)
        if not mime_type:
            mime_type = "application/octet-stream"
            logger.warning(f"无法检测文件 {file_path} 的 MIME 类型，使用默认值: {mime_type}")

        supported_mime_types = [
            "application/pdf", "image/jpeg", "image/png", "image/webp", "image/gif"
        ]
        if mime_type not in supported_mime_types:
            logger.warning(f"MIME 类型 {mime_type} 可能不受支持，可能导致处理失败")

        try:
            async with aiofiles.open(file_path, 'rb') as f:
                file = await self.client.files.create(
                    file=(display_name or os.path.basename(file_path), await f.read(), mime_type),
                    purpose="user_data"
                )
                file_id = file.id
                logger.info(f"文件 {file_path} 上传成功，ID: {file_id}")
                return {"fileId": file_id, "mimeType": mime_type, "error": None}
        except Exception as e:
            logger.error(f"文件 {file_path} 上传失败: {str(e)}")
            return {"fileId": None, "mimeType": mime_type, "error": str(e)}

    async def upload_files(self, file_paths: List[str], display_names: Optional[List[str]] = None) -> List[Dict[str, Union[str, None]]]:
        """并行上传多个文件"""
        if not file_paths:
            raise ValueError("文件路径列表不能为空")

        if display_names and len(display_names) != len(file_paths):
            raise ValueError("display_names 长度必须与 file_paths 一致")

        tasks = [self.upload_file(file_paths[idx], display_names[idx] if display_names else None) for idx in range(len(file_paths))]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        final_results = []
        for idx, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"上传文件 {file_paths[idx]} 失败: {str(result)}")
                final_results.append({"fileId": None, "mimeType": None, "error": str(result)})
            else:
                final_results.append(result)
        return final_results

    async def prepare_inline_image(self, file_path: str, detail: str = "auto") -> Dict[str, Union[Dict, None]]:
        """将单个图片转换为 Base64 编码的 input_image"""
        try:
            file_size = os.path.getsize(file_path)
            if file_size > 20 * 1024 * 1024:  # 20MB 限制
                raise ValueError(f"文件 {file_path} 过大，超过 20MB 限制")

            mime_type, _ = mimetypes.guess_type(file_path)
            if not mime_type or mime_type not in ["image/jpeg", "image/png", "image/webp", "image/gif"]:
                mime_type = "image/jpeg"
                logger.warning(f"无效图片 MIME 类型，使用默认值: {mime_type}")

            async with aiofiles.open(file_path, 'rb') as f:
                file_content = await f.read()
            base64_data = base64.b64encode(file_content).decode('utf-8')
            return {
                "input_image": {
                    "image_url": f"data:{mime_type};base64,{base64_data}",
                    "detail": detail
                }
            }
        except Exception as e:
            logger.error(f"处理图片 {file_path} 失败: {str(e)}")
            return {"input_image": None, "error": str(e)}

    async def prepare_inline_image_batch(self, file_paths: List[str], detail: str = "auto") -> List[Dict[str, Union[Dict, None]]]:
        """将多个图片转换为 Base64 编码的 input_image 列表"""
        if not file_paths:
            raise ValueError("文件路径列表不能为空")

        results = []
        for file_path in file_paths:
            result = await self.prepare_inline_image(file_path, detail)
            results.append(result)
        return results

    async def _execute_tool(
        self,
        tool_calls: List[Union[Dict, any]],
        tools: Dict[str, Callable],
        tool_fixed_params: Optional[Dict[str, Dict]] = None
    ) -> List[Dict]:
        async def run_single_tool(tool_call):
            if isinstance(tool_call, dict):
                name = tool_call["function"]["name"]
                arguments = tool_call["function"]["arguments"]
                tool_call_id = tool_call.get("id")
            else:
                name = tool_call.function.name
                arguments = tool_call.function.arguments
                tool_call_id = tool_call.id
            
            tool_call_id = tool_call_id or f"call_{uuid.uuid4()}"
            
            try:
                args = json.loads(arguments)
                func = tools.get(name)
                
                if not func:
                    return {"role": "tool", "content": json.dumps({"error": f"未找到工具 {name}"}), "tool_call_id": tool_call_id}

                fixed_params = tool_fixed_params.get(name, tool_fixed_params.get("all", {})) if tool_fixed_params else {}
                combined_args = {**fixed_params, **args}
                
                if args:
                    logger.info(f"[Tool Call] {name} | 参数: {args}")
                else:
                    logger.info(f"[Tool Call] {name} | 无自由参数")
                
                if asyncio.iscoroutinefunction(func):
                    result = await func(**combined_args)
                else:
                    result = await asyncio.to_thread(func, **combined_args)
                
                return {
                    "role": "tool",
                    "content": json.dumps(result, ensure_ascii=False),
                    "tool_call_id": tool_call_id
                }
            except Exception as e:
                logger.error(f"工具 {name} 执行失败: {str(e)}")
                return {"role": "tool", "content": json.dumps({"error": str(e)}, ensure_ascii=False), "tool_call_id": tool_call_id}

        tasks = [run_single_tool(tc) for tc in tool_calls]
        return list(await asyncio.gather(*tasks))

    @staticmethod
    def _convert_messages(messages: List[Dict]) -> List[Dict]:
        """将内部消息格式转换为 OpenAI API 格式，并自动修正 role=model → assistant。"""
        api_messages = []
        for msg in messages:
            try:
                role = msg["role"]
            except Exception as e:
                continue
            #修正初次启动对话报错。
            if role == "model":
                role = "assistant"

            content = msg.get("content", "")
            if isinstance(content, str):
                api_content = [{"type": "text", "text": content}]
            elif isinstance(content, list):
                api_content = []
                for part in content:
                    if "text" in part:
                        api_content.append({"type": "text", "text": part["text"]})
                    elif "input_file" in part:
                        f = part["input_file"]
                        api_content.append(
                            {"type": "input_file", "file_id": f["file_id"]}
                            if "file_id" in f
                            else {"type": "input_file", "filename": f["filename"], "file_data": f["file_data"]}
                        )
                    elif "input_image" in part:
                        img = part["input_image"]
                        api_content.append({
                            "type": "image_url",
                            "image_url": {"url": img["image_url"], "detail": img.get("detail", "auto")},
                        })
                    elif part.get("type") == "image_url" and "image_url" in part:
                        api_content.append(part)
            else:
                raise ValueError(f"无效的消息内容格式: {content}")

            api_msg = {"role": role, "content": api_content}
            if "tool_calls" in msg:
                api_msg["tool_calls"] = msg["tool_calls"]
            if "tool_call_id" in msg:
                api_msg["tool_call_id"] = msg["tool_call_id"]

            logger.debug(f"构造消息: {json.dumps(api_msg, ensure_ascii=False)}")
            api_messages.append(api_msg)
        return api_messages

    # ──────────────────────────────────────────────
    # 辅助：构建 OpenAI 请求参数
    # ──────────────────────────────────────────────
    def _build_request_params(
            self,
            api_messages,
            stream,
            tools=None,
            tool_fixed_params=None,
            tool_declarations=None,
            max_output_tokens=None,
            topp=None,
            temperature=None,
            presence_penalty=None,
            frequency_penalty=None,
            stop_sequences=None,
            response_format=None,
            reasoning_effort=None,
            seed=None,
            response_logprobs=None,
            logprobs=None,
    ) -> dict:
        #params = {"model": self.model, "messages": api_messages, "stream": stream}
        for msg in api_messages:
            if isinstance(msg.get('content'), list):
                msg['content'] = [
                    {'type': item['type'], 'text': '艾特你了'} if (
                            isinstance(item, dict) and
                            item.get('type') == 'text' and
                            not item.get('text', '').strip()
                    ) else item
                    for item in msg['content']
                    if item is not None
                ]

        params = {"model": self.model, "messages": api_messages, "stream": stream}
        print(api_messages)
        #if max_output_tokens is not None: params["max_tokens"] = max_output_tokens
        if topp is not None: params["top_p"] = topp
        if temperature is not None: params["temperature"] = temperature
        if stop_sequences is not None: params["stop"] = stop_sequences
        if presence_penalty is not None: params["presence_penalty"] = presence_penalty
        if frequency_penalty is not None: params["frequency_penalty"] = frequency_penalty
        if seed is not None: params["seed"] = seed
        if response_logprobs is not None:
            params["logprobs"] = response_logprobs
            if logprobs is not None:
                params["top_logprobs"] = logprobs
        if response_format:               params["response_format"] = response_format
        if reasoning_effort is not None: params["reasoning_effort"] = reasoning_effort

        if tools is not None:
            tool_defs = []
            if tool_declarations:
                tool_names = set(tools.keys())
                for decl in tool_declarations:
                    if decl.get("name") not in tool_names:
                        continue
                    p = decl.get("parameters", {"type": "object", "properties": {}, "required": []})
                    p.setdefault("additionalProperties", False)
                    tool_defs.append({
                        "type": "function",
                        "function": {
                            "name": decl["name"],
                            "description": decl.get("description", f"调用 {decl['name']} 函数"),
                            "parameters": p,
                        },
                    })
                if not tool_defs:
                    logger.warning("tool_declarations 中没有与 tools 匹配的函数声明，回退到自动推断")
                    tool_declarations = None

            if not tool_declarations:
                fixed = (tool_fixed_params or {}).get("all", {})
                for name, func in tools.items():
                    p = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
                    if hasattr(func, "__code__"):
                        dynamic = [
                            v for v in func.__code__.co_varnames[:func.__code__.co_argcount]
                            if v not in fixed
                        ]
                        p["properties"] = {v: {"type": "string"} for v in dynamic}
                        p["required"] = dynamic
                    else:
                        p["properties"] = {"arg": {"type": "string"}}
                        p["required"] = ["arg"]
                    tool_defs.append({
                        "type": "function",
                        "function": {
                            "name": name,
                            "description": getattr(func, "__doc__", f"调用 {name} 函数"),
                            "parameters": p,
                        },
                    })

            if tool_defs:
                params["tools"] = tool_defs

        return params

    # ──────────────────────────────────────────────
    # 辅助：空响应时清除上下文并重建 api_messages
    # ──────────────────────────────────────────────
    async def _clear_context_and_rebuild(
            self,
            messages: list,
            api_messages: list,
            request_params: dict,
            on_clear_context,
    ):
        try:
            await on_clear_context()
            system_msgs = [m for m in messages if m.get("role") == "system"]
            last_user = next((m for m in reversed(messages) if m.get("role") == "user"), None)
            if last_user:
                messages.clear()
                messages.extend(system_msgs)
                messages.append(last_user)
                rebuilt = self._convert_messages(messages)
                api_messages.clear()
                api_messages.extend(rebuilt)
                request_params["messages"] = api_messages
        except Exception as e:
            logger.error(f"清除上下文失败: {e}")

    # ──────────────────────────────────────────────
    # 辅助：yield reasoning + content（非流式单条消息）
    # ──────────────────────────────────────────────
    @staticmethod
    async def _yield_message(message):
        if hasattr(message, "reasoning_content") and message.reasoning_content:
            yield {"thought": message.reasoning_content}
        if message.content:
            yield message.content

    # ──────────────────────────────────────────────
    # 辅助：处理工具调用并续接（流式/非流式共用）
    # ──────────────────────────────────────────────
    async def _handle_tool_calls_openai(
            self,
            tool_calls_raw,  # list[dict] 或 SDK tool_call 对象列表
            api_messages: list,
            messages: list,
            request_params: dict,
            tools,
            tool_fixed_params,
            stream: bool,
    ):
        # 统一转换为 dict 格式
        tool_calls = []
        for tc in tool_calls_raw:
            if isinstance(tc, dict):
                tc_dict = tc
            else:
                tc_dict = {
                    "id": tc.id or f"call_{uuid.uuid4()}",
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                if hasattr(tc, "extra_content") and tc.extra_content:
                    tc_dict["extra_content"] = tc.extra_content
            tool_calls.append(tc_dict)

        assistant_message = {
            "role": "assistant",
            "content": [{"type": "text", "text": "Tool calls executed"}],
            "tool_calls": tool_calls,
        }
        api_messages.append(assistant_message)
        messages.append(assistant_message)

        tool_messages = await self._execute_tool(tool_calls_raw, tools, tool_fixed_params)
        api_messages.extend(tool_messages)
        messages.extend(tool_messages)

        followup_params = {**request_params, "messages": api_messages, "stream": stream}

        if stream:
            try:
                async for chunk in await self.client.chat.completions.create(**followup_params):
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                        yield {"thought": delta.reasoning_content}
                    if delta.content:
                        yield delta.content
                    if chunk.choices[0].finish_reason in ("stop", "length"):
                        break
            except Exception as e:
                logger.error(f"工具调用后续接失败: {e}")
                yield f"[错误] 无法获取工具调用后的响应 - {e}"
        else:
            resp = await self.client.chat.completions.create(**followup_params)
            msg = resp.choices[0].message
            messages.append({
                "role": "assistant",
                "content": [{"type": "text", "text": msg.content or ""}],
            })
            async for chunk in self._yield_message(msg):
                yield chunk

    # ──────────────────────────────────────────────
    # 核心 API 调用（精简版）
    # ──────────────────────────────────────────────
    async def _chat_api(
            self,
            messages: List[Dict],
            stream: bool,
            tools=None,
            tool_fixed_params=None,
            tool_declarations=None,
            max_output_tokens=None,
            system_instruction=None,
            topp=None,
            temperature=None,
            presence_penalty=None,
            frequency_penalty=None,
            stop_sequences=None,
            response_format=None,
            reasoning_effort=None,
            seed=None,
            response_logprobs=None,
            logprobs=None,
            retries=3,
            on_clear_context=None,
    ):
        original_model = self.model

        # ---------- 参数校验 ----------
        if topp is not None and not (0 <= topp <= 1):               raise ValueError("top_p 必须在 0 到 1 之间")
        if temperature is not None and not (0 <= temperature <= 2):        raise ValueError(
            "temperature 必须在 0 到 2 之间")
        if presence_penalty is not None and not (-2 <= presence_penalty <= 2):  raise ValueError(
            "presence_penalty 必须在 -2 到 2 之间")
        if frequency_penalty is not None and not (-2 <= frequency_penalty <= 2): raise ValueError(
            "frequency_penalty 必须在 -2 到 2 之间")
        if logprobs is not None and not (0 <= logprobs <= 20):          raise ValueError(
            "logprobs 必须在 0 到 20 之间")
        if reasoning_effort is not None and reasoning_effort not in ("minimal", "low", "medium", "high"):
            raise ValueError("reasoning_effort 必须是 minimal、low、medium 或 high")

        api_messages = self._convert_messages(messages)
        request_params = self._build_request_params(
            api_messages, stream,
            tools=tools, tool_fixed_params=tool_fixed_params,
            tool_declarations=tool_declarations,
            max_output_tokens=max_output_tokens, topp=topp, temperature=temperature,
            presence_penalty=presence_penalty, frequency_penalty=frequency_penalty,
            stop_sequences=stop_sequences, response_format=response_format,
            reasoning_effort=reasoning_effort, seed=seed,
            response_logprobs=response_logprobs, logprobs=logprobs,
        )

        clear_threshold = max(1, retries - 2)

        # ══════════════════════════════════════════
        # 流式
        # ══════════════════════════════════════════
        if stream:
            assistant_content = ""
            tool_calls_buffer = []
            try:
                logger.info(f"开始流式请求: model={self.model}, base_url={self.baseurl}")
                async for chunk in await self.client.chat.completions.create(**request_params):
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    finish_reason = chunk.choices[0].finish_reason

                    if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                        yield {"thought": delta.reasoning_content}

                    if delta.content:
                        yield delta.content
                        assistant_content += delta.content
                    elif hasattr(delta, "text") and delta.text:
                        yield delta.text
                        assistant_content += delta.text

                    # 累积工具调用 delta
                    if hasattr(delta, "tool_calls") and delta.tool_calls:
                        for tc in delta.tool_calls:
                            if tc is None:
                                continue
                            idx = getattr(tc, "index", None) or len(tool_calls_buffer)
                            while len(tool_calls_buffer) <= idx:
                                tool_calls_buffer.append(
                                    {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                            entry = tool_calls_buffer[idx]
                            if tc.id:                          entry["id"] = tc.id
                            if tc.function:
                                if tc.function.name:           entry["function"]["name"] += tc.function.name
                                if tc.function.arguments:      entry["function"][
                                    "arguments"] += tc.function.arguments

                    if finish_reason == "tool_calls" and tool_calls_buffer:
                        valid = [tc for tc in tool_calls_buffer if tc["function"]["name"]]
                        for tc in valid:
                            if not tc["id"]:
                                tc["id"] = f"call_{uuid.uuid4()}"
                        if not valid:
                            logger.warning("没有有效的工具调用")
                            tool_calls_buffer = []
                            continue
                        async for chunk in self._handle_tool_calls_openai(
                                valid, api_messages, messages, request_params, tools, tool_fixed_params, stream=True
                        ):
                            yield chunk
                        tool_calls_buffer = []

                    if finish_reason in ("stop", "length"):
                        if assistant_content:
                            messages.append(
                                {"role": "assistant", "content": [{"type": "text", "text": assistant_content}]})
                        assistant_content = ""

                # 检测空响应
                if not assistant_content and not tool_calls_buffer:
                    has_content = any(
                        m.get("role") == "assistant"
                        and any(c.get("text", "").strip() for c in m.get("content", []) if isinstance(c, dict))
                        for m in messages[-2:]
                    )
                    if not has_content:
                        logger.warning("OpenAI 流式响应内容为空")
                        if on_clear_context:
                            try:
                                await on_clear_context()
                            except Exception as e:
                                logger.error(f"清除上下文失败: {e}")
                        yield "[错误] AI流式响应内容为空（可能被内容安全过滤拦截）。已自动清除上下文，请重新提问。"

            except httpx.TimeoutException as e:
                logger.error(f"流式请求超时: {e}")
                yield "[错误] OpenAI 流式请求超时，请检查网络或稍后重试。"
            except httpx.ConnectError as e:
                logger.error(f"流式请求连接失败: {e}")
                yield "[错误] OpenAI 流式请求连接失败，请检查网络或代理设置。"
            except Exception as e:
                logger.error(f"流式请求失败: {type(e).__name__}: {e}")
                yield f"[错误] OpenAI 流式请求失败（{type(e).__name__}: {e}）"

        # ══════════════════════════════════════════
        # 非流式（带重试）
        # ══════════════════════════════════════════
        else:
            for attempt in range(retries):
                try:
                    response = await self.client.chat.completions.create(**request_params)

                    # ── 无 choices ──
                    if not response.choices:
                        logger.warning(f"无 choices（第 {attempt + 1}/{retries} 次）")
                        if attempt >= clear_threshold and on_clear_context:
                            await self._clear_context_and_rebuild(messages, api_messages, request_params,
                                                                  on_clear_context)
                        if attempt == retries - 1:
                            yield f"[错误] AI响应内容为空（无 choices），已重试{retries}次。请尝试 /clear 清除上下文后重新提问。"
                            break
                        await asyncio.sleep(2 ** attempt)
                        continue

                    choice = response.choices[0]
                    message = choice.message

                    # ── content 为空且无工具调用 ──
                    if not message.content and not message.tool_calls:
                        finish_reason = choice.finish_reason or "未知"
                        logger.warning(
                            f"content 为空（第 {attempt + 1}/{retries} 次），finish_reason: {finish_reason}")
                        if attempt >= clear_threshold and on_clear_context:
                            await self._clear_context_and_rebuild(messages, api_messages, request_params,
                                                                  on_clear_context)
                        if attempt == retries - 1:
                            yield f"[错误] AI响应内容为空（finish_reason: {finish_reason}），已重试{retries}次。请尝试 /clear 清除上下文后重新提问。"
                            break
                        await asyncio.sleep(2 ** attempt)
                        continue

                    # ── 工具调用 ──
                    if message.tool_calls:
                        async for chunk in self._handle_tool_calls_openai(
                                message.tool_calls, api_messages, messages, request_params, tools,
                                tool_fixed_params, stream=False
                        ):
                            yield chunk
                    else:
                        # ── 正常响应 ──
                        assistant_message = {
                            "role": "assistant",
                            "content": [{"type": "text", "text": message.content or ""}],
                        }
                        if response_logprobs and choice.logprobs:
                            assistant_message["logprobs"] = choice.logprobs.content
                            messages.append(assistant_message)
                            async for chunk in self._yield_message(message):
                                yield chunk
                            yield f"\nLogprobs: {json.dumps(choice.logprobs.content, ensure_ascii=False)}"
                        else:
                            messages.append(assistant_message)
                            async for chunk in self._yield_message(message):
                                yield chunk
                    break

                except (httpx.ConnectError, httpx.TimeoutException) as e:
                    logger.error(f"网络错误 (尝试 {attempt + 1}/{retries}): {type(e).__name__}: {e}")
                    if attempt == retries - 1:
                        yield f"[错误] OpenAI 请求网络连接失败（{type(e).__name__}），已重试{retries}次。请检查网络或代理设置。"
                        break
                    await asyncio.sleep(2 ** attempt)
                except Exception as e:
                    logger.error(f"API 调用失败 (尝试 {attempt + 1}/{retries}): {e}")
                    if attempt == retries - 1:
                        yield f"[错误] OpenAI 请求失败（{type(e).__name__}: {e}），已重试{retries}次"
                        break
                    await asyncio.sleep(2 ** attempt)

        self.model = original_model

    async def chat(
        self,
        messages: Union[str, List[Dict[str, any]]],
        stream: bool = False,
        tools: Optional[Dict[str, Callable]] = None,
        tool_fixed_params: Optional[Dict[str, Dict]] = None,
        tool_declarations: Optional[List[Dict]] = None,
        max_output_tokens: Optional[int] = None,
        system_instruction: Optional[str] = None,
        topp: Optional[float] = None,
        temperature: Optional[float] = None,
        presence_penalty: Optional[float] = None,
        frequency_penalty: Optional[float] = None,
        stop_sequences: Optional[List[str]] = None,
        response_format: Optional[Dict] = None,
        reasoning_effort: Optional[str] = None,
        seed: Optional[int] = None,
        response_logprobs: Optional[bool] = None,
        logprobs: Optional[int] = None,
        retries: int = 3,
        on_clear_context: Optional[Callable] = None
    ) -> AsyncGenerator[Union[str, Dict], None]:
        """发起聊天请求，支持多文件和多图片输入"""
        if isinstance(messages, str):
            messages = [{"role": "user", "content": [{"type": "text", "text": messages}]}]
        if system_instruction:
            for i, message in enumerate(messages):
                if message.get("role") == "system":
                    messages[i] = {"role": "system", "content": [{"type": "text", "text": system_instruction}]}
                    break
            else:
                messages.insert(0, {"role": "system", "content": [{"type": "text", "text": system_instruction}]})

        async for part in self._chat_api(
            messages, stream, tools, tool_fixed_params, tool_declarations,
            max_output_tokens, system_instruction, topp, temperature,
            presence_penalty, frequency_penalty,
            stop_sequences, response_format,
            reasoning_effort, seed, response_logprobs, logprobs,
            retries, on_clear_context=on_clear_context
        ):
            yield part

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.client.aclose()

# 示例工具函数
async def schedule_meeting(event: str, config: Dict, start_time: str, duration: str, attendees: str) -> str:
    """安排一个会议，参数包括事件、配置、开始时间、持续时间和与会者"""
    return f"会议已安排：事件 {event}，配置 {config}，开始时间 {start_time}，持续时间 {duration}，与会者 {attendees}。"

async def get_weather(event: str, config: Dict, location: str) -> str:
    """获取指定地点的天气信息"""
    return f"{location} 的天气是晴天，温度 25°C（事件 {event}，配置 {config}）。"

async def get_time(event: str, config: Dict, city: str) -> str:
    """获取指定城市的当前时间"""
    return f"{city} 的当前时间是 2025 年 4 月 24 日 13:00（事件 {event}，配置 {config}）。"

async def send_email(event: str, config: Dict, to: str, body: str) -> str:
    """发送电子邮件"""
    return f"邮件已发送至 {to}，内容：{body}（事件 {event}，配置 {config}）。"

# 主函数
async def test():
    api = OpenAIAPI(
        apikey="",  # 请替换为你的实际 API 密钥
        baseurl="https://api-inference.modelscope.cn/v1/",
        model="deepseek-ai/DeepSeek-R1",
        proxies={
            "http://": "http://127.0.0.1:7890",
            "https://": "http://127.0.0.1:7890"
        }
    )
    tools = {
        "schedule_meeting": schedule_meeting,
        "get_weather": get_weather,
        "get_time": get_time,
        "send_email": send_email
    }
    tool_fixed_params = {
        "all": {
            "event": "Team Sync",
            "config": {"location": "Room A", "priority": "high"}
        }
    }

    # 示例 1：单轮对话（非流式，无额外参数）
    print("示例 1：单轮对话（非流式，无额外参数）")
    messages = [{"role": "user", "content": [{"type": "text", "text": "法国的首都是哪里？"}]}]
    async for part in api.chat(messages, stream=False):
        if isinstance(part, dict) and "thought" in part:
            print("思考过程:", part["thought"], flush=True)
        else:
            print(part, end="", flush=True)
    print("\n更新后的消息列表：", json.dumps(messages, ensure_ascii=False, indent=2))
    print()

    # 示例 2：多轮对话（非流式，无额外参数）
    print("示例 2：多轮对话（非流式，无额外参数）")
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "法国的首都是哪里？"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "法国的首都是巴黎。"}]},
        {"role": "user", "content": [{"type": "text", "text": "巴黎的人口是多少？"}]}
    ]
    async for part in api.chat(messages, stream=False):
        if isinstance(part, dict) and "thought" in part:
            print("思考过程:", part["thought"], flush=True)
        else:
            print(part, end="", flush=True)
    print("\n更新后的消息列表：", json.dumps(messages, ensure_ascii=False, indent=2))
    print()

    # 示例 3：单轮对话（流式，无额外参数）
    print("示例 3：单轮对话（流式，无额外参数）")
    messages = [{"role": "user", "content": [{"type": "text", "text": "讲一个关于魔法背包的故事。"}]}]
    async for part in api.chat(messages, stream=True):
        if isinstance(part, dict) and "thought" in part:
            print("思考过程:", part["thought"], flush=True)
        else:
            print(part, end="", flush=True)
    print("\n更新后的消息列表：", json.dumps(messages, ensure_ascii=False, indent=2))
    print()

    # 示例 4：多轮对话（流式，带工具和 presence_penalty）
    print("示例 4：多轮对话（流式，带工具和 presence_penalty）")
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "今天纽约的天气如何？"}]}
    ]
    async for part in api.chat(messages, stream=True, tools=tools, tool_fixed_params=tool_fixed_params, presence_penalty=0.5):
        if isinstance(part, dict) and "thought" in part:
            print("思考过程:", part["thought"], flush=True)
        else:
            print(part, end="", flush=True)
    print("\n更新后的消息列表：", json.dumps(messages, ensure_ascii=False, indent=2))
    print()

    # 示例 5：多个工具调用（流式，带工具）
    print("示例 5：多个工具调用（流式，带工具）")
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "请安排一个明天上午10点的会议，持续1小时，与会者是Alice和Bob。然后告诉我巴黎和波哥大的天气，并给 Bob 发送一封邮件（bob@email.com），内容为 'Hi Bob'。"}]}
    ]
    async for part in api.chat(messages, stream=True, tools=tools, tool_fixed_params=tool_fixed_params):
        if isinstance(part, dict) and "thought" in part:
            print("思考过程:", part["thought"], flush=True)
        else:
            print(part, end="", flush=True)
    print("\n更新后的消息列表：", json.dumps(messages, ensure_ascii=False, indent=2))
    print()

    # 示例 6：推理模式（流式，启用推理）
    # reasoning_effort 可选：minimal、low、medium、high
    print("示例 6：推理模式（流式，启用推理）")
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "你好"}]}
    ]
    async for part in api.chat(messages, stream=True, max_output_tokens=500, reasoning_effort="low"):
        if isinstance(part, dict) and "thought" in part:
            print("思考过程:", part["thought"], flush=True)
        else:
            print(part, end="", flush=True)
    print("\n更新后的消息列表：", json.dumps(messages, ensure_ascii=False, indent=2))
    print()

    # 示例 7：结构化输出（非流式，使用 response_format）
    print("示例 7：结构化输出（非流式，使用 response_format）")
    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "person_info",
            "schema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "age": {"type": "integer"}
                },
                "required": ["name", "age"],
                "additionalProperties": False
            },
            "strict": True
        }
    }
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "请提供一个人的信息，包括姓名和年龄。"}]}
    ]
    async for part in api.chat(messages, stream=False, response_format=response_format):
        if isinstance(part, dict) and "thought" in part:
            continue
        print("结构化输出:", part, end="", flush=True)
    print("\n更新后的消息列表：", json.dumps(messages, ensure_ascii=False, indent=2))
    print()

    # 示例 8：聊天中使用多文件上传（PDF）
    print("示例 8：聊天中使用多文件上传（PDF）")
    file_paths = [
        'pdf1.pdf',
        'pdf2.pdf'
    ]
    display_names = ["doc1.pdf", "doc2.pdf"]

    # 上传文件
    upload_results = await api.upload_files(file_paths, display_names)
    file_parts = []
    for idx, result in enumerate(upload_results):
        if result["fileId"] and not result["error"]:
            file_parts.append({
                "input_file": {
                    "file_id": result["fileId"]
                }
            })
        else:
            print(f"文件 {file_paths[idx]} 上传失败: {result['error']}")

    if file_parts:
        # 构造包含 input_file 的聊天消息
        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": "请总结以下 PDF 文件的要点："},
                *file_parts
            ]
        }]
        print("发送 PDF 文件进行聊天：")
        async for part in api.chat(messages, stream=False):
            if isinstance(part, dict) and "thought" in part:
                continue
            print(part, end="", flush=True)
        print("\n更新后的消息列表：", json.dumps(messages, ensure_ascii=False, indent=2))
    else:
        print("无有效文件 ID，无法发起聊天")
    print()

    # 示例 9：聊天中使用多 inline 图片
    print("示例 9：聊天中使用多 inline 图片")
    file_paths = [
        '《Break the Cocoon》封面.jpg',
        '92D32EDFF4535D91F4E60234FD4703E1.jpg'
    ]

    # 转换为 inline 图片
    inline_results = await api.prepare_inline_image_batch(file_paths, detail="high")
    image_parts = []
    for idx, result in enumerate(inline_results):
        if "input_image" in result and result["input_image"]:
            image_parts.append({
                "input_image": result["input_image"]
            })
        else:
            print(f"图片 {file_paths[idx]} 处理失败: {result.get('error', '未知错误')}")

    if image_parts:
        # 构造包含 input_image 的聊天消息
        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": "请描述以下图片的内容："},
                *image_parts
            ]
        }]
        print("发送 inline 图片进行聊天：")
        async for part in api.chat(messages, stream=False):
            if isinstance(part, dict) and "thought" in part:
                continue
            print(part, end="", flush=True)
        print("\n更新后的消息列表：", json.dumps(messages, ensure_ascii=False, indent=2))
    else:
        print("无有效 inline 图片，无法发起聊天")
    print()

if __name__ == "__main__":
    asyncio.run(test())
