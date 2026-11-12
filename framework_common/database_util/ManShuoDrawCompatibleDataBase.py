import traceback

import aiosqlite
import json
import asyncio
from typing import Dict, Any, Optional, List
import os
from datetime import datetime
from pathlib import Path
from collections import defaultdict
import pprint
from developTools.utils.logger import get_logger

logger = get_logger(__name__.split('.')[-1])

#获取当前时间戳
async def date_get():
    current_date = datetime.now()
    timestamp = int(current_date.timestamp())
    current_year = current_date.year
    current_month = current_date.month
    current_day = current_date.day
    day = f'{current_year}_{current_month}_{current_day}'
    month = f'{current_year}_{current_month}'
    year = f'{current_year}'
    return_json = {'day':day, 'month':month, 'year':year,'today':current_date,'time':timestamp}
    return return_json

#初始化数据库中的缓存操作
async def cache_init():
    db = await AsyncSQLiteDatabase.get_instance()
    await db.delete_user('manshuo_cache')
    await db.write_user('manshuo_cache', {})

#获取数据库中的缓存
async def cache_get(db, user_id = None):
    if user_id is None:
        return await db.read_user('manshuo_cache')
    else:
        data_info = await db.read_user('manshuo_cache')
        return data_info.get(user_id,{})

#保存缓存数据
async def cache_save(db, user_id = None, data_info = None):
    await db.write_user('manshuo_cache', {user_id:data_info})

#初始化数据库中的缓存操作
async def cache_delete(db, user_id = None, key = None):
    await db.delete_user_field('manshuo_cache',f'{user_id}.{key}')

# 递归合并字典中的同名字段
def merge_dicts(dict1, dict2):
    merged = dict1.copy()  # 复制 dict1 的数据
    for key, value in dict2.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            # 如果键存在且对应的值是嵌套字典，则递归合并
            merged[key] = merge_dicts(merged[key], value)
        else:
            # 否则直接覆盖
            merged[key] = value
    return merged


