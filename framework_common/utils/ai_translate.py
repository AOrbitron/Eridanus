import random
import traceback

from developTools.utils.logger import get_logger
from framework_common.framework_util.yamlLoader import YAMLManager
from framework_common.framework_util.reply_config import core_reply_enabled, auxiliary_reply


class Translator:
    def __init__(self):
        self.config = YAMLManager.get_instance()
        self.system_instruction="请翻译以下内容为日文，直接给出结果，不要有多余废话，也不要回应，直接输出结果。需要翻译的文本为："
        self.logger=get_logger()
    async def translate(self, text):
        return await self.aiReplyCore(text, self.config, self.system_instruction)
    async def aiReplyCore(self,text,config,system_instruction=None,recursion_times=0):  # 后面几个函数都是供函数调用的场景使用的
        if core_reply_enabled(config):
            try:
                return await auxiliary_reply((system_instruction or "") + text, config) or text
            except Exception as exc:
                self.logger.warning(f"Translation failed: {exc}")
                return text

        from run.ai_llm.service.aiReplyHandler.default import defaultModelRequest
        from run.ai_llm.service.aiReplyHandler.tecentYuanQi import YuanQiTencent
        from run.ai_llm.clients.gemini_client import GeminiAPI
        from run.ai_llm.clients.openai_client import OpenAIAPI
        from framework_common.utils.GeminiKeyManager import GeminiKeyManager

        logger = self.logger
        logger.info(f"translator called with message: {text}")
        """
        递归深度约束
        """
        
        if recursion_times > config.ai_llm.config["llm"]["retries"]:
            logger.warning(f"roll back to original history, recursion times: {recursion_times}")
            return text

        try:
            if config.ai_llm.config["llm"]["model"] == "default":
                prompt=[
                    {"role": "user", "content": system_instruction+text},
                ]
                response_message = await defaultModelRequest(
                    prompt,
                    config.common_config.basic_config["proxy"]["http_proxy"] if config.ai_llm.config["llm"][
                        "enable_proxy"] else None,
                )
                reply_message = response_message['content']


            elif config.ai_llm.config["llm"]["model"] in ["openai",'eridanus',"double"]:
                prompt = [{"role": "user", "content": system_instruction + text}]

                proxy = config.common_config.basic_config["proxy"]["http_proxy"] if config.ai_llm.config["llm"]["enable_proxy"] else None
                proxies = {"http://": proxy, "https://": proxy} if proxy else None

                api = OpenAIAPI(
                    apikey=random.choice(config.ai_llm.config["llm"]["openai"]["api_keys"]),
                    baseurl=(config.ai_llm.config["llm"]["openai"].get("quest_url")
                             or config.ai_llm.config["llm"]["openai"].get("base_url")),
                    model=config.ai_llm.config["llm"]["openai"]["model"],
                    proxies=proxies
                )

                response_text = ""
                async for part in api.chat(
                    prompt,
                    stream=False,
                    max_output_tokens=config.ai_llm.config["llm"]["openai"]["max_tokens"],
                    temperature=config.ai_llm.config["llm"]["openai"]["temperature"],
                ):
                    if isinstance(part, str):
                        response_text += part
                reply_message = response_text.strip() if response_text else None
            elif config.ai_llm.config["llm"]["model"] == "gemini":
                prompt = [
                    {
                        "parts": [{"text": system_instruction + text}],
                        "role": "user"
                    },
                ]

                proxy = config.common_config.basic_config["proxy"]["http_proxy"] if config.ai_llm.config["llm"]["enable_proxy"] else None
                proxies = {"http://": proxy, "https://": proxy} if proxy else None

                # 使用 GeminiKeyManager 获取 API key，与主回复逻辑保持一致
                api = GeminiAPI(
                    apikey=await GeminiKeyManager.get_gemini_apikey(),
                    baseurl=config.ai_llm.config["llm"]["gemini"]["base_url"],
                    model=config.ai_llm.config["llm"]["gemini"]["model"],
                    proxies=proxies
                )

                response_text = ""
                async for part in api.chat(
                    prompt,
                    stream=False,
                    system_instruction="请你扮演翻译官，我给你要翻译的文本，你直接给我结果，不需要回应。",
                    temperature=config.ai_llm.config["llm"]["gemini"]["temperature"],
                    max_output_tokens=config.ai_llm.config["llm"]["gemini"]["maxOutputTokens"],
                ):
                    if isinstance(part, str):
                        response_text += part
                reply_message = response_text.strip() if response_text else None

            elif config.ai_llm.config["llm"]["model"] == "腾讯元器":
                prompt=[{"role": "user", "content": [{"type": "text", "text": system_instruction+text}]}]
                response_message = await YuanQiTencent(
                    prompt,
                    config.ai_llm.config["llm"]["腾讯元器"]["智能体ID"],
                    config.ai_llm.config["llm"]["腾讯元器"]["token"],
                    random.randint(1, 100),
                )
                reply_message = response_message["content"]
                response_message["content"] = [{"type": "text", "text": response_message["content"]}]
            logger.info(f"aiReplyCore returned: {reply_message}")
            if reply_message is not None:
                return reply_message.strip()
            else:
                return reply_message
        except Exception as e:
            logger.error(f"Error occurred: {e}")
            traceback.print_exc()
            logger.warning(f"roll back to original history, recursion times: {recursion_times}")
            if recursion_times <= config.ai_llm.config["llm"]["retries"]:
                logger.warning(f"Recursion times: {recursion_times}")
                return await self.aiReplyCore(text, config, system_instruction, recursion_times + 1)
            else:
                return text
