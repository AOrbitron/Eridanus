# encoding: utf-8
import asyncio
import base64
import functools
import hashlib
import importlib
import json
import logging
import os
import re
import shutil
import sys
import threading
import time
import urllib
from io import StringIO

from cryptography.fernet import Fernet
from flask import Flask, request, jsonify, make_response, send_file, send_from_directory
from flask_cors import CORS
from ruamel.yaml import YAML, comments
from ruamel.yaml.scalarint import ScalarInt
from ruamel.yaml.scalarstring import DoubleQuotedScalarString, SingleQuotedScalarString
import traceback


sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from developTools.utils.logger import get_logger
from framework_common.utils.install_and_import import install_and_import
from framework_common.database_util.User import get_user, update_user   # 更新用户数据用
from framework_common.framework_util.function_control import (
    list_all_functions, save_disabled, list_all_skills, save_disabled_skills,
)
from userdb_query import get_users_range, get_users_count, search_users_by_id, get_user_signed_days
from chatdb_manage import get_msg, get_msg_since, get_android_history_records, update_msg, delete_specified_msg, delete_all_msg, get_file_storage, update_file_storage

flask_sock = install_and_import("flask_sock")
from flask_sock import Sock

psutil = install_and_import("psutil")
httpx = install_and_import("httpx")
zipfile = install_and_import("zipfile")
# 全局变量，用于存储 logger 实例和屏蔽的日志类别
_logger = None
_blocked_loggers = ["INFO_MSG", "DEBUG"]

app = Flask(__name__, static_folder="dist", static_url_path="")
app.json.sort_keys = False  # 不要对json排序



log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)  # 只显示 ERROR 级别及以上的日志（隐藏 INFO 和 DEBUG）
logger = get_logger(blocked_loggers=["DEBUG", "INFO_MSG"])

CORS(app, supports_credentials=True)  # 启用跨域支持
sock = Sock(app)  # 初始化Flask sock

try:
    from tool import get_git_path
    git_path = get_git_path()
except Exception:
    parent_dir = os.path.dirname(os.getcwd())
    candidate_parent = os.path.join(parent_dir, "environments", "MinGit", "cmd", "git.exe")
    candidate_local = os.path.join("environments", "MinGit", "cmd", "git.exe")
    if os.path.exists(candidate_parent):
        git_path = candidate_parent
    elif os.path.exists(candidate_local):
        git_path = candidate_local
    else:
        git_path = "git"

logger.info(f"Git path: {git_path}")

# 默认用户信息
user_info = {
    # webUI默认账户密码
    "account": "eridanus",
    "password": "f6074ac37e2f8825367d9ae118a523abf16924a86414242ae921466db1e84583",
    # 机器人好友和群聊数量
    "friends": 0,
    "groups": 0,
}

# ip白名单，白名单不需要登录，便于不看文档的用户和远程开发调试使用
# 出于安全考虑，release不再使用,仅用于调试
ip_whitelist = []
# ip_whitelist = ["127.0.0.1","192.168.195.128","192.168.195.137","::1"]

# 合法的消息事件，其余不储存进数据库。
valid_message_actions = ['send_group_forward_msg', 'send_private_forward_msg', 'send_group_msg', 'send_private_msg', 'upload_group_file', 'upload_private_file', 'get_msg']

# 用户信息文件
user_file = "./user_info.yaml"

is_saving_yaml = False

# 会话信息字典（token跟expires）
auth_info = {}

# 会话有效时长，秒数为单位
auth_duration = 720000
# 可用的git源
REPO_SOURCES = [
    "https://ghfast.top/https://github.com/avilliai/Eridanus.git",
    "https://mirror.ghproxy.com/https://github.com/avilliai/Eridanus",
    "https://github.moeyy.xyz/https://github.com/avilliai/Eridanus",
    "https://github.com/avilliai/Eridanus.git",
    "https://gh.llkk.cc/https://github.com/avilliai/Eridanus.git",
    "https://gitclone.com/github.com/avilliai/Eridanus.git"
]


# 配置文件路径
def get_plugin_description(plugin_dir):
    init_file = os.path.join(plugin_dir, '__init__.py')
    if not os.path.exists(init_file):
        return None
    spec = importlib.util.spec_from_file_location("plugin_init", init_file)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        return getattr(module, 'plugin_description', None)
    except Exception:
        return None


def build_yaml_file_map(run_dir):
    yaml_map = {}
    run_dir = os.path.abspath(run_dir)
    for root, _, files in os.walk(run_dir):
        for file in files:
            if not file.endswith('.yaml'):
                continue
            # 如果文件名包含"基础配置.menu"则跳过
            # if "menu.yaml" in file:
                # continue
            abs_path = os.path.join(root, file)
            rel_path = os.path.relpath(abs_path, run_dir).replace("\\", "/")
            parts = rel_path.split("/")
            if len(parts) < 2:
                continue  # 不处理 run 目录下直接放的文件
            plugin_dir = os.path.join(run_dir, parts[0])
            plugin_desc = get_plugin_description(plugin_dir)
            if not plugin_desc:
                continue  # 没有 plugin_description 就跳过
            filename = os.path.splitext(parts[-1])[0]
            key = f"{plugin_desc}.{filename}"
            yaml_map[key] = abs_path
    return yaml_map


RUN_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'run'))
YAML_FILES = build_yaml_file_map(RUN_DIR)
YAML_FILES.pop("live2d desktop pet.config", None)
YAML_FILES.pop("定时任务.sheduled_tasks_push_groups_ordinary", None)

# 指定前置顺序
priority_keys = [
    "基础配置.basic_config",
    "mai_reply 新版ai对话.config",
    "tts_v2.config",
    "mai_reply 新版ai对话.rag",
    "mai_reply 新版ai对话.proactive",
    "ai绘画.config",
    "qq空间.config",
    #"live2d desktop pet.config",
]

# 重新排序
ordered_yaml_files = {}

for key in priority_keys:
    if key in YAML_FILES:
        ordered_yaml_files[key] = YAML_FILES.pop(key)

# 剩余保持原有顺序
ordered_yaml_files.update(YAML_FILES)

YAML_FILES = ordered_yaml_files

#print(YAML_FILES)

# 初始化 YAML 解析器（支持注释）
yaml = YAML()
yaml.preserve_quotes = True

"""
读取配置
"""

"""
新旧数据合并
"""


def merge_dicts(old, new):
    """
    递归合并旧数据和新数据。
    """
    for k, v in old.items():
        logger.server(
            f"处理 key: {k}, old value: {v} old type: {type(v)}, new value: {new.get(k)} new type: {type(new.get(k))}")
        # 如果值是一个字典，并且键在新的yaml文件中，那么我们就递归地更新键值对
        if isinstance(v, dict) and k in new and isinstance(new[k], dict):
            merge_dicts(v, new[k])
        # 如果值是列表，且新旧值都是列表，则合并并去重
        elif isinstance(v, list) and k in new and isinstance(new[k], list):
            # 合并列表并去重，保留旧列表顺序
            new[k] = [item for item in v if v is not None]
        elif k in new and type(v) != type(new[k]):

            if isinstance(new[k], DoubleQuotedScalarString) or isinstance(new[k], SingleQuotedScalarString):
                v = str(v)
                new[k] = v
            elif isinstance(new[k], ScalarInt) or isinstance(v, ScalarInt):
                v = int(v)
                new[k] = v
            else:
                logger.server(f"类型冲突 key: {k}, old value type: {type(v)}, new value type: {type(new[k])}")
                logger.warning(f"旧值: {v}, 新值: {new[k]} 直接覆盖")
                new[k] = v
        # 如果键在新的yaml文件中且类型一致，则更新值
        elif k in new:
            # logger.server(f"更新 key: {k}, old value: {v}, new value: {new[k]}")
            new[k] = v
        # 如果键不在新的yaml中，直接添加
        # else:
        #     logger.server(f"移除键 key: {k}, value: {v}")


