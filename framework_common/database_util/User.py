import json
import os
import pickle
import aiosqlite
import datetime
import asyncio
import traceback

from developTools.utils.logger import get_logger
from functools import wraps
import time
from typing import Optional
from asyncio import sleep
        
from framework_common.database_util.RedisCacheManager import create_user_cache_manager

dbpath = "data/dataBase/user_management.db"

logger = get_logger()

# 使用新的Redis缓存管理器，专门用于用户数据库(db1)
redis_cache_manager = create_user_cache_manager(cache_ttl=60)

# 全局变量存储初始化状态
_db_initialized: bool = False


async def ensure_db_initialized():
    """确保数据库已初始化"""
    global _db_initialized
    if not _db_initialized:
        await initialize_db()
        _db_initialized = True


# 初始化数据库，新增注册时间字段
async def initialize_db():
    """初始化数据库表结构"""
    try:
        db_dir = os.path.dirname(dbpath)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir)

        async with aiosqlite.connect(dbpath) as db:
            await db.execute("PRAGMA journal_mode=WAL;")
            await db.execute("PRAGMA synchronous=NORMAL;")
            await db.execute("PRAGMA cache_size=10000;")
            await db.execute("PRAGMA temp_store=MEMORY;")
            await db.execute("PRAGMA busy_timeout=5000;")

            await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                nickname TEXT,
                card TEXT,
                sex TEXT DEFAULT '0',
                age INTEGER DEFAULT 0,
                city TEXT DEFAULT '通辽',
                permission INTEGER DEFAULT 0,
                signed_days TEXT,
                registration_date TEXT,
                ai_token_record INTEGER DEFAULT 0,
                user_portrait TEXT DEFAULT '',
                portrait_update_time TEXT DEFAULT ''
                ,intimacy INTEGER DEFAULT 0
            )
            """)

            required_columns = {
                'nickname': 'TEXT',
                'card': 'TEXT',
                'sex': 'TEXT DEFAULT "0"',
                'age': 'INTEGER DEFAULT 0',
                'city': 'TEXT DEFAULT "通辽"',
                'permission': 'INTEGER DEFAULT 0',
                'signed_days': 'TEXT',
                'registration_date': 'TEXT',
                'ai_token_record': 'INTEGER DEFAULT 0',
                'user_portrait': 'TEXT DEFAULT ""',
                'portrait_update_time': 'TEXT DEFAULT ""'
                ,'intimacy': 'INTEGER DEFAULT 0'
            }

            async with db.execute("PRAGMA table_info(users);") as cursor:
                columns = await cursor.fetchall()
                existing_columns = [col[1] for col in columns]

            for column_name, column_def in required_columns.items():
                if column_name not in existing_columns:
                    await db.execute(f"ALTER TABLE users ADD COLUMN {column_name} {column_def};")
                    logger.info(f"✅ 添加了 {column_name} 列")

            await db.execute("CREATE INDEX IF NOT EXISTS idx_user_id ON users(user_id);")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_permission ON users(permission);")

            await db.commit()
            logger.info("✅ 用户数据库初始化完成")

    except Exception as e:
        logger.error(f"❌ 数据库初始化失败: {e}")
        raise


# User 类
class User:
    def __init__(self, user_id, nickname, card, sex, age, city, permission, signed_days, registration_date,
                 ai_token_record, user_portrait="", portrait_update_time="", intimacy=0):
        self.user_id = user_id
        self.nickname = nickname
        self.card = card
        self.sex = sex
        self.age = age
        self.city = city
        self.permission = permission
        self.signed_days = signed_days
        self.registration_date = registration_date
        self.ai_token_record = ai_token_record
        self.user_portrait = user_portrait
        self.portrait_update_time = portrait_update_time
        self.intimacy = intimacy or 0

    def __repr__(self):
        return (f"User(user_id={self.user_id}, nickname={self.nickname}, card={self.card}, "
                f"sex={self.sex}, age={self.age}, city={self.city}, permission={self.permission}, "
                f"signed_days={self.signed_days}, registration_date={self.registration_date}, "
                f"ai_token_record={self.ai_token_record}, user_portrait={self.user_portrait}, "
                f"portrait_update_time={self.portrait_update_time})")


async def add_user(user_id, nickname, card, sex="0", age=0, city="通辽", permission=0, ai_token_record=0):
    """添加新用户"""
    # 确保数据库已初始化
    await ensure_db_initialized()

    async with aiosqlite.connect(dbpath) as db:
        async with db.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,)) as cursor:
            if await cursor.fetchone():
                return f"✅ 用户 {user_id} 已存在，无法重复注册。"

        registration_date = datetime.date.today().isoformat()
        await db.execute("""
        INSERT INTO users (user_id, nickname, card, sex, age, city, permission, signed_days, registration_date, ai_token_record)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, nickname, card, sex, age, city, permission, "[]", registration_date, ai_token_record))
        await db.commit()

        # 使用新的缓存管理器清除缓存
        redis_cache_manager.delete(f"user:{user_id}")

        return f"✅ 用户 {user_id} 注册成功。"