class AsyncSQLiteDatabase:
    _instance = None
    _lock = asyncio.Lock()
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(AsyncSQLiteDatabase, cls).__new__(cls)
        return cls._instance

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def initialize(self, db_path: str = "manshuo.db", storage_dir: str = "data/database"):
        """
        初始化 SQLite 数据库连接，并创建必要的表结构。
        :param db_path: SQLite 数据库文件路径
        :param storage_dir: 数据库存储目录
        """
        logger.info(f"Initializing SQLite database at {db_path}")
        async with self._lock:
            if self._initialized:
                return

            if storage_dir:
                # 确保目录存在
                Path(storage_dir).mkdir(parents=True, exist_ok=True)
                self.db_path = os.path.join(storage_dir, db_path)
            else:
                self.db_path = db_path

            # 创建连接池的概念 - 使用信号量控制并发连接数
            self._semaphore = asyncio.Semaphore(50)  # 最大50个并发连接

            # 初始化数据库表结构
            await self._init_database()
            self._initialized = True

    async def _get_connection(self):
        """获取数据库连接的上下文管理器"""
        await self._semaphore.acquire()
        try:
            conn = await aiosqlite.connect(self.db_path)
            conn.row_factory = aiosqlite.Row
            return conn
        except Exception as e:
            self._semaphore.release()
            raise e

    async def _release_connection(self, conn):
        """释放数据库连接"""
        if conn:
            await conn.close()
        self._semaphore.release()

    async def _init_database(self):
        """初始化数据库表结构"""
        conn = await self._get_connection()
        try:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    user_data TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 创建索引提高查询性能
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_users_updated_at ON users(updated_at)
            ''')

            await conn.commit()
        finally:
            await self._release_connection(conn)

    async def write_user(self, user_id: str, user_data: Dict[str, Any], is_merged=True):
        """
        将用户数据以嵌套字典的形式存储到 SQLite 中（通过 JSON 序列化）。
        """
        logger.info(f"Writing user {user_id} to {self.db_path}")

        # 合并新数据与旧数据（旧数据保留，新数据覆盖同名字段）
        if is_merged:
            existing_data = await self.read_user(user_id)
            merged_data = merge_dicts(existing_data, user_data)
        else: merged_data = user_data

        # 序列化为 JSON 字符串
        json_data = json.dumps(merged_data, ensure_ascii=False)

        conn = await self._get_connection()
        try:
            await conn.execute('''
                INSERT OR REPLACE INTO users (user_id, user_data, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            ''', (user_id, json_data))
            await conn.commit()
        finally:
            await self._release_connection(conn)

    async def read_user(self, user_id: str) -> Dict[str, Any]:
        """
        读取用户数据，并将 JSON 字符串反序列化为嵌套字典。
        """
        logger.info(f"Reading user {user_id} from {self.db_path}")
        #traceback.print_stack()
        conn = await self._get_connection()
        try:
            cursor = await conn.execute(
                'SELECT user_data FROM users WHERE user_id = ?',
                (user_id,)
            )
            row = await cursor.fetchone()

            if row:
                return json.loads(row['user_data'])
            return {}
        finally:
            await self._release_connection(conn)

    async def batch_read_users(self, user_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        批量读取多个用户数据，减少数据库查询次数
        :param user_ids: 用户ID列表
        :return: 用户ID到用户数据的映射字典
        """
        if not user_ids:
            return {}

        logger.info(f"Batch reading {len(user_ids)} users from {self.db_path}")

        conn = await self._get_connection()
        try:
            # 构造 IN 查询
            placeholders = ','.join(['?' for _ in user_ids])
            query = f'SELECT user_id, user_data FROM users WHERE user_id IN ({placeholders})'

            cursor = await conn.execute(query, user_ids)

            result = {}
            async for row in cursor:
                user_id = row['user_id']
                user_data = json.loads(row['user_data'])
                result[str(user_id)] = user_data

            # 为不存在的用户返回空字典
            for user_id in user_ids:
                if user_id not in result:
                    result[str(user_id)] = {}

            return result
        finally:
            await self._release_connection(conn)

    async def batch_update_speech_counts(self, speech_cache: Dict[int, Dict[int, Dict[str, int]]]):
        """
        批量更新用户的发言统计数据，专门针对发言统计的高效更新方法
        :param speech_cache: 格式 {user_id: {group_id: {day: count}}}
        """
        if not speech_cache:
            return

        logger.info(f"Batch updating speech counts for {len(speech_cache)} users")

        # 获取所有需要更新的用户ID
        user_ids = [str(user_id) for user_id in speech_cache.keys()]

        # 批量读取现有用户数据
        existing_users = await self.batch_read_users(user_ids)

        # 准备批量更新的数据
        updates = []

        for user_id, groups in speech_cache.items():
            user_id_str = str(user_id)
            current_data = existing_users.get(user_id_str, {})

            # 确保 number_speeches 字段存在
            if 'number_speeches' not in current_data:
                current_data['number_speeches'] = {}

            # 更新每个群组的发言统计
            for group_id, days in groups.items():
                group_id_str = str(group_id)

                if group_id_str not in current_data['number_speeches']:
                    current_data['number_speeches'][group_id_str] = {}

                # 更新每天的发言数量
                for day, count in days.items():
                    if day in current_data['number_speeches'][group_id_str]:
                        # 累加现有计数
                        current_data['number_speeches'][group_id_str][day] += count
                    else:
                        # 设置新的计数
                        current_data['number_speeches'][group_id_str][day] = count

            # 准备批量更新的数据
            json_data = json.dumps(current_data, ensure_ascii=False)
            updates.append((json_data, user_id_str))

        # 执行批量更新
        conn = await self._get_connection()
        try:
            await conn.execute('BEGIN TRANSACTION')

            await conn.executemany('''
                INSERT OR REPLACE INTO users (user_id, user_data, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            ''', [(user_id, json_data) for json_data, user_id in updates])

            await conn.commit()
            logger.info(f"Successfully batch updated {len(updates)} users")

        except Exception as e:
            await conn.rollback()
            logger.error(f"Batch update failed: {e}")
            raise e
        finally:
            await self._release_connection(conn)

    async def batch_increment_counters(self, counter_updates: Dict[str, Dict[str, int]]):
        """
        批量增量更新计数器，适用于需要在现有数值基础上增加的场景
        :param counter_updates: 格式 {user_id: {field_path: increment_value}}
        """
        if not counter_updates:
            return

        logger.info(f"Batch incrementing counters for {len(counter_updates)} users")

        user_ids = list(counter_updates.keys())
        existing_users = await self.batch_read_users(user_ids)

        updates = []

        for user_id, field_updates in counter_updates.items():
            current_data = existing_users.get(user_id, {})

            for field_path, increment in field_updates.items():
                # 解析嵌套字段路径
                keys = field_path.split('.')
                target = current_data

                # 确保路径上的所有字典都存在
                for key in keys[:-1]:
                    if key not in target or not isinstance(target[key], dict):
                        target[key] = {}
                    target = target[key]

                # 增量更新最终值
                final_key = keys[-1]
                current_value = target.get(final_key, 0)
                target[final_key] = current_value + increment

            json_data = json.dumps(current_data, ensure_ascii=False)
            updates.append((json_data, user_id))

        # 执行批量更新
        conn = await self._get_connection()
        try:
            await conn.execute('BEGIN TRANSACTION')

            await conn.executemany('''
                INSERT OR REPLACE INTO users (user_id, user_data, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            ''', [(json_data, user_id) for json_data, user_id in updates])

            await conn.commit()

        except Exception as e:
            await conn.rollback()
            raise e
        finally:
            await self._release_connection(conn)

    async def update_user_field(self, user_id: str, field_path: str, value: Any) -> bool:
        """
        更新嵌套字典中的某个字段。
        :param user_id: 用户 ID
        :param field_path: 嵌套字段的路径，例如 "address.city"
        :param value: 要更新的值
        """
        logger.info(f"Updating user {user_id} field {field_path} to {value}")
        user_data = await self.read_user(user_id)
        if not user_data:
            return False

        # 解析字段路径并更新对应的嵌套值
        keys = field_path.split(".")
        target = user_data
        for key in keys[:-1]:
            target = target.setdefault(key, {})
        target[keys[-1]] = value

        # 写回数据库
        await self.write_user(user_id, user_data)
        return True

    async def delete_user_field(self, user_id: str, field_path: str) -> bool:
        """
        删除嵌套字典中的某个字段。
        """
        logger.info(f"Deleting user {user_id} field {field_path}")
        user_data = await self.read_user(user_id)
        if not user_data:
            return False

        # 解析字段路径并删除对应的嵌套值
        keys = field_path.split(".")
        target = user_data
        for key in keys[:-1]:
            target = target.get(key, {})
            if not isinstance(target, dict):
                return False

        if keys[-1] in target:
            target.pop(keys[-1], None)
            # 写回数据库
            await self.write_user(user_id, user_data, is_merged=False)
            return True
        return False

    async def delete_user(self, user_id: str) -> bool:
        """
        删除整个用户数据。
        """
        logger.info(f"Deleting user {user_id} from {self.db_path}")
        conn = await self._get_connection()
        try:
            cursor = await conn.execute(
                'DELETE FROM users WHERE user_id = ?',
                (user_id,)
            )
            await conn.commit()
            return cursor.rowcount > 0
        finally:
            await self._release_connection(conn)

    async def write_multiple_users(self, users: Dict[str, Dict[str, Any]], is_merged=True):
        """
        一次写入多个用户的数据（嵌套字典形式）。
        """
        logger.info(f"Writing multiple users to {self.db_path}")
        conn = await self._get_connection()
        try:
            # 使用事务提高性能
            await conn.execute('BEGIN TRANSACTION')
            user_list = [user_id for user_id, user_data in users.items()]
            user_info_list = await self.batch_read_users(user_list)
            for user_id, user_data in users.items():
                existing_data = user_info_list[user_id]
                if is_merged: merged_data = merge_dicts(existing_data, user_data)
                else: merged_data = user_data
                json_data = json.dumps(merged_data, ensure_ascii=False)
                await conn.execute('''
                    INSERT OR REPLACE INTO users (user_id, user_data, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                ''', (user_id, json_data))

            await conn.commit()
        except Exception as e:
            await conn.rollback()
            raise e
        finally:
            await self._release_connection(conn)

    async def read_all_users(self, user_prefix: str = None) -> Dict[str, Dict[str, Any]]:
        """
        读取所有用户数据，返回一个嵌套字典，key 为用户 ID，value 是嵌套字典数据。
        :param user_prefix: 用户ID前缀过滤器，如果提供则只返回匹配前缀的用户
        """
        logger.info(f"Reading all users from {self.db_path}")
        conn = await self._get_connection()
        try:
            if user_prefix:
                cursor = await conn.execute(
                    'SELECT user_id, user_data FROM users WHERE user_id LIKE ?',
                    (f'{user_prefix}%',)
                )
            else:
                cursor = await conn.execute('SELECT user_id, user_data FROM users')

            users_data = {}
            async for row in cursor:
                user_id = row['user_id']
                user_data = json.loads(row['user_data'])
                users_data[user_id] = user_data

            return users_data
        finally:
            await self._release_connection(conn)

    async def save_to_disk(self):
        """
        手动执行数据库同步（SQLite 自动持久化，此方法执行 WAL checkpoint）。
        """
        conn = await self._get_connection()
        try:
            await conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            await conn.commit()
            print("Database checkpoint completed successfully.")
        except Exception as e:
            print(f"Error during database checkpoint: {e}")
        finally:
            await self._release_connection(conn)

    async def load_from_disk(self):
        """
        SQLite 数据会自动从文件加载，此方法仅用于兼容性。
        """
        print("SQLite 数据会在连接时自动加载。数据库文件路径:", self.db_path)

    async def get_user_count(self) -> int:
        """获取用户总数"""
        logger.info(f"Getting user count from {self.db_path}")
        conn = await self._get_connection()
        try:
            cursor = await conn.execute('SELECT COUNT(*) as count FROM users')
            row = await cursor.fetchone()
            return row['count']
        finally:
            await self._release_connection(conn)

    async def get_users_by_pattern(self, pattern: str) -> Dict[str, Dict[str, Any]]:
        """
        通过模式匹配获取用户数据
        :param pattern: SQL LIKE 模式，例如 '%test%'
        """
        conn = await self._get_connection()
        try:
            cursor = await conn.execute(
                'SELECT user_id, user_data FROM users WHERE user_id LIKE ?',
                (pattern,)
            )

            users_data = {}
            async for row in cursor:
                user_id = row['user_id']
                user_data = json.loads(row['user_data'])
                users_data[user_id] = user_data

            return users_data
        finally:
            await self._release_connection(conn)

    async def close(self):
        """关闭数据库连接（清理资源）"""
        # SQLite 连接在每次使用后都会自动关闭
        # 这里主要用于清理单例状态
        pass

    @classmethod
    async def get_instance(cls, db_path: str = "ManshuoCompatibledData.db",
                           storage_dir: str = "data/database") -> "AsyncSQLiteDatabase":
        """
        获取数据库实例的异步方法
        """
        logger.info(f"Getting database instance for {db_path}")
        #traceback.print_stack()
        instance = cls()
        if not instance._initialized:
            await instance.initialize(db_path, storage_dir)
        return instance


# 优化后的批量更新示例
async def optimized_batch_update_speeches(speech_cache, db):
    """
    优化后的批量更新发言统计函数
    """
    try:
        logger.info("Start optimized batch update speeches")

        if not speech_cache:
            return

        # 使用新的批量更新方法，一次性处理所有数据
        await db.batch_update_speech_counts(speech_cache)

        # 清空缓存
        speech_cache.clear()

        logger.info("Optimized batch update completed successfully")

    except Exception as e:
        logger.error(f"Optimized batch update error: {e}")
        raise e