def conflict_file_dealer(old_data: dict, file_new='new_aiReply.yaml'):
    try:
        logger.info(f"冲突文件处理: {file_new}")
    
        old_data_yaml_str = StringIO()
        yaml.dump(old_data, old_data_yaml_str)
        old_data_yaml_str.seek(0)  # 将光标移到字符串开头，以便后续读取
    
        # 将 YAML 字符串加载回 ruamel.yaml 对象
        old_data = yaml.load(old_data_yaml_str)
        # 加载新的YAML文件
        with open(file_new, 'r', encoding="utf-8") as file:
            new_data = yaml.load(file)
    
        # 遍历旧的YAML数据并更新新的YAML数据中的相应值
        merge_dicts(old_data, new_data)
    
        # 把新的YAML数据保存到新的文件中，保留注释
        with open(file_new, 'w', encoding="utf-8") as file:
            yaml.dump(new_data, file)
        return True
    except Exception as e:
        logger.error(f"冲突文件处理失败: {e}")
        return False


def extract_comments(data, path="", comments_dict=None):
    if comments_dict is None:
        comments_dict = {}

    if isinstance(data, comments.CommentedMap):
        for key, value in data.items():
            new_path = f"{path}.{key}" if path else key
            # 提取行尾注释
            if key in data.ca.items and data.ca.items[key][2]:
                comment = data.ca.items[key][2].value.strip("# \n")
                comments_dict[new_path] = comment
            # 递归处理子节点
            extract_comments(value, new_path, comments_dict)

    elif isinstance(data, comments.CommentedSeq):
        for index, item in enumerate(data):
            new_path = f"{path}[{index}]"
            # 序列整体注释（如果存在）
            if data.ca.comment and data.ca.comment[0]:
                comments_dict[path] = data.ca.comment[0].value.strip("# \n")
            # 递归处理子节点
            extract_comments(item, new_path, comments_dict)

    return comments_dict


def extract_key_order(data, path="", order_dict=None):
    if order_dict is None:
        order_dict = {}

    if isinstance(data, comments.CommentedMap):
        order_dict[path] = list(data.keys())  # 记录当前层级 key 的顺序
        for key, value in data.items():
            new_path = f"{path}.{key}" if path else key
            extract_key_order(value, new_path, order_dict)

    elif isinstance(data, comments.CommentedSeq):
        # 对于序列，记录其位置
        for index, item in enumerate(data):
            new_path = f"{path}[{index}]"
            extract_key_order(item, new_path, order_dict)

    return order_dict


