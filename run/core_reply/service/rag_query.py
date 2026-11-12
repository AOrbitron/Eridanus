"""Local query grounding: speaker resolution, conversational context and dates.

No chat-model call is required. All context supplied here must already belong to
the current conversation scope; cross-scope lookup is never performed.
"""
import calendar
import re
from dataclasses import dataclass
from datetime import datetime, timedelta


TOPICS = (
    ("菜馆", "餐馆", "餐厅", "饭店", "吃饭", "用餐", "restaurant", "dinner"),
    ("考研", "考试", "备考", "exam"),
    ("旅行", "旅游", "出游", "travel", "trip"),
    ("宠物", "猫咪", "小猫", "小狗", "pet"),
    ("编程", "代码", "项目", "programming", "code"),
)
FILLER = ("上次", "之前", "那个", "那家", "那件", "这个", "这家", "记得", "还记", "得吗",
          "什么", "怎么", "是不是", "我们", "你们", "他们", "我说", "我去", "今天", "上个月",
          "一个月前", "昨天", "刚才", "一下", "的话", "是的", "还是", "然后", "已经")
DEICTIC = re.compile(r"上次|之前|那[个家件次天]|这[个家件]|还记得|以前|上个[月周]|[个一二两三四五六七八九十\d]+[天周月年]前")


def terms(text):
    text = str(text).lower()
    expanded = set()
    for topic in TOPICS:
        if any(word in text for word in topic):
            expanded.update(topic)
    for filler in FILLER:
        text = text.replace(filler, " ")
    result = set(re.findall(r"[a-z][a-z0-9_-]{2,}", text))
    for run in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        result.update(run[i:i + 2] for i in range(len(run) - 1))
    return result | expanded


def topic_labels(text):
    text = str(text).lower()
    return [" ".join(topic) for topic in TOPICS if any(word in text for word in topic)]


def _months_ago(now, months):
    month = now.year * 12 + now.month - 1 - months
    year, zero_month = divmod(month, 12)
    day = min(now.day, calendar.monthrange(year, zero_month + 1)[1])
    return now.replace(year=year, month=zero_month + 1, day=day)


def time_window(text, timestamp):
    """Only explicit dates constrain retrieval; '上次' alone is a soft recency cue."""
    now = datetime.fromtimestamp(timestamp).astimezone()
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    absolute = re.search(r"(20\d{2})[年/-](\d{1,2})(?:[月/-](\d{1,2}))?", text)
    if absolute:
        try:
            year, month = int(absolute[1]), int(absolute[2])
            start = day.replace(year=year, month=month, day=int(absolute[3] or 1))
            end = start + timedelta(days=1) if absolute[3] else _months_ago(start, -1)
            return start.timestamp(), end.timestamp()
        except ValueError:
            return None
    if "上个月" in text or "上月" in text:
        end = day.replace(day=1)
        return _months_ago(end, 1).timestamp(), end.timestamp()
    if "去年" in text:
        return day.replace(year=day.year - 1, month=1, day=1).timestamp(), day.replace(month=1, day=1).timestamp()
    if "上周" in text or "上星期" in text:
        end = day - timedelta(days=day.weekday())
        return (end - timedelta(days=7)).timestamp(), end.timestamp()
    if "昨天" in text:
        return (day - timedelta(days=1)).timestamp(), day.timestamp()
    match = re.search(r"([一二两三四五六七八九十\d]+)(?:个)?([天周月年])前", text)
    if match:
        numbers = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6,
                   "七": 7, "八": 8, "九": 9, "十": 10}
        count = int(match[1]) if match[1].isdigit() else numbers.get(match[1], 1)
        unit = match[2]
        if unit in ("月", "年"):
            center = _months_ago(day, count * (12 if unit == "年" else 1))
            tolerance = 30 if unit == "年" else 10
        else:
            center = day - timedelta(days=count * (7 if unit == "周" else 1))
            tolerance = 3 if unit == "周" else 1
        return (center - timedelta(days=tolerance)).timestamp(), (center + timedelta(days=tolerance + 1)).timestamp()
    return None


@dataclass(frozen=True)
class QueryPlan:
    text: str
    original: str
    owner: str | None
    window: tuple | None
    deictic: bool
    keywords: frozenset
    context_used: int
    skip: bool
    ambiguous_person: bool


def build_query(query, user_id, context, now, config=None, is_group=False):
    config = config or {}
    query = str(query).strip()
    deictic = bool(DEICTIC.search(query))
    explicit_id = re.search(r"(?:用户ID|ID|QQ)[:：\s]*(\d+)", query, re.I)
    owner = explicit_id[1] if explicit_id else None
    # Match nicknames only when unambiguous within this scope's recent context.
    names = {}
    for item in context:
        if item.get("role", "user") == "assistant":
            continue
        name = str(item.get("speaker", item.get("sender", "")))
        uid = item.get("user_id")
        if name and uid is not None and name in query and not re.search(r"(?:我|我们)(?:和|跟|与)" + re.escape(name), query):
            names.setdefault(name, set()).add(str(uid))
    ambiguous_person = owner is None and (any(len(ids) > 1 for ids in names.values()) or len(names) > 1)
    if owner is None:
        matches = {next(iter(ids)) for ids in names.values() if len(ids) == 1}
        if len(matches) == 1:
            owner = matches.pop()
    collective = bool(re.search(r"大家|群里|谁|有人|我们|everyone|who", query, re.I))
    if owner is None and not ambiguous_person and (not is_group or (not collective and (deictic or re.search(r"(?:^|[，。！？\s])我|我的|我上|我之|我去", query)))):
        owner = str(user_id)
    keywords = terms(query)
    labels = topic_labels(query)
    selected = []
    last_user = None
    normalized = []
    for item in context:
        role = item.get("role", "user" if item.get("user_id") is not None else "assistant")
        if role not in ("user", "assistant"):
            continue
        uid = item.get("user_id")
        if role == "user":
            last_user = str(uid) if uid is not None else (None if is_group else str(user_id))
        else:
            uid = item.get("owner_id", uid if uid is not None else last_user)
        uid = str(uid) if uid is not None else None
        value = item.get("content", item.get("text", ""))
        if not isinstance(value, str) or not value.strip() or value.strip() == query:
            continue
        if owner is not None and uid != owner:
            continue
        normalized.append((role, value.strip()))
    if deictic:
        for role, text in reversed(normalized[-12:]):
            if not keywords or keywords & terms(text):
                selected.append((role, text[:300]))
                if len(selected) >= max(1, int(config.get("context_messages", 4))):
                    break
    selected.reverse()
    grounded = query
    if labels:
        grounded += "\n相关话题：" + "; ".join(labels)
    if selected:
        limit = max(100, int(config.get("context_chars", 700)))
        grounded += "\n当前对话线索（仅辅助定位，不是历史事实）：\n" + "\n".join(
            ("Bot说：" if role == "assistant" else "用户说：") + text for role, text in selected
        )[-limit:]
    simple = re.sub(r"[\W_]+", "", query.lower())
    skip = config.get("mode", "adaptive") == "adaptive" and not deictic and bool(re.fullmatch(
        r"(?:嗯+|哦+|好+|好的|知道了|收到|谢谢|哈哈+|早安|晚安|你好|嗨|hello|hi|ok|thanks)", simple))
    return QueryPlan(grounded[:4000], query, owner, time_window(query, now), deictic,
                     frozenset(keywords), len(selected), skip, ambiguous_person)
