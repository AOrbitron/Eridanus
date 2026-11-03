import httpx
import asyncio
import itertools
from typing import List, Dict, Tuple, Optional
import logging

from developTools.utils.logger import get_logger
from framework_common.framework_util.yamlLoader import YAMLManager
from framework_common.framework_util.reply_config import active_llm_config

logger=get_logger("GeminiKeyManager")
base_url = active_llm_config(YAMLManager.get_instance())["gemini"]["base_url"]
GEMINI_API_MODELS_URL = f"{base_url}/v1beta/models"
proxy=YAMLManager.get_instance().common_config.basic_config["proxy"]["http_proxy"]

class NoAvailableAPIKeyError(Exception):
    pass

async def _check_single_gemini_key_status(
        client: httpx.AsyncClient,
        api_key: str,
        timeout: float = 20.0
) -> Tuple[str, bool, str]:
    """异步检测单个 Gemini API Key 的可用性。"""
    try:
        params = {"key": api_key}
        response = await client.get(GEMINI_API_MODELS_URL, params=params, timeout=timeout)

        if response.status_code == 200:
            response_json = response.json()
            if "models" in response_json and isinstance(response_json["models"], list):
                return api_key, True, "API Key 有效，成功获取模型列表。"
            else:
                return api_key, True, f"响应200但内容异常: {response.text[:100]}..."
        elif response.status_code in [401, 403]:
            logger.error(f"API Key: {api_key} 无效。原因: {response.text}")
            return api_key, False, f"HTTP {response.status_code}: {response.text}"
        else:
            logger.info(f"API Key: {api_key} 状态码: {response.status_code}。无法访问但暂时保留")
            return api_key, True, f"HTTP {response.status_code}: {response.text[:100]}..."

    except httpx.RequestError as exc:
        logger.error(f"API Key: {api_key} 请求错误: {exc} 但暂时保留")
        return api_key, True, f"网络或请求错误: {exc}"
    except Exception as exc:
        logger.error(f"API Key: {api_key} 未知错误: {exc} 但暂时保留")
        return api_key, True, f"未知错误: {exc} 但暂时保留"


import threading


class GeminiKeyManager:
    _instance: Optional['GeminiKeyManager'] = None
    _initialized: bool = False
    _init_lock: asyncio.Lock = None  # 用于保护单例初始化的锁
    _class_lock: threading.Lock = threading.Lock()  # 用于保护锁初始化的线程锁

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(GeminiKeyManager, cls).__new__(cls)
        return cls._instance

    def __init__(self, initial_api_keys: List[str], check_interval_seconds: int = 3000,
                 timeout_per_key: float = 10.0, max_concurrent_checks: int = 20):
        if self._initialized:
            return

        self._all_api_keys = list(set(initial_api_keys))  # 使用set去重并转换为list
        self._available_keys: List[str] = []
        self._unavailable_keys: Dict[str, str] = {}  # key -> reason
        self._key_iterator = itertools.cycle([])  # 用于轮询的迭代器
        self._next_key_lock = asyncio.Lock()  # 保护轮询索引和可用key列表

        self._check_interval_seconds = check_interval_seconds
        self._timeout_per_key = timeout_per_key
        self._max_concurrent_checks = max_concurrent_checks
        if proxy and proxy!="":
            proxies={"http://": proxy, "https://": proxy}
        else:
            proxies=None
        logger.info(f"初始化 GeminiKeyManager，代理：{proxies} base_url: {base_url}")
        self._client: httpx.AsyncClient = httpx.AsyncClient(proxies=proxies)
        self._checker_task: Optional[asyncio.Task] = None

        self._initialized = True
        logger.info("GeminiKeyManager 初始化完成，将启动后台Key检测。")
        # 立即启动后台任务，并执行一次初始检测
        self._checker_task = asyncio.create_task(self._run_periodic_check())

    async def _perform_full_check(self):
        """执行一次所有API Key的全面检测。"""
        if not self._all_api_keys:
            logger.warning("没有可供检测的API Key。")
            async with self._next_key_lock:
                self._available_keys = []
                self._unavailable_keys = {}
                self._key_iterator = itertools.cycle([])
            return

        logger.info(f"开始检测 {len(self._all_api_keys)} 个API Key...")

        # 使用Semaphore限制并发
        semaphore = asyncio.Semaphore(self._max_concurrent_checks)

        async def check_key_with_semaphore(key: str):
            async with semaphore:
                return await _check_single_gemini_key_status(self._client, key, self._timeout_per_key)

        tasks = [check_key_with_semaphore(key) for key in self._all_api_keys]
        results = await asyncio.gather(*tasks, return_exceptions=True)  # 捕获内部异常

        new_available = []
        new_unavailable: Dict[str, str] = {}

        for res in results:
            if isinstance(res, Exception):
                # 任务自身出错，不是HTTP请求出错
                logger.error(f"Key检测任务内部错误: {res}")
                continue

            key, is_available, message = res
            if is_available:
                new_available.append(key)
            else:
                new_unavailable[key] = message
                #logger.warning(f"Key: {key} 不可用。原因: {message}")

        async with self._next_key_lock:
            self._available_keys = new_available
            self._unavailable_keys = new_unavailable

            if self._available_keys:
                self._key_iterator = itertools.cycle(self._available_keys)
                logger.info(
                    f"检测完成。当前可用Key数量: {len(self._available_keys)}，不可用Key数量: {len(self._unavailable_keys)}")
                #logger.info(f"{list(key_manager._unavailable_keys.keys())}")
            else:
                self._key_iterator = itertools.cycle([])
                logger.warning("所有API Key均不可用或未配置。")

    async def _run_periodic_check(self):
        """后台协程，定期执行API Key检测。"""
        await self._perform_full_check()
        while True:
            try:
                await asyncio.sleep(self._check_interval_seconds)
                await self._perform_full_check()
            except asyncio.CancelledError:
                logger.info("Key检测后台任务已取消。")
                break
            except Exception as e:
                logger.error(f"Key检测后台任务发生错误: {e}")
                # 可以在这里添加重试逻辑或更高级的错误处理

    async def get_apikey(self) -> str:
        """
        获取一个可用的 Gemini API Key (轮询)。
        如果所有 Key 都不可用，则抛出 NoAvailableAPIKeyError。
        """
        async with self._next_key_lock:
            if not self._available_keys:
                logger.error("当前没有可用的 Gemini API Key。")
                raise NoAvailableAPIKeyError("没有可用的 Gemini API Key。")
            try:
                key = next(self._key_iterator)
                logger.debug(f"分配 Key: {key}")
                return key
            except StopIteration:
                # 理论上 itertools.cycle 不会 StopIteration，除非初始列表为空
                # 但为了健壮性，这里处理一下
                logger.error("Key迭代器为空或异常，尝试重新初始化。")
                self._key_iterator = itertools.cycle(self._available_keys)
                if not self._available_keys:
                    raise NoAvailableAPIKeyError("Key迭代器异常且没有可用Key。")
                key = next(self._key_iterator)  # 再次尝试获取
                logger.debug(f"重新初始化迭代器后分配 Key: {key}")
                return key

    @classmethod
    async def get_gemini_apikey(cls) -> str:
        """
        类方法：获取一个可用的Gemini API Key
        如果实例不存在，会自动创建并初始化

        Returns:
            str: 可用的API Key

        Raises:
            NoAvailableAPIKeyError: 如果没有可用的API Key
        """
        # 使用线程锁保护异步锁的初始化，防止竞态条件
        with cls._class_lock:
            if cls._init_lock is None:
                cls._init_lock = asyncio.Lock()
        
        async with cls._init_lock:
            if cls._instance is None:
                try:
                    config = YAMLManager.get_instance()
                    initial_keys_from_config = active_llm_config(config)["gemini"]["api_keys"]
                    cls._instance = cls(initial_keys_from_config)
                    # 等待初始检测完成
                    await asyncio.sleep(3)
                    logger.info("自动初始化GeminiKeyManager完成")
                except Exception as e:
                    logger.error(f"自动初始化失败: {e}")
                    raise RuntimeError("无法自动初始化GeminiKeyManager") from e

        return await cls._instance.get_apikey()

    async def shutdown(self):
        """优雅地关闭Key管理器，停止后台任务并关闭HTTP客户端。"""
        if self._checker_task:
            self._checker_task.cancel()
            try:
                await self._checker_task
            except asyncio.CancelledError:
                pass  # 正常取消
        if self._client:
            await self._client.aclose()
        logger.info("GeminiKeyManager 已关闭。")

if __name__ == "__main__":

    config = YAMLManager("run")
    initial_keys_from_config = active_llm_config(config)["gemini"]["api_keys"]



    async def main():
        key_manager = GeminiKeyManager(initial_api_keys=initial_keys_from_config,
                                       check_interval_seconds=60)  # 每60秒检测一次

        await asyncio.sleep(5)  # 等待初始化完成
        key = await key_manager.get_apikey()


        print("\n--- 检查当前 Key 状态 ---")
        print(f"可用 Key ({len(key_manager._available_keys)}个): {key_manager._available_keys}")
        print(f"不可用 Key ({len(key_manager._unavailable_keys)}个): {list(key_manager._unavailable_keys.keys())}")


        await key_manager.shutdown()

    asyncio.run(main())
