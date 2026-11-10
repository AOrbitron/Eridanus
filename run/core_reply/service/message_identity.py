"""One identity-preserving text representation for observation, trigger and reply."""
import asyncio

from developTools.message.message_components import At, Text


def _value(obj, key):
    value = obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)
    return str(value).strip() if value is not None else ''


def sender_display_name(event):
    sender, user = getattr(event, 'sender', None), getattr(event, 'user', None)
    return (_value(sender, 'card') or _value(user, 'card')
            or _value(sender, 'nickname') or _value(user, 'nickname')
            or _value(user, 'user_name') or str(event.user_id))


async def resolve_user_name(bot, event, user_id, group_id, fallback=''):
    """Resolve the target, never use the sender's name for someone else's @."""
    is_sender = str(user_id) == str(getattr(event, 'user_id', ''))
    sender = getattr(event, 'sender', None) if is_sender else None
    user = getattr(event, 'user', None) if is_sender else None
    card = _value(sender, 'card') or _value(user, 'card')
    if card:
        return card
    try:
        if group_id is not None:
            info = await asyncio.wait_for(bot.get_group_member_info(
                group_id=group_id, user_id=int(user_id)), timeout=2.0)
        else:
            info = await asyncio.wait_for(bot.get_stranger_info(user_id=int(user_id)), timeout=2.0)
        if isinstance(info, dict):
            info = info.get('data', info)
        name = _value(info, 'card') or _value(info, 'nickname') or _value(info, 'user_name')
        if name:
            return name
    except Exception:
        # Missing API, timeout or departed member must not break message handling.
        pass
    return (sender_display_name(event) if is_sender else '') or fallback or f'未知用户({user_id})'


def render_message_text(event, bot_self_id=None, bot_name='', names=None, fallback=''):
    parts = []
    names = names or {}
    for component in getattr(event, 'message_chain', None) or []:
        if isinstance(component, Text):
            parts.append(component.text)
        elif isinstance(component, At):
            uid = str(component.qq)
            if uid == '0':
                parts.append('[@全体成员，非单独艾特机器人]')
            elif bot_self_id is not None and uid == str(bot_self_id):
                parts.append(f'[@{bot_name or "机器人"}，QQ: {uid}，机器人自身]')
            else:
                name = names.get(uid) or component.name or f'未知用户({uid})'
                parts.append(f'[@{name}，QQ: {uid}，非机器人]')
    return ''.join(parts).strip() or fallback.strip()


async def resolve_message_text(event, bot, bot_name=''):
    bot_id = getattr(bot, 'id', None)
    targets = {str(c.qq): c for c in getattr(event, 'message_chain', None) or []
               if isinstance(c, At) and str(c.qq) not in {'0', str(bot_id)}}
    resolved = await asyncio.gather(*(resolve_user_name(
        bot, event, uid, getattr(event, 'group_id', None), component.name or '')
        for uid, component in targets.items()))
    return render_message_text(event, bot_id, bot_name, dict(zip(targets, resolved)),
                               fallback=getattr(event, 'pure_text', '') or '')
