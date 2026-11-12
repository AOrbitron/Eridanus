import asyncio
import os
import json
import aiosqlite
import httpx
import re
from PIL import Image
import base64
import html

from ruamel.yaml import YAML

from framework_common.framework_util.yamlLoader import YAMLManager

same_manager = YAMLManager.get_instance()
from framework_common.framework_util.reply_config import active_llm_config
local_config = active_llm_config(same_manager)
if local_config.get("provider", local_config.get("model")) == "gemini":
    DATABASE_FILE = "data/dataBase/conversation.db"
else:
    DATABASE_FILE = "data/dataBase/openai_conversation.db"


async def use_folder_chara(file_name):
    full_path = f"data/system/chara/{file_name}"
    if file_name.endswith((".txt", ".json")):
        with open(full_path, "r", encoding="utf-8") as f:
            return f.read()
    elif file_name.endswith((".jpg", ".jpeg", ".png")):
        return silly_tavern_card(full_path, clear_html=True)


async def get_folder_chara():
    chara_list = [f for f in os.listdir('data/system/chara')]
    return "\n".join(chara_list)


def clean_invalid_characters(s, clear_html=False):
    """
    清理字符串中的无效控制字符，并根据需要移除HTML标签及其内容，以及前面可能存在的'xxx:'或'xxx：'前缀。
    """
    cleaned = ''.join(c for c in s if ord(c) >= 32 or c in ('\t', '\n', '\r'))
    if clear_html:
        cleaned = html.unescape(cleaned)
        cleaned = re.sub(r'<[^>]+>.*?</[^>]+>', '', cleaned, flags=re.DOTALL)
        cleaned = re.sub(r'<[^>]+?/>', '', cleaned)
        cleaned = re.sub(r'^.*?(?=:|：)', '', cleaned).lstrip(':： ').lstrip()
    cleaned = re.sub(r'[ \t]+', ' ', cleaned)
    cleaned = re.sub(r'\n\s+', '\n', cleaned)

    cleaned = cleaned.replace('{{user}}', '{用户}').replace('{{char}}', '{bot_name}')

    return cleaned.strip()


def silly_tavern_card(image_path, clear_html=False):
    image = Image.open(image_path)
    # 打印基本信息
    # print("图片基本信息:")
    # print(f"格式: {image.format}")
    # print(f"大小: {image.size}")
    # print(f"模式: {image.mode}")

    # 打印所有图像信息
    # print("\n所有图像信息:")
    # for key, value in image.info.items():
    # print(f"{key}: {value}")

    # 尝试打印文本块
    try:
        print("\n文本块信息:")
        for k, v in image.text.items():
            print(f"{k}: {len(v)} 字符")
            # 如果文本很长，只打印前100个字符
            print(f"预览: {v[:100]}...")
            pass
    except AttributeError:
        return "错误，没有文本块信息"

    final = []

    # 尝试解码 base64
    try:
        for key, value in image.info.items():
            if isinstance(value, str) and 'chara' in key.lower():
                print(f"\n尝试解码 {key} 的 base64:")
                decoded = base64.b64decode(value)
                res = decoded.decode('utf-8', errors='ignore')
                final.append(res)

    except Exception as e:
        return (f"错误，解码失败: {e}")

    if final:
        s = "\n".join(final)
        return clean_invalid_characters(s, clear_html=False)
    else:
        return "错误，没有人设信息"


# --- 异步数据库操作 ---

async def init_db():
    """初始化数据库"""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS conversation_history (
                user_id INTEGER PRIMARY KEY,
                history TEXT
            )
        """)
        await db.commit()


async def init_charas_db():
    """初始化角色数据库"""
    async with aiosqlite.connect('data/dataBase/charas.db') as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_chara (
                user_id INTEGER PRIMARY KEY,
                chara TEXT
            )
        """)
        await db.commit()


asyncio.run(init_charas_db())


async def change_folder_chara(file_name, user_id, folder_path='data/system/chara'):
    """根据文件名更改用户的角色，并删除用户的聊天记录"""
    try:
        # 获取文件夹中的所有文件名
        folder_contents = [f for f in os.listdir(folder_path) if os.path.isfile(os.path.join(folder_path, f))]

        for item in folder_contents:
            if file_name in item: file_name = item
        
        # 检查文件名是否在文件夹内容中
        if file_name in folder_contents:
            chara = await use_folder_chara(file_name)
            if chara.startswith("错误"):
                return chara
            await delete_user_history(user_id)
            async with aiosqlite.connect('data/dataBase/charas.db') as db:
                # 更新用户的角色信息
                await db.execute("INSERT OR REPLACE INTO user_chara (user_id, chara) VALUES (?, ?)",
                                 (user_id, chara))
                await db.commit()

            return "人设已切换为：" + file_name
        else:
            return f"文件{file_name}不存在"
    except Exception as e:
        print(f"发生了一个错误: {e}")
        return f"发生了一个错误: {e}"