def load_yaml_with_comments(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = yaml.load(f)
        # 提取所有注释
        order = extract_key_order(data)
        comments = extract_comments(data)
        return {"data": data, "comments": comments, "order": order}
    except Exception as e:
        return {"error": str(e)}


def load_yaml(file_path):
    """加载 YAML 文件并返回内容及注释"""
    try:
        return load_yaml_with_comments(file_path)
    except Exception as e:
        return {"error": str(e)}


def save_yaml(file_path, data):
    """将数据保存回 YAML 文件"""

    # logger.server(f"保存文件: {file_path}")
    # logger.server(f"数据: {data}")
    return conflict_file_dealer(data["data"], file_path)

# 鉴权
def auth(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        #白名单直接放行
        # print(request.remote_addr)
        if request.remote_addr in ip_whitelist:
            return func(*args, **kwargs)
        global auth_info
        recv_token = request.cookies.get('auth_token')
        try:
            if auth_info[recv_token] < int(time.time()):  # 如果存在token且过期
                return jsonify({"error": "Unauthorized"})
        except:  # 不存在token
            return jsonify({"error": "Unauthorized"})
        return func(*args, **kwargs)
    return wrapper

# 静态文件缓存控制，加快响应
#先不要了，缓存不刷新，页面总是出问题
# @app.after_request
# def after_request(response):
#     # 为静态文件添加缓存控制头
#     if request.endpoint == 'static':
#         response.headers['Cache-Control'] = 'public, max-age=2592000'  # 缓存一月
#     return response

@app.route("/api/load/<filename>", methods=["GET"])
@auth
def load_file(filename):
    """加载指定的 YAML 文件"""
    if filename not in YAML_FILES:
        return jsonify({"error": "文件名错误"})

    file_path = YAML_FILES[filename]
    if not os.path.exists(file_path):
        return jsonify({"error": "文件不存在"})

    data_with_comments = load_yaml(file_path)
    rtd = jsonify(data_with_comments)

    return rtd


@app.route("/api/save/<filename>", methods=["POST"])
@auth
def save_file(filename):
    """接收前端数据并保存到 YAML 文件"""
    global is_saving_yaml
    if is_saving_yaml:
        return jsonify({"error": "操作过快！"})
    is_saving_yaml = True
    if filename not in YAML_FILES:
        return jsonify({"error": "文件名错误"})

    file_path = YAML_FILES[filename]
    if not os.path.exists(file_path):
        return jsonify({"error": "文件不存在"})

    data = request.json  # 获取前端发送的 JSON 数据
    if not data:
        return jsonify({"error": "无效数据"})
    
    result = save_yaml(file_path, data)
    is_saving_yaml = False
    if result:
        return jsonify({"message": "文件保存成功"})
    elif result == False:
        return jsonify({"error": "文件保存失败"})


@app.route("/api/sources", methods=["GET"])
@auth
def list_sources():
    """列出所有可用的git源"""
    return jsonify(list(REPO_SOURCES))


@app.route("/api/files", methods=["GET"])
@auth
def list_files():
    """列出所有可用的 YAML 文件"""
    return jsonify({"files": list(YAML_FILES.keys())})


def search_yaml_content(search_key):
    """在所有YAML文件中搜索指定的键名"""
    # 构建索引字典
    index_dict = {}
    for filename, file_path in YAML_FILES.items():
        try:
            # 加载YAML文件
            with open(file_path, 'r', encoding='utf-8') as f:
                yaml_data = yaml.load(f)
            
            # 递归搜索键名
            def search_in_dict(d, path=""):
                results = []
                for key, value in d.items():
                    current_path = f"{path}.{key}" if path else key
                    
                    # 如果键是字符串且匹配搜索词
                    if isinstance(key, str) and search_key.lower() in key.lower():
                        results.append({
                            "file": filename,
                            "path": current_path,
                            "value": value
                        })
                    
                    # 如果值是字典，递归搜索
                    if isinstance(value, dict):
                        results.extend(search_in_dict(value, current_path))
                    
                return results
            
            # 在当前文件中搜索
            if isinstance(yaml_data, dict):
                matches = search_in_dict(yaml_data)
                if matches:
                    index_dict[filename] = matches
                    
        except Exception as e:
            logger.error(f"处理文件 {filename} 时出错: {str(e)}")
            continue
    
    # 构建结果列表
    result_list = []
    for filename, matches in index_dict.items():
        for match in matches:
            result_list.append({
                "file": filename,
                "path": match["path"],
                "value": match["value"]
            })
    
    return result_list


@app.route("/api/search_yaml", methods=["POST"])
@auth
def search_yaml_keys():
    """根据键名搜索YAML文件内容"""
    try:
        # 获取请求数据
        data = request.get_json()
        search_key = data.get("search")
        
        if not search_key:
            return jsonify({"error": "搜索键名不能为空"})
        
        # 搜索YAML内容
        result_list = search_yaml_content(search_key)
        
        return jsonify({"results": result_list})
        
    except Exception as e:
        logger.error(f"搜索YAML键名时出错: {str(e)}")
        return jsonify({"error": f"搜索时出错: {str(e)}"})


@app.route("/api/functions/list", methods=["GET"])
@auth
def list_functions():
    """列出所有插件声明的函数及启用状态（供函数管理界面使用）"""
    try:
        return jsonify({"plugins": list_all_functions()})
    except Exception as e:
        logger.error(f"列出函数失败: {e}")
        return jsonify({"error": f"列出函数失败: {e}"})


@app.route("/api/functions/save", methods=["POST"])
@auth
def save_functions():
    """保存被禁用的函数名列表。body: {"disabled": ["name", ...]}"""
    data = request.get_json(silent=True) or {}
    disabled = data.get("disabled", [])
    if not isinstance(disabled, list) or not all(isinstance(x, str) for x in disabled):
        return jsonify({"error": "disabled 必须是字符串列表"})
    try:
        save_disabled(disabled)
        return jsonify({"message": "保存成功"})
    except Exception as e:
        logger.error(f"保存函数开关失败: {e}")
        return jsonify({"error": f"保存失败: {e}"})


@app.route("/api/skills/list", methods=["GET"])
@auth
def list_skills():
    """列出所有 skill 包及启用状态（供功能管理界面使用）"""
    try:
        return jsonify({"skills": list_all_skills()})
    except Exception as e:
        logger.error(f"列出 skill 失败: {e}")
        return jsonify({"error": f"列出 skill 失败: {e}"})


@app.route("/api/skills/save", methods=["POST"])
@auth
def save_skills():
    """保存被禁用的 skill 名列表。body: {"disabled": ["name", ...]}"""
    data = request.get_json(silent=True) or {}
    disabled = data.get("disabled", [])
    if not isinstance(disabled, list) or not all(isinstance(x, str) for x in disabled):
        return jsonify({"error": "disabled 必须是字符串列表"})
    try:
        save_disabled_skills(disabled)
        return jsonify({"message": "保存成功"})
    except Exception as e:
        logger.error(f"保存 skill 开关失败: {e}")
        return jsonify({"error": f"保存失败: {e}"})


@app.route("/api/pull", methods=["POST"])
@auth
def pull_eridanus():
    """从仓库拉取eridanus(未完成)"""
    return jsonify({"message": "success"})


@app.route("/api/clone", methods=["POST"])
@auth
def clone_source():
    data = request.get_json()
    source_url = data.get("source")

    if not source_url:
        return jsonify({"error": "Missing source URL"})
    if os.path.exists("Eridanus"):
        return jsonify({"error": "Eridanus already exists。请删除现有Eridanus后再尝试克隆"})

    logger.server(f"开始克隆: {source_url}")
    os.system(f"{git_path} clone --depth 1 {source_url}")

    return jsonify({"message": f"开始部署 {source_url}"})


# 登录api
@app.route("/api/login", methods=['POST'])
def login():
    global auth_info
    global auth_duration
    data = request.get_json()
    # 不能给用户看
    # logger.server(data)
    if data["account"] == user_info["account"] and data["password"] == user_info["password"]:
        logger.server(f"WebUI登录 - {request.remote_addr}")
        auth_token = Fernet.generate_key().decode()  # 生成token
        auth_expires = int(time.time() + auth_duration)  # 生成过期时间
        auth_info[auth_token] = auth_expires  # 加入字典
        resp = make_response(jsonify({"message": "登录成功", "auth_token": auth_token}))
        resp.set_cookie("auth_token", auth_token)
        resp.set_cookie("auth_expires", str(auth_expires))
        return resp
    else:
        logger.error(f"WebUI登录失败 - {request.remote_addr}")
        return jsonify({"error": "Failed"})


# 登出api
@app.route("/api/logout", methods=['GET', 'POST'])
def logout():
    global auth_info
    recv_token = request.cookies.get('auth_token')
    try:
        del auth_info[recv_token]
        # logger.server("用户登出")
        return jsonify({"message": "退出登录成功"})
    except:
        return jsonify({"error": "登录信息无效"})


# 账户修改
@app.route("/api/profile", methods=['GET', 'POST'])
@auth
def profile():
    global user_info
    global auth_info
    if request.method == 'GET':
        return jsonify({"account": user_info['account']})
    elif request.method == 'POST':
        data = request.get_json()
        logger.server(data)
        if data["account"]:
            user_info["account"] = data["account"]
        if data["password"]:
            user_info["password"] = data["password"]
            with open(user_file, 'w', encoding="utf-8") as file:
                yaml.dump(user_info, file)
        auth_info = {}  # 清空登录信息
        return jsonify({"message": "账户信息修改成功，请重新登录"})


# 用户管理
@app.route("/api/usermgr/userList", methods=["GET"])
@auth
def get_users():
    try:
        # 当前页
        current = int(request.args.get("current"))
        # 每页数量
        page_size = int(request.args.get("pageSize"))
        start = (current - 1) * page_size
        end = start + page_size
        sort_by = request.args.get("sortBy")
        sort_order = request.args.get("sortOrder")

        async def fetch_users():
            if request.args.get("user_id"):
                user_id = request.args.get("user_id")
                total_count = await get_users_count(user_id)
                result = await search_users_by_id(user_id, start, end, sort_by, sort_order)
                return total_count, result
            else:
                # 获取用户总数
                total_count = await get_users_count()
                # 获取指定范围的用户
                users = await get_users_range(start, end, sort_by, sort_order)
                return total_count, users

        total_count, users = asyncio.run(fetch_users())

        return jsonify({
            "data": users,
            "total": total_count,
            "success": True,
            "pageSize": page_size,
            "current": current,
        })
    except Exception as e:
        return jsonify({"error": f"获取用户信息失败: {e}"})

# 修改用户信息
@app.route("/api/usermgr/modUser", methods=["POST"])
@auth
def mod_user():
    try:
        data = request.get_json()
        result = asyncio.run(
            update_user(
                user_id = int(data.get("user_id")),
                nickname = data.get("nickname"),
                card = data.get("card"),
                sex = data.get("sex"),
                age = int(data.get("age")),
                city = data.get("city"),
                permission = int(data.get("permission")),
                ai_token_record = int(data.get("ai_token_record")),
                user_portrait = data.get("user_portrait"),
            )
        )
        return jsonify({"message": result })
    except Exception as e:
        return jsonify({"error": f"更新用户信息失败: {e}"})


@app.route("/api/diagnosis", methods=["GET","POST"])
@auth
def diagnosis():
    """日志"""
    try:
        if request.method == "GET":
            # 返回 ../log 目录下的文件列表
            logs_dir = os.path.join(BASE_DIR, "..", "log")
            files = [f for f in os.listdir(logs_dir) if os.path.isfile(os.path.join(logs_dir, f))]
            return jsonify({"files": files})
        elif request.method == "POST":
            # 获取json字段中{"file":"filename.log"}的文件名称，并返回文件
            data = request.get_json()
            filename = data.get("file")
            logs_dir = os.path.join(BASE_DIR, "..", "log")
            file_path = os.path.join(logs_dir, filename)
            # 确保文件在 log 目录下，防止路径遍历攻击
            if not os.path.abspath(file_path).startswith(os.path.abspath(logs_dir)):
                return jsonify({"error": "Invalid file path"})
            if not os.path.exists(file_path):
                return jsonify({"error": "File not found"})
            # 检查文件大小，如果大于特定值返回错误
            file_size = os.path.getsize(file_path)
            if file_size > 30 * 1024 * 1024:  # 30MB
                return jsonify({"error": f"日志文件过大: {file_size / 1024 / 1024:.2f} MB"})
            return send_file(file_path)
    except Exception as e:
        return jsonify({"error": str(e)})



# 机器人的基本信息
@app.route("/api/dashboard/basicInfo", methods=["GET"])
@auth
def basic_info():
    try:
        system_info_only = request.args.get("systemInfo")
        # 获取系统信息
        cpu_percent = psutil.cpu_percent(interval=0.5)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        if system_info_only:
            return jsonify({
                "systemInfo": {
                    "cpuUsage": cpu_percent,
                    "totalMemory": memory.total,
                    "usedMemory": memory.used,
                    "totalDisk": disk.total,
                    "usedDisk": disk.used
                },
            })
        # 获取好友和群聊信息
        with open(user_file, 'r', encoding="utf-8") as file:
            yaml_file = yaml.load(file)
            user_info['friends'] = yaml_file['friends']
            user_info['groups'] = yaml_file['groups']

        # 获取排行榜数据
        async def get_ranks():
            token_rank = await get_users_range(0, 10, "ai_token_record", "DESC")
            signin_rank = await get_user_signed_days()
            total_users = await get_users_count()
            return token_rank, signin_rank, total_users

        token_rank, signin_rank, total_users = asyncio.run(get_ranks())

        basic_info = {
            "systemInfo": {
                "cpuUsage": cpu_percent,
                "totalMemory": memory.total,
                "usedMemory": memory.used,
                "totalDisk": disk.total,
                "usedDisk": disk.used
            },
            "botInfo": {
                "totalUsers": total_users,
                "totalFriends": user_info['friends'],
                "totalGroups": user_info['groups']
            },
            "ranks": {
                "tokenRank": token_rank,
                "signInRank": signin_rank
            }
        }
        return jsonify(basic_info)
    except Exception as e:
        return jsonify({"error": f"获取基本信息失败: {e}"})

BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # 普通运行环境

UPLOAD_FOLDER = os.path.join(BASE_DIR, "chat_files")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)  # 确保目录存在
ALLOWED_EXTENSIONS = {'gif', 'png', 'jpg', 'jpeg', 'bmp', 'webp', 'tif', 'tiff' , 'heif', 'ico' , 'heic' , 'svg' , 'avif' , 'jfif', 'zip'}
def allowed_file(filename):
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def gen_file_name(filename):
    """
    如果文件存在，加后缀重命名。
    """
    i = 1
    # print(filename)
    while os.path.exists(os.path.join(UPLOAD_FOLDER, filename)):
        name, extension = os.path.splitext(filename)
        name = str(name).rstrip(f"_{i-1}")
        filename = '%s_%s%s' % (name, str(i), extension)
        i += 1
    # print(filename)
    return filename

#上传文件
@app.route("/api/chat/uploadFile", methods=["POST"])
@auth
def upload_file():
    try:
        files = request.files['file']
        if files:
            filename = gen_file_name(files.filename)
            mime_type = files.content_type

            # if not allowed_file(files.filename):
            #     return jsonify({"files": [{"error": "不支持的文件格式"}]})
            # else:
                # save file to disk
            uploaded_file_path = os.path.join(UPLOAD_FOLDER, filename)
            files.save(uploaded_file_path)

                # size = os.path.getsize(uploaded_file_path)

            return jsonify({"files": [{
                        "name": filename,
                        "type": mime_type,
                        # "size": size,
                        "path": "file://"+uploaded_file_path}]})
    except Exception as e:
        return jsonify({"error": str(e)})

# webui对话需要保存聊天记录，从缓存文件夹移动文件到聊天文件文件夹(done)；聊天文件可以通过webUI的文件管理器管理(todo)
@app.route("/api/chat/file", methods=["GET"])
@auth
def get_file():
    try:
        origin_file_path = request.args.get("path", "")
        file_name = request.args.get("name", "")
        if origin_file_path.startswith("file://"):
            # 查询数据库有没有存入文件
            file_name = asyncio.run(get_file_storage(origin_file_path))
            # 若有
            if file_name:
                return send_file(os.path.join(UPLOAD_FOLDER, file_name))
            else :
                file_path = origin_file_path[7:]  # 去掉 "file://"
            # 从指定目录移动文件
                file_name = os.path.basename(file_path)
                dest_path = os.path.join(UPLOAD_FOLDER, file_name)
            # logger.server(f"目标路径: {dest_path} 原始路径: {file_path}")
                if file_path != dest_path:
                    dest_path = os.path.join(UPLOAD_FOLDER, gen_file_name(file_name))
                    shutil.move(file_path, dest_path)  # 移动文件
            # 储存文件信息到键值对
                asyncio.run(update_file_storage(origin_file_path,file_name))
            # 返回文件
        return send_file(os.path.join(UPLOAD_FOLDER, file_name))
    except Exception as e:
        return jsonify({"error":str(e)})

# 获取音乐卡片，如果能解决前端请求不发options就不用这个。
@app.route("/api/chat/music", methods=["POST"])
@auth
def get_music():
    try:
        response = httpx.post(
            "https://ss.xingzhige.com/music_card/card", #赞美源神
            json = request.json
        )
        # 解析返回的JSON数据
        result = response.json()
        music_data = result['meta']['music']
        return jsonify(music_data)
    except Exception as e:
        return jsonify({"error": f"请求时出错: {str(e)}"})

# 获取聊天历史记录
@app.route("/api/chat/get_history", methods=["GET"])
@auth
def get_history():
    try:
        start = int(request.args.get("start"))
        end = int(request.args.get("end"))
        result = asyncio.run(get_msg(start,end))
        return jsonify({"data": result})
    except Exception as e:
        return jsonify({"error":e})

# 删除历史聊天记录
@app.route("/api/chat/del_history", methods=["POST","GET"])
@auth
def del_history():
    try:
        # 带msg_id就是删除特定id聊天记录。应当返回一个数组。不该用args，要换成json。多选bubble还没有实现，等antd x更新(todo)
        msg_id = request.args.get("msg_id")
        if msg_id:
            asyncio.run(delete_specified_msg(msg_id))
        else:
            asyncio.run(delete_all_msg())
        return jsonify({"message": "删除成功"})
    except Exception as e:
        return jsonify({"error":e})

# 重启服务器
@app.route("/api/tools/restart", methods=["GET"])
@auth
def restart_server():
    try:
        return jsonify({"message": "功能开发中，敬请期待"})
    except Exception as e:
        return jsonify({"error":e})


# 菜单编辑器
@app.route("/api/menu/load", methods=["GET"])
@auth
def menu_editor():
    """加载菜单的 YAML 文件"""
    file_path = YAML_FILES["基础配置.menu"]
    data_with_comments = load_yaml(file_path)
    rtd = jsonify(data_with_comments["data"]["help_menu"]["content"])
    return rtd

@app.route("/api/menu/update", methods=["POST"])
@auth
def update_menu():
    """更新菜单的 YAML 文件"""
    try:
        data = {"data": {"help_menu": {"content": request.json}}}  # 将收到的数据封装到新字典
        file_path = YAML_FILES["基础配置.menu"]
        result = save_yaml(file_path, data)
        if result:
            return jsonify({"message": "菜单保存成功"})
        else:
            return jsonify({"error": "菜单保存失败"})
    except Exception as e:
        return jsonify({"error":e})

@app.route("/api/tools/export_yaml", methods=["GET"])
@auth
def export_yaml():
    try:
        # 导入tool.py中的export_yaml函数
        sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from tool import export_yaml as export_yaml_func
        
        # 调用导出函数
        export_yaml_func()
        
        # 创建zip文件名
        timestamp = int(time.time())
        zip_filename = f"yaml_backups_{timestamp}.zip"
        zip_filepath = os.path.join(UPLOAD_FOLDER, zip_filename)
        # 压缩old_yamls文件夹
        with zipfile.ZipFile(zip_filepath, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk("old_yamls"):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.join("old_yamls", os.path.relpath(file_path, "old_yamls"))
                    zipf.write(file_path, arcname)
        # 删除old_yamls文件夹
        shutil.rmtree("old_yamls")
        
        # 储存文件信息到数据库
        asyncio.run(update_file_storage(zip_filename,zip_filename))
        
        return jsonify({"message": "导出成功", "file": zip_filename})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/api/tools/import_yaml", methods=["POST"])
@auth
def import_yaml():
    try:
        # 获取传入的文件名
        data = request.get_json()
        zip_filename = data.get("file")
        
        if not zip_filename:
            return jsonify({"error": "文件名不能为空"})
        
        # 检查文件是否存在
        zip_filepath = os.path.join(UPLOAD_FOLDER, zip_filename)
        if not os.path.exists(zip_filepath):
            return jsonify({"error": "文件不存在"})
        
        # 解压文件到上一级目录
        extract_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with zipfile.ZipFile(zip_filepath, 'r') as zip_ref:
            # 获取压缩包内所有文件和文件夹的路径
            namelist = zip_ref.namelist()
            logger.server(f"压缩包内文件和文件夹路径: {namelist}")
            # 检查根目录是否只有一个文件夹，且仅为 old_yamls
            root_items = {item.split('/')[0] for item in namelist if item.split('/')[0]}
            if len(root_items) == 1 and 'old_yamls' in root_items:
                zip_ref.extractall(extract_path)
            else:
                raise ValueError("压缩包目录有误")
        
        # 导入tool.py中的import_yaml函数
        sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from tool import import_yaml as import_yaml_func
        
        # 调用导入函数
        import_yaml_func()
        
        # 删除解压后的文件夹
        shutil.rmtree("old_yamls")
        
        return jsonify({"message": "导入成功"})
    except Exception as e:
        return jsonify({"error": str(e)})

# API和静态文件外的路由（404）完全交给React前端处理,根路由都不用了
@app.errorhandler(404)
def index(e):
    return send_from_directory(app.static_folder, 'index.html')

clients = set()

# WebSocket路由

# ==========================================
# Android 客户端 / 统一中转接口与图床缓存
# ==========================================
android_pending_events = {}       # user_id -> threading.Event
android_pending_responses = {}    # user_id -> reply_data dict {"reply": str, "images": list}

def clean_expired_chat_files(days=3):
    """清理 chat_files 中超过指定天数(默认3天)的过期临时图片文件"""
    try:
        if not os.path.exists(UPLOAD_FOLDER):
            return
        now = time.time()
        expire_seconds = days * 86400
        removed_count = 0
        for fname in os.listdir(UPLOAD_FOLDER):
            fpath = os.path.join(UPLOAD_FOLDER, fname)
            if os.path.isfile(fpath):
                try:
                    mtime = os.path.getmtime(fpath)
                    if (now - mtime) > expire_seconds:
                        os.remove(fpath)
                        removed_count += 1
                except Exception:
                    pass
        if removed_count > 0:
            logger.server(f"[FileCache] 清理了 {removed_count} 个超过 {days} 天的过期临时文件")
    except Exception as e:
        logger.warning(f"[FileCache] 清理过期文件失败: {e}")

def _start_file_cleanup_thread():
    """后台定时清理线程，每 12 小时清理一次超过 3 天的文件"""
    def _loop():
        while True:
            try:
                clean_expired_chat_files(days=3)
            except Exception:
                pass
            time.sleep(43200)  # 12 小时
    t = threading.Thread(target=_loop, daemon=True, name="FileCleanupThread")
    t.start()

# 启动定时清理线程
_start_file_cleanup_thread()

def cache_local_image_for_remote(img_path_or_url):
    """
    ?????? file:// ????? WebUI ???? chat_files/
    ?? Android App ????????? /api/chat/media/<filename> ????
    """
    if not img_path_or_url or not isinstance(img_path_or_url, str):
        return img_path_or_url

    clean_str = img_path_or_url.strip()
    if clean_str.startswith("/api/chat/media/"):
        return clean_str
    if clean_str.startswith("http://") or clean_str.startswith("https://") or clean_str.startswith("base64://"):
        return clean_str

    s = clean_str
    if s.startswith("file:///"):
        s = s[8:]
    elif s.startswith("file://"):
        s = s[7:]

    try:
        s = urllib.parse.unquote(s)
    except Exception:
        pass

    if len(s) >= 3 and s[0] == '/' and s[2] == ':':
        s = s[1:]
    elif len(s) >= 2 and s[0] == '\\' and s[2] == ':':
        s = s[1:]

    local_path = os.path.normpath(s)
    candidate_paths = [local_path]
    if not os.path.isabs(local_path):
        candidate_paths.append(os.path.normpath(os.path.join(os.path.dirname(BASE_DIR), local_path)))
        candidate_paths.append(os.path.normpath(os.path.join(BASE_DIR, local_path)))

    resolved_path = None
    for cp in candidate_paths:
        if os.path.isfile(cp):
            resolved_path = cp
            break

    if resolved_path:
        try:
            ext = os.path.splitext(resolved_path)[1]
            if not ext:
                ext = ".jpg"
            with open(resolved_path, "rb") as rf:
                file_bytes = rf.read()
            fmd5 = hashlib.md5(file_bytes).hexdigest()[:16]
            dest_name = f"cached_{fmd5}{ext}"
            dest_path = os.path.join(UPLOAD_FOLDER, dest_name)
            if not os.path.exists(dest_path):
                with open(dest_path, "wb") as wf:
                    wf.write(file_bytes)
            return f"/api/chat/media/{dest_name}"
        except Exception as e:
            logger.warning(f"[cache_local_image] ???????? {resolved_path}: {e}")
            return clean_str
    return clean_str

def extract_onebot_text(message):
    """提取 OneBot 文本消息/过滤图片占位符与 CQ 码"""
    if not message:
        return ""
    def _clean(t):
        s = re.sub(r'\[CQ:[^\]]+\]', '', str(t))
        s = re.sub(r'\[图片\]t=[0-9.]*', '', s)
        return s
    if isinstance(message, str):
        return _clean(message).strip()
    if isinstance(message, list):
        texts = []
        for item in message:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    texts.append(_clean(item.get("data", {}).get("text", "")))
            elif isinstance(item, str):
                texts.append(_clean(item))
        return "".join(texts).strip()
    return _clean(str(message)).strip()

def extract_onebot_images(message):
    """提取并缓存 OneBot 消息列表/CQ码中的图片路径为公开可访问URL"""
    images = []
    if not message:
        return images
    img_pattern = r'\[CQ:image,[^\]]*?(?:file|url)=([^,\]]+)'
    if isinstance(message, str):
        for m in re.finditer(img_pattern, message):
            f_val = m.group(1).strip()
            if f_val:
                cached = cache_local_image_for_remote(f_val)
                if cached not in images:
                    images.append(cached)
    elif isinstance(message, list):
        for item in message:
            if isinstance(item, dict) and item.get("type") == "image":
                f_info = item.get("data", {}).get("file") or item.get("data", {}).get("url")
                if f_info:
                    cached_url = cache_local_image_for_remote(f_info)
                    if cached_url not in images:
                        images.append(cached_url)
            elif isinstance(item, str):
                for m in re.finditer(img_pattern, item):
                    f_val = m.group(1).strip()
                    if f_val:
                        cached = cache_local_image_for_remote(f_val)
                        if cached not in images:
                            images.append(cached)
    return images

def get_webui_auth_token():
    """读取 basic_config.yaml 中的 webui.auth_token 鉴权密钥"""
    try:
        cfg_path = os.path.join(os.path.dirname(BASE_DIR), "run", "common_config", "basic_config.yaml")
        if not os.path.exists(cfg_path):
            cfg_path = os.path.join(BASE_DIR, "run", "common_config", "basic_config.yaml")
        if os.path.exists(cfg_path):
            with open(cfg_path, 'r', encoding='utf-8') as f:
                yaml_loader = YAML(typ='safe')
                cfg = yaml_loader.load(f)
                if isinstance(cfg, dict):
                    webui_cfg = cfg.get("webui", {})
                    if isinstance(webui_cfg, dict):
                        return str(webui_cfg.get("auth_token", "")).strip()
    except Exception as e:
        logger.warning(f"[Auth] 读取 WebUI auth_token 异常: {e}")
    return ""

def verify_external_request_auth():
    """
    检查外部请求鉴权：
    1. 若未设置 auth_token，则放行
    2. 若客户端来自本机(127.0.0.1, ::1)，放行
    3. 若外部访问，支持从 Header (X-Auth-Token/Authorization), Query (auth_token/token), 
       或者 JSON Body (auth_token) 中读取 token 并比对。
    """
    configured_token = get_webui_auth_token()
    if not configured_token:
        return True, ""

    client_ip = request.remote_addr or ""
    # 如果没有走反代直接来自本机
    is_local = (client_ip in ['127.0.0.1', '::1', 'localhost'] or client_ip.startswith('127.'))
    # 注意：如果经过了反向代理 (例如 frp/nginx/caddy)，用户可能从外网访问
    # 因此如果有 X-Forwarded-For 且不全是 127.0.0.1，或者外部域名访问，必须严密校验 token
    forwarded_for = request.headers.get("X-Forwarded-For", "").strip()
    if forwarded_for and not all(ip.strip() in ['127.0.0.1', '::1', 'localhost'] for ip in forwarded_for.split(',')):
        is_local = False

    # 获取请求传入的 token
    recv_token = (
        request.headers.get("X-Auth-Token", "") or
        request.headers.get("Authorization", "").replace("Bearer ", "") or
        request.args.get("auth_token", "") or
        request.args.get("token", "")
    ).strip()

    if not recv_token and request.is_json:
        data = request.get_json(silent=True) or {}
        recv_token = str(data.get("auth_token", "")).strip()

    # 检查是否匹配配置的 token
    if recv_token == configured_token:
        return True, ""

    # 检查是否是 WebUI 登录会话中的合法 token
    if recv_token in auth_info and auth_info[recv_token] > int(time.time()):
        return True, ""

    # 如果完全是本地且没有携带外部代理来源，允许本地开发环境访问
    if is_local and not forwarded_for and not recv_token:
        return True, ""

    return False, "鉴权失败：缺少有效或匹配的访问 Token (Invalid Auth Token)"

@app.route("/api/chat/media/<path:filename>", methods=["GET"])
def get_chat_media_file(filename):
    """直接访问 chat_files 中的图片文件，供 Android App 跨设备加载"""
    try:
        return send_from_directory(UPLOAD_FOLDER, filename)
    except Exception as e:
        return jsonify({"error": f"File not found: {e}"}), 404

@app.route("/api/android/status", methods=["GET"])
def android_status():
    """Android App 连通性与状态检查"""
    auth_ok, auth_msg = verify_external_request_auth()
    if not auth_ok:
        return jsonify({
            "status": "error",
            "message": auth_msg
        }), 401

    return jsonify({
        "status": "ok",
        "bot_connected": len(clients) > 0,
        "default_qq_id": 1840094972,
        "active_clients": len(clients)
    })

@app.route("/api/android/history", methods=["GET"])
def android_history():
    """? Android App ?????????????? since_id ????"""
    auth_ok, auth_msg = verify_external_request_auth()
    if not auth_ok:
        return jsonify({
            "status": "error",
            "message": auth_msg
        }), 401

    try:
        limit = int(request.args.get("limit", 50))
        since_id_raw = request.args.get("since_id")
        since_id = None
        if since_id_raw is not None and str(since_id_raw).strip() != "":
            try:
                since_id = int(str(since_id_raw).strip())
            except Exception:
                since_id = None

        rows = asyncio.run(get_android_history_records(since_id=since_id or 0, limit=limit))

        results = []
        for mid, data_str in rows:
            try:
                item_data = json.loads(data_str)
                msg_obj = item_data.get("message")
                role = item_data.get("role", "start")
                is_user = (role == "end")
                time_val = item_data.get("message_id") or mid

                text_content = ""
                images = []

                if isinstance(msg_obj, dict):
                    raw_msg = msg_obj.get("params", {}).get("message", "")
                    text_content = extract_onebot_text(raw_msg)
                    images = extract_onebot_images(raw_msg)
                elif isinstance(msg_obj, list):
                    text_content = extract_onebot_text(msg_obj)
                    images = extract_onebot_images(msg_obj)
                elif isinstance(msg_obj, str):
                    text_content = extract_onebot_text(msg_obj)
                    images = extract_onebot_images(msg_obj)

                if text_content or images:
                    if "||" in text_content and not is_user:
                        parts = [p.strip() for p in text_content.split("||") if p.strip()]
                        for pi, p_seg in enumerate(parts):
                            p_imgs = images if pi == len(parts) - 1 else []
                            results.append({
                                "id": int(time_val) + pi,
                                "raw_msg_id": int(time_val),
                                "text": p_seg,
                                "images": p_imgs,
                                "is_user": False,
                                "time": int(time_val)
                            })
                    else:
                        results.append({
                            "id": int(time_val),
                            "raw_msg_id": int(time_val),
                            "text": text_content,
                            "images": images,
                            "is_user": is_user,
                            "time": int(time_val)
                        })
            except Exception:
                continue

        return jsonify({"status": "ok", "messages": results})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/android/upload", methods=["POST"])
def android_upload_image():
    """供 Android App 上传图片并保存到 chat_files，返回公开访问 URL"""
    auth_ok, auth_msg = verify_external_request_auth()
    if not auth_ok:
        return jsonify({
            "status": "error",
            "message": auth_msg
        }), 401

    try:
        file = request.files.get("file")
        if not file:
            return jsonify({"status": "error", "message": "No file uploaded"}), 400
        ext = os.path.splitext(file.filename)[1] or ".jpg"
        content = file.read()
        fmd5 = hashlib.md5(content).hexdigest()[:16]
        dest_name = f"cached_{fmd5}{ext}"
        dest_path = os.path.join(UPLOAD_FOLDER, dest_name)
        if not os.path.exists(dest_path):
            with open(dest_path, "wb") as wf:
                wf.write(content)
        return jsonify({
            "status": "ok",
            "url": f"/api/chat/media/{dest_name}",
            "filename": dest_name
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/android/ask", methods=["POST"])
def android_ask():
    """Android App 发送/提问接口，与 QQ 上下文记忆打通"""
    auth_ok, auth_msg = verify_external_request_auth()
    if not auth_ok:
        return jsonify({
            "status": "error",
            "message": auth_msg
        }), 401

    data = request.get_json(silent=True) or {}
    text = data.get("text", "").strip()
    image_base64 = data.get("image_base64")
    user_id = data.get("user_id") or 1840094972
    nickname = data.get("nickname") or "主人"
    if nickname in ["Android助理", "Android"]:
        nickname = "主人"
    timeout = float(data.get("timeout") or 60.0)

    try:
        user_id = int(user_id)
    except Exception:
        user_id = 1840094972

    msg_segments = []
    at_bot = data.get("at_bot", True)
    if at_bot:
        msg_segments.append({
            "type": "at",
            "data": {"qq": "1000000", "name": "Eridanus"}
        })

    if image_base64:
        try:
            clean_b64 = image_base64
            if "base64," in clean_b64:
                clean_b64 = clean_b64.split("base64,")[1]
            img_bytes = base64.b64decode(clean_b64)
            img_md5 = hashlib.md5(img_bytes).hexdigest()[:16]
            dest_name = f"cached_{img_md5}.jpg"
            dest_path = os.path.join(UPLOAD_FOLDER, dest_name)
            if not os.path.exists(dest_path):
                with open(dest_path, "wb") as wf:
                    wf.write(img_bytes)
            # 采用标准本地 file:// 协议，让 mai_reply 和视觉模型直接原生加载
            abs_uri = f"file:///{os.path.abspath(dest_path).replace(chr(92), '/')}"
            msg_segments.append({
                "type": "image",
                "data": {"file": abs_uri}
            })
        except Exception as e_b64:
            logger.warning(f"[Android Ask] 保存上传图片失败: {e_b64}")
    if text:
        msg_segments.append({
            "type": "text",
            "data": {"text": text}
        })

    if len(msg_segments) <= (1 if at_bot else 0):
        return jsonify({"status": "error", "message": "Prompt is empty"}), 400

    now_ms = int(time.time() * 1000)
    event_payload = {
        "self_id": 1000000,
        "user_id": user_id,
        "time": int(time.time()),
        "message_id": now_ms,
        "real_id": now_ms % 2147483647,
        "message_seq": now_ms % 2147483647,
        "message_type": "group",
        "sender": {
            "user_id": user_id,
            "nickname": nickname,
            "card": "",
            "role": "member",
            "title": ""
        },
        "raw_message": text,
        "font": 14,
        "sub_type": "normal",
        "message": msg_segments,
        "message_format": "array",
        "post_type": "message",
        "group_id": 222222,  # 虚拟 Android 群号
        "adapter_source": "android"
    }

    # 记录该提问消息至数据库
    try:
        asyncio.run(
            update_msg(
                now_ms, json.dumps({
                    "role": "end",
                    "message_id": now_ms,
                    "message": msg_segments
                }, ensure_ascii=False)
            )
        )
    except Exception as ex:
        logger.warning(f"记录 Android 提问消息失败: {ex}")

    # 等待机器人生成回复的通知事件
    ev = threading.Event()
    android_pending_events[user_id] = ev
    android_pending_responses[user_id] = {"reply": "", "images": [], "msg_id": 0}

    # 广播事件至本地 WebSocket (Eridanus Bot 机器人)
    ev_json = json.dumps(event_payload, ensure_ascii=False)
    for c in list(clients):
        try:
            c.send(ev_json)
        except Exception:
            clients.discard(c)

    # 阻塞等待回复生成
    flag = ev.wait(timeout=timeout)

    if flag:
        # 延时 2.5 秒以确保所有分段消息(|| 分割)接收完整
        time.sleep(2.5)
        android_pending_events.pop(user_id, None)
        reply_info = android_pending_responses.pop(user_id, {"reply": "", "images": [], "msg_id": 0})
        final_reply = reply_info.get("reply", "").strip()
        final_images = reply_info.get("images", [])
        final_msg_id = reply_info.get("msg_id", 0)

        return jsonify({
            "status": "ok",
            "reply": final_reply,
            "images": final_images,
            "msg_id": final_msg_id,
            "message": "success",
            "user_id": user_id
        })
    else:
        android_pending_events.pop(user_id, None)
        android_pending_responses.pop(user_id, None)
        return jsonify({
            "status": "timeout",
            "reply": "(Eridanus 生成回复超时，请检查 Bot 是否已连接到 Hub)",
            "images": [],
            "message": "timeout",
            "user_id": user_id
        }), 504

@sock.route('/api/ws')
def handle_websocket(ws):
    global auth_info
    logger.server("WebSocket 客户端已连接")
    clients.add(ws)
    try:
        # 对来自非本机的外部 WebSocket 连接进行鉴权 (Hub 端口 5007)
        # 本地连接 (127.0.0.1, ::1, localhost 等) 或未设置 token 时自动放行
        client_ip = request.remote_addr or ""
        forwarded_for = request.headers.get("X-Forwarded-For", "").strip()
        is_local = (client_ip in ['127.0.0.1', '::1', 'localhost'] or client_ip.startswith('127.'))
        if forwarded_for and not all(ip.strip() in ['127.0.0.1', '::1', 'localhost'] for ip in forwarded_for.split(',')):
            is_local = False

        configured_token = get_webui_auth_token()
        if not is_local and configured_token:
            recv_token = (request.args.get('auth_token') or request.args.get('token') or "").strip()
            is_valid_session = (recv_token in auth_info and auth_info[recv_token] > int(time.time()))
            if recv_token != configured_token and not is_valid_session:
                logger.warning(f"WebSocket 外部客户端鉴权未通过 - IP: {client_ip}")
                raise ValueError(f"WebSocket 外部客户端鉴权未通过 - IP: {client_ip}")
            logger.server(f"WebSocket 外部客户端鉴权通过 - IP: {client_ip}")
        while True:
            # 接收来自前端的消息
            message = ws.receive()
            # logger.server(f"收到前端消息: {message} {type(message)}")
            message = json.loads(message)

            # 外部适配器（如 TelegramAdapter）对 Action（如 get_msg）的响应帧，直接转发给主程序/请求端
            if isinstance(message, dict) and "status" in message and "echo" in message:
                resp_json = json.dumps(message, ensure_ascii=False)
                for client in list(clients):
                    if client != ws:
                        try:
                            client.send(resp_json)
                        except Exception:
                            clients.discard(client)
                continue

            # 对于不需要适配器返回数据的普通指令，返回虚拟确认；查询类（如 get_msg）由真实适配器响应
            if "echo" in message and message.get("action") != "get_msg":
                for client in list(clients):
                    try:
                        client.send(json.dumps({'status': 'ok',
                                                'retcode': 0,
                                                'data': {'message_id': 1253451396},
                                                'message': '',
                                                'wording': '',
                                                'echo': message['echo']}))
                    except Exception:
                        clients.discard(client)
                        # 获取前端消息的id
            # 统一时间戳
            time_now = int(time.time() * 1000)
            message_id = time_now
            is_update = False
            target_group_id = 879886836
            # 区分消息发起者
            role = 'end'

            # 1. 转发主程序 Eridanus 发出的 Action 指令至所有外部客户端（包括 TG）
            if isinstance(message, dict) and message.get("action") in valid_message_actions:
                target_group_id = message.get("params", {}).get("group_id", 879886836)

                # 捕获发送给 Android 客户端 (group_id == 222222) 的消息
                if target_group_id == 222222 or str(target_group_id) == "222222":
                    try:
                        raw_msg = message.get("params", {}).get("message", "")
                        extracted_text = extract_onebot_text(raw_msg)
                        extracted_images = extract_onebot_images(raw_msg)

                        # 记录历史并唤醒等待的客户端
                        if extracted_text or extracted_images:
                            # 保存到持久化数据库
                            try:
                                asyncio.run(
                                    update_msg(
                                        time_now, json.dumps({
                                            "role": "start",
                                            "message_id": time_now,
                                            "message": message
                                        }, ensure_ascii=False)
                                    )
                                )
                            except Exception as e_db:
                                logger.warning(f"Android 存储消息失败: {e_db}")

                            # 唤醒当前阻塞等待回复的 Android 客户端
                            # 若为多段消息（含 ||），累计拼装给长轮询或即时推送
                            for uid, ev in list(android_pending_events.items()):
                                curr_info = android_pending_responses.get(uid, {"reply": "", "images": []})
                                curr_reply = curr_info.get("reply", "")
                                if curr_reply and extracted_text:
                                    curr_reply = curr_reply + "||" + extracted_text
                                elif extracted_text:
                                    curr_reply = extracted_text

                                curr_imgs = curr_info.get("images", [])
                                for img in extracted_images:
                                    if img not in curr_imgs:
                                        curr_imgs.append(img)

                                android_pending_responses[uid] = {
                                    "reply": curr_reply,
                                    "images": curr_imgs,
                                    "msg_id": time_now
                                }
                                ev.set()
                    except Exception as e_resp:
                        logger.warning(f"处理 Android 响应失败: {e_resp}")
                action_json = json.dumps(message, ensure_ascii=False)
                # 广播给除发送端外的其它客户端（如 TelegramAdapter）
                for client in list(clients):
                    if client != ws:
                        try:
                            client.send(action_json)
                        except Exception:
                            clients.discard(client)

                # 如果是 WebUI 的本地群，则持久化消息（排除查询动作如 get_msg）
                if target_group_id == 879886836 and message.get("action") != "get_msg":
                    is_update = True
                    message_id = time_now
                    role = 'start'
                    try:
                        asyncio.run(
                            update_msg(
                                time_now, json.dumps({
                                    "role": role,
                                    "message_id": message_id,
                                    "message": message
                                })
                            )
                        )
                    except Exception as ex:
                        logger.warning(f"消息记录更新失败: {ex}")

            # 2. 如果收到的是外部适配器（如 TelegramAdapter）发来的 OneBot Event 事件，广播给主程序及 WebUI
            elif isinstance(message, dict) and "post_type" in message:
                event_json = json.dumps(message, ensure_ascii=False)
                for client in list(clients):
                    if client != ws:
                        try:
                            client.send(event_json)
                        except Exception:
                            clients.discard(client)

            # 3. 原始 WebUI 前端发送的 Array 格式消息，包装为标准 OneBot v11 Group 消息并注入
            elif isinstance(message, list):
                is_update = True
                message_id = time_now
                if message and isinstance(message[0], dict) and "msg_id" in message[0] and "type" not in message[0]:
                    message_id = message[0]["msg_id"]
                    del message[0]
                role = 'end'
                try:
                    asyncio.run(
                        update_msg(
                            time_now, json.dumps({
                                "role": role,
                                "message_id": message_id,
                                "message": message
                            })
                        )
                    )
                except Exception as ex:
                    logger.warning(f"消息记录更新失败: {ex}")

                onebot_event = {
                    'self_id': 1000000,
                    'user_id': 111111111,
                    'time': time_now,
                    'message_id': message_id,
                    'real_id': 1253451396,
                    'message_seq': 1253451396,
                    'message_type': 'group',
                    'sender': {
                        'user_id': 111111111,
                        'nickname': '主人',
                        'card': '',
                        'role': 'member',
                        'title': ''
                    },
                    'raw_message': "",
                    'font': 14,
                    'sub_type': 'normal',
                    'message': message,
                    'message_format': 'array',
                    'post_type': 'message',
                    'group_id': 879886836,
                    'adapter_source': 'webui'
                }

                event_json = json.dumps(onebot_event, ensure_ascii=False)
                for client in list(clients):
                    try:
                        if client != ws:
                            client.send(event_json)
                    except Exception:
                        clients.discard(client)
    except Exception as e:
        logger.server(f"WebSocket事件: {str(e)}")
        # traceback.print_exc()
    finally:
        # 总有人看见红色就害怕，干脆不要了，不搞这么多提示
        # logger.server("WebSocket 客户端断开连接")
        clients.discard(ws)


# Live2D 网页版桌宠（/live2dchat）：路由与逻辑都在 run/live2d，这里只做注册，
# 便于 web/ 更新后存活。webui_enable 关闭/插件未加载时，/live2dchat/config 会返回未启用。
try:
    from run.live2d.webchat import register_live2d_webchat
    register_live2d_webchat(app)
    logger.server("🔧 Live2D 网页版路由已注册：/live2dchat（需 live2d 配置 webui_enable: true）")
except Exception as e:
    logger.warning(f"Live2D /live2dchat 注册失败（不影响 WebUI）：{e}")


# 启动webUI
def start_webui():
    # 初始化用户登录信息
    try:
        with open(user_file, 'r', encoding="utf-8") as file:
            yaml_file = yaml.load(file)
            user_info['account'] = yaml_file['account']
            user_info['password'] = yaml_file['password']
            user_info['friends'] = yaml_file['friends']
            user_info['groups'] = yaml_file['groups']
        logger.server("登录信息读取成功。初始用户名和密码均为 eridanus ")
        logger.server("请访问 http://localhost:5007 登录")
        logger.server("请访问 http://localhost:5007 登录")
        logger.server("请访问 http://localhost:5007 登录")
    except:
        logger.warning("登录信息读取失败，已恢复默认。默认用户名/密码：eridanus")
        with open(user_file, 'w', encoding="utf-8") as file:
            yaml.dump(user_info, file)

    app.run(host="0.0.0.0", port=5007,threaded=True)
# 启动Eridanus并捕获输出，反馈到前端。
# 不会写，不写！