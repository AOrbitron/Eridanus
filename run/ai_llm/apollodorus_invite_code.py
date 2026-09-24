import json
import logging
from pathlib import Path
from typing import Dict, Optional
import httpx

# 引入框架相关组件
from developTools.event.events import GroupMessageEvent
from framework_common.framework_util.websocket_fix import ExtendBot
from framework_common.framework_util.yamlLoader import YAMLManager
from developTools.message.message_components import Text

# ==========================================
# 核心配置区域
# ==========================================
API_SERVER_URL = "http://api.apollodorus.xyz"  # 你的 API Server 地址
ADMIN_USERNAME = "laisizhe"  # 管理员账号
ADMIN_PASSWORD = "fkeveryone"  # 管理员密码

# 特权白名单用户ID（可无限重复生成全新邀请码）
UNLIMITED_USER_ID = 1840094972

# 本地数据存储路径
DATA_DIR = Path("data/invite")
DATA_DIR.mkdir(parents=True, exist_ok=True)
RECORD_FILE = DATA_DIR / "invite_claimed_users.json"

logger = logging.getLogger("InvitePlugin")


# ==========================================
# 数据持久化辅助函数 (使用 Dict 存储映射关系)
# ==========================================
def _load_claimed_map() -> Dict[str, str]:
    """
    加载已领取的映射字典: { "user_id_str": "invite_code" }
    """
    if not RECORD_FILE.exists():
        return {}
    try:
        with open(RECORD_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # 兼容旧版本是 list 的情况，如果是 list 则返回空 dict 重新记录
            return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.error(f"读取已领取用户记录失败: {e}")
        return {}


def _save_claimed_code(user_id: int, invite_code: str):
    """保存普通用户的 user_id -> invite_code 映射"""
    data = _load_claimed_map()
    data[str(user_id)] = invite_code
    try:
        with open(RECORD_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"保存领取记录失败: {e}")


# ==========================================
# 异步生成邀请码函数 (httpx)
# ==========================================
async def generate_invite_code(
        base_url: str,
        admin_username: str,
        admin_password: str,
        count: int = 1,
        timeout: float = 10.0,
) -> str:
    """
    异步管理员登录并生成1个邀请码
    :return: 邀请码字符串
    """
    base_url = base_url.rstrip("/")
    login_url = f"{base_url}/api/auth/login"
    generate_url = f"{base_url}/api/admin/invite/generate"

    async with httpx.AsyncClient(timeout=timeout) as client:
        # 1. 登录
        login_resp = await client.post(
            login_url,
            json={"username": admin_username, "password": admin_password},
        )
        if login_resp.status_code != 200:
            err = login_resp.text
            try:
                err = login_resp.json().get("detail", err)
            except Exception:
                pass
            raise RuntimeError(f"管理员登录失败: {err}")

        token = login_resp.json().get("access_token")
        if not token:
            raise RuntimeError("未获取到有效的管理员 Token")

        # 2. 生成邀请码
        gen_resp = await client.post(
            generate_url,
            headers={"Authorization": f"Bearer {token}"},
            params={"count": count},
        )
        if gen_resp.status_code != 200:
            err = gen_resp.text
            try:
                err = gen_resp.json().get("detail", err)
            except Exception:
                pass
            raise RuntimeError(f"邀请码生成接口返回错误: {err}")

        codes = gen_resp.json().get("codes", [])
        if not codes:
            raise RuntimeError("接口未返回任何邀请码")

        return codes[0]


# ==========================================
# 插件入口
# ==========================================
def main(bot: ExtendBot, config: YAMLManager):
    @bot.on(GroupMessageEvent)
    async def handle_group_invite(event: GroupMessageEvent):
        # 提取纯文本指令（去除首尾空白）
        text = str(event.pure_text).strip()

        if text != "/invite" or event.group_id != 1050663831:
            return

        user_id = int(event.user_id)
        user_id_str = str(user_id)
        is_unlimited = (user_id == UNLIMITED_USER_ID)

        claimed_map = _load_claimed_map()

        # -----------------------------------------------------------
        # 情况一：普通用户已经生成过，重新发送之前保存的邀请码
        # -----------------------------------------------------------
        if not is_unlimited and user_id_str in claimed_map:
            old_code = claimed_map[user_id_str]
            resend_msg = (
                f"ℹ️ 您此前已获取过邀请码，现为您重新补发：\n"
                f"🔑 邀请码: {old_code}\n\n"
                f"请前往网站 {API_SERVER_URL} 注册。"
            )
            # 尝试私聊发送
            try:
                await bot.send_friend_message(event.user_id, resend_msg)
                await bot.send(event, "已将您之前生成的邀请码重新发送至私聊，请注意查收。若未添加好友请添加后再次发送/invite")
            except Exception as e:
                bot.logger.error(f"私聊重发邀请码失败: {e}")
                await bot.send(event, "❌ 发送私聊消息失败，请先添加机器人为好友后再试。")
            return

        # -----------------------------------------------------------
        # 情况二：首次获取的用户，或特权用户（每次都生成新的）
        # -----------------------------------------------------------
        try:
            invite_code = await generate_invite_code(
                base_url=API_SERVER_URL,
                admin_username=ADMIN_USERNAME,
                admin_password=ADMIN_PASSWORD,
                count=1,
            )
        except Exception as e:
            bot.logger.error(f"生成邀请码异常: {e}")
            await bot.send(event, f"❌ 邀请码生成失败，请联系管理员。\n错误信息: {e}")
            return

        # 记录普通用户的邀请码映射（特权账号不写入，保持无限生成）
        if not is_unlimited:
            _save_claimed_code(user_id, invite_code)

        # 构造首次发送的消息
        reply_msg = (
            f"🎉 邀请码生成成功！\n"
            f"🔑 邀请码: {invite_code}\n\n"
            f"请及时前往网站 {API_SERVER_URL} 进行注册绑定。"
        )
        if is_unlimited:
            reply_msg += "\n(✨ 特权用户：不占用限额，每次生成全新码)"

        try:
            await bot.send_friend_message(event.user_id, reply_msg)
            await bot.send(event, "生成成功，已发送至私聊。无bot好友需添加bot好友后在群内再次发送/invite")
        except Exception as e:
            bot.logger.error(f"私聊发送新邀请码失败: {e}")
            await bot.send(event, "⚠️ 邀请码已生成但私聊发送失败，请先添加机器人为好友，添加后在群内重新发送 /invite 即可获取！")