async def set_all_users_chara(file_name, folder_path='data/system/chara'):
    """
    将所有用户的chara字段设置为指定的file_name对应的角色信息。
    从历史记录数据库中读取所有user_id，并写入chara数据库。
    删除所有用户的聊天记录。
    """
    try:
        if not os.path.isfile(os.path.join(folder_path, file_name)):
            return f"文件{file_name}不存在"

        chara = await use_folder_chara(file_name)
        if chara.startswith("错误"):
            return chara

        await clear_all_history()

        async with aiosqlite.connect(DATABASE_FILE) as db:
            cursor = await db.execute("SELECT user_id FROM conversation_history")
            history_users = await cursor.fetchall()

        async with aiosqlite.connect('data/dataBase/charas.db') as db:
            cursor = await db.execute("SELECT user_id FROM user_chara")
            chara_users = await cursor.fetchall()

            all_user_ids = set(user[0] for user in history_users).union(user[0] for user in chara_users)
            for user_id in all_user_ids:
                await db.execute("INSERT OR REPLACE INTO user_chara (user_id, chara) VALUES (?, ?)",
                               (user_id, chara))

            await db.commit()

        return "所有用户（包括历史记录中的用户）的人设已切换为：" + file_name
    except Exception as e:
        print(f"发生了一个错误: {e}")
        return f"发生了一个错误: {e}"


async def clear_all_users_chara():
    """
    清空chara数据库中的所有内容。
    """
    try:
        await clear_all_history()
        async with aiosqlite.connect('data/dataBase/charas.db') as db:
            await db.execute("DELETE FROM user_chara")
            await db.commit()
        return "所有用户的人设已清空"
    except Exception as e:
        print(f"发生了一个错误: {e}")
        return f"发生了一个错误: {e}"


async def clear_user_chara(user_id):
    """
    删除指定user_id的数据，包括chara字段。

    参数:
    - user_id: 要删除数据的用户的ID。
    返回:
    - 操作结果的消息字符串。
    """
    try:
        await delete_user_history(user_id)
        async with aiosqlite.connect('data/dataBase/charas.db') as db:
            await db.execute("DELETE FROM user_chara WHERE user_id = ?", (user_id,))
            await db.commit()

        return f"用户ID为 {user_id} 的人设已删除"
    except Exception as e:
        print(f"发生了一个错误: {e}")
        return f"发生了一个错误: {e}"


async def read_chara(user_id, chara_str):  # 这里的chara_str是一个字符串，表示用户默认的角色
    """读取用户的角色信息，如果不存在则直接返回默认值，不写入数据库"""
    if not isinstance(chara_str, str):
        raise ValueError("chara_str 必须是字符串类型")

    async with aiosqlite.connect('data/dataBase/charas.db') as db:
        cursor = await db.execute("SELECT chara FROM user_chara WHERE user_id = ?", (user_id,))
        result = await cursor.fetchone()
        if result is None:
            return chara_str
        else:
            return result[0]


async def get_user_history(user_id)->list:
    """获取用户历史对话"""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        async with db.execute("SELECT history FROM conversation_history WHERE user_id = ?", (user_id,)) as cursor:
            result = await cursor.fetchone()
            if result:
                return json.loads(result[0])
            else:
                return []

async def delete_latest2_history(user_id):
    user_history=await get_user_history(user_id)
    user_history=user_history[:-2]
    await update_user_history(user_id, user_history)

async def update_user_history(user_id, history):
    """更新用户历史对话，自动过滤掉思维链(thought)内容"""
    # 过滤掉 thought 内容
    filtered_history = []
    for msg in history:
        if isinstance(msg, dict) and "parts" in msg:
            # 过滤掉 thought: true 的部分
            filtered_parts = [
                part for part in msg["parts"]
                if not (isinstance(part, dict) and part.get("thought") is True)
            ]
            if filtered_parts:  # 只有在有内容时才添加
                filtered_history.append({
                    "role": msg.get("role", "user"),
                    "parts": filtered_parts
                })
        else:
            filtered_history.append(msg)
    
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute("INSERT OR REPLACE INTO conversation_history (user_id, history) VALUES (?, ?)",
                         (user_id, json.dumps(filtered_history)))
        await db.commit()


async def delete_user_history(user_id):
    """删除指定用户的聊天记录"""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute("DELETE FROM conversation_history WHERE user_id = ?", (user_id,))
        await db.commit()


async def clear_all_history():
    """清理所有用户的聊天记录"""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute("DELETE FROM conversation_history")
        await db.commit()
        print("所有用户的对话记录已清理。")


asyncio.run(init_db())