async def update_user(user_id, **kwargs):
    """更新用户信息"""
    # 确保数据库已初始化
    await ensure_db_initialized()

    valid_fields = ["nickname", "card", "sex", "age", "city", "permission",
                    'ai_token_record', 'user_portrait', 'portrait_update_time']

    async with aiosqlite.connect(dbpath) as db:
        for key, value in kwargs.items():
            if key in valid_fields:
                await db.execute(f"UPDATE users SET {key} = ? WHERE user_id = ?", (value, user_id))
            else:
                logger.warning(f"❌ 未知的用户字段 {key}，请检查输入是否正确。")
        await db.commit()

    # 使用新的缓存管理器清除缓存
    redis_cache_manager.delete(f"user:{user_id}")

    logger.info(f"✅ 用户 {user_id} 的信息已更新：{kwargs}")
    return f"✅ 用户 {user_id} 的信息已更新：{kwargs}"


async def get_user(user_id, nickname="", times=1) -> User:
    """获取用户信息，如果不存在则创建默认用户"""
    if times > 5:
        logger.error(f"清理损坏数据失败, 递归次数过多")
        return None

    try:
        # 确保数据库已初始化
        await ensure_db_initialized()

        cache_key = f"user:{user_id}"

        # 使用新的缓存管理器检查缓存
        if redis_cache_manager.is_connected():
            cached_user_data = redis_cache_manager.get(cache_key)
            if cached_user_data:
                # 从JSON数据重构User对象
                return User(**cached_user_data)

        default_user = {
            "user_id": user_id,
            "nickname": f"{nickname}" if nickname else f"用户{user_id}",
            "card": "00000",
            "sex": "0",
            "age": 0,
            "city": "通辽",
            "permission": 0,
            "signed_days": "[]",
            "registration_date": datetime.date.today().isoformat(),
            'ai_token_record': 0,
            "user_portrait": "",
            "portrait_update_time": ""
            ,"intimacy": 0
        }

        async with aiosqlite.connect(dbpath) as db:
            # 查询用户（不再检查表结构）
            async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
                result = await cursor.fetchone()

                if result:
                    # 用户存在，构建用户对象
                    column_names = [description[0] for description in cursor.description]
                    existing_user = dict(zip(column_names, result))

                    user_obj = User(
                        existing_user['user_id'],
                        existing_user['nickname'],
                        existing_user['card'],
                        existing_user['sex'],
                        existing_user['age'],
                        existing_user['city'],
                        existing_user['permission'],
                        existing_user['signed_days'],
                        existing_user['registration_date'],
                        existing_user['ai_token_record'],
                        existing_user.get('user_portrait', ""),
                        existing_user.get('portrait_update_time', ""),
                        existing_user.get('intimacy', 0)
                    )
                else:
                    # 用户不存在，创建新用户
                    await db.execute("""
                    INSERT INTO users (user_id, nickname, card, sex, age, city, permission, signed_days, 
                                     registration_date, ai_token_record, user_portrait, portrait_update_time, intimacy)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (user_id, default_user["nickname"], default_user["card"], default_user["sex"],
                          default_user["age"], default_user["city"], default_user["permission"],
                          default_user["signed_days"], default_user["registration_date"],
                          default_user["ai_token_record"], default_user["user_portrait"],
                          default_user["portrait_update_time"], default_user["intimacy"]))
                    await db.commit()
                    logger.info(f"用户 {user_id} 不在数据库中，已创建默认用户。")

                    user_obj = User(
                        default_user['user_id'],
                        default_user['nickname'],
                        default_user['card'],
                        default_user['sex'],
                        default_user['age'],
                        default_user['city'],
                        default_user['permission'],
                        default_user['signed_days'],
                        default_user['registration_date'],
                        default_user['ai_token_record'],
                        default_user['user_portrait'],
                        default_user['portrait_update_time'], default_user['intimacy']
                    )

                # 使用新的缓存管理器存储到缓存（使用JSON而不是pickle）
                if redis_cache_manager.is_connected():
                    user_data = {
                        'user_id': user_obj.user_id,
                        'nickname': user_obj.nickname,
                        'card': user_obj.card,
                        'sex': user_obj.sex,
                        'age': user_obj.age,
                        'city': user_obj.city,
                        'permission': user_obj.permission,
                        'signed_days': user_obj.signed_days,
                        'registration_date': user_obj.registration_date,
                        'ai_token_record': user_obj.ai_token_record,
                        'user_portrait': user_obj.user_portrait,
                        'portrait_update_time': user_obj.portrait_update_time
                        ,'intimacy': user_obj.intimacy
                    }
                    redis_cache_manager.set(cache_key, user_data)

                return user_obj

    except Exception as e:
        logger.error(f"获取用户 {user_id} 时出错：{e}")
        logger.error(traceback.format_exc())

        # 清除缓存
        redis_cache_manager.delete(f"user:{user_id}")

        await asyncio.sleep(2)
        times += 1

        return await get_user(user_id, nickname, times)


async def get_signed_days(user_id):
    """获取用户签到记录"""
    # 确保数据库已初始化
    await ensure_db_initialized()

    async with aiosqlite.connect(dbpath) as db:
        async with db.execute("SELECT signed_days FROM users WHERE user_id = ?", (user_id,)) as cursor:
            result = await cursor.fetchone()
            if result and result[0]:
                try:
                    return json.loads(result[0])
                except json.JSONDecodeError:
                    return []
            return []


async def record_sign_in(user_id, nickname="DefaultUser", card="00000"):
    """记录用户签到"""
    # 确保数据库已初始化
    await ensure_db_initialized()

    async with aiosqlite.connect(dbpath) as db:
        async with db.execute("SELECT signed_days FROM users WHERE user_id = ?", (user_id,)) as cursor:
            result = await cursor.fetchone()

            if not result:
                # 用户不存在，创建新用户
                registration_date = datetime.date.today().isoformat()
                await db.execute("""
                INSERT INTO users (user_id, nickname, card, signed_days, registration_date)
                VALUES (?, ?, ?, ?, ?)
                """, (user_id, nickname, card, "[]", registration_date))
                await db.commit()
                logger.info(f"用户 {user_id} 不存在，已创建新用户。")
                signed_days = []
            else:
                try:
                    signed_days = json.loads(result[0]) if result[0] else []
                except json.JSONDecodeError:
                    signed_days = []

        today = datetime.date.today().isoformat()
        if today not in signed_days:
            signed_days.append(today)
            signed_days.sort()
            await db.execute("UPDATE users SET signed_days = ? WHERE user_id = ?",
                             (json.dumps(signed_days), user_id))
            await db.commit()

            # 使用新的缓存管理器清除缓存
            redis_cache_manager.delete(f"user:{user_id}")

            return f"用户 {user_id} 签到成功，日期：{today}"
        else:
            return f"用户 {user_id} 今天已经签到过了！"


async def get_users_with_permission_above(permission_value):
    """查找权限高于指定值的用户"""
    # 确保数据库已初始化
    await ensure_db_initialized()

    async with aiosqlite.connect(dbpath) as db:
        async with db.execute("SELECT user_id FROM users WHERE permission > ?", (permission_value,)) as cursor:
            result = await cursor.fetchall()
            return [user[0] for user in result]


def get_db_stats():
    """获取数据库统计信息"""
    return {
        "db_initialized": _db_initialized,
        "redis_connected": redis_cache_manager.is_connected(),
        "redis_info": redis_cache_manager.get_info(),
        "db_path": dbpath
    }


def clear_user_cache(user_id=None):
    """清除用户缓存"""
    if user_id:
        # 清除特定用户缓存
        return redis_cache_manager.delete(f"user:{user_id}")
    else:
        # 清除所有用户缓存
        return redis_cache_manager.delete_pattern("user:*")


def get_cache_stats():
    """获取缓存统计信息"""
    return redis_cache_manager.get_info()


# 添加缓存预热功能
async def warm_up_cache(user_ids: list = None):
    """预热缓存 - 将常用用户数据加载到缓存中"""
    if not redis_cache_manager.is_connected():
        logger.warning("Redis未连接，无法预热缓存")
        return

    await ensure_db_initialized()

    async with aiosqlite.connect(dbpath) as db:
        if user_ids:
            # 预热指定用户
            for user_id in user_ids:
                await get_user(user_id)
        else:
            # 预热最近活跃的用户（例如最近30天有签到记录的用户）
            thirty_days_ago = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
            async with db.execute("""
                SELECT user_id FROM users 
                WHERE signed_days LIKE ? OR registration_date >= ?
                LIMIT 100
            """, (f'%{thirty_days_ago}%', thirty_days_ago)) as cursor:
                results = await cursor.fetchall()
                for result in results:
                    await get_user(result[0])

    logger.info("缓存预热完成")


async def clear_all_user_portraits():
    """清除所有用户的用户画像"""
    await ensure_db_initialized()

    async with aiosqlite.connect(dbpath) as db:
        await db.execute("UPDATE users SET user_portrait = '', portrait_update_time = ''")
        await db.commit()

    # 清除所有用户缓存
    redis_cache_manager.delete_pattern("user:*")
    logger.info("已清除所有用户的用户画像")
