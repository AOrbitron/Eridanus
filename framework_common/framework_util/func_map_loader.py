import os
import sys
import importlib
import traceback


from developTools.utils.logger import get_logger

logger=get_logger()
print(logger)
PLUGIN_DIR = "run"
dynamic_imports = {}
all_function_declarations = []  # 存储所有插件的 function_declarations

# 遍历 run 目录及子目录，查找 `__init__.py`
for root, dirs, files in os.walk(PLUGIN_DIR):
    if "__init__.py" in files:
        module_name = root.replace(os.sep, ".")  # 转换为 Python 模块名
        try:
            module = importlib.import_module(module_name)  # 导入模块

            # 加载 dynamic_imports
            if hasattr(module, "dynamic_imports"):
                if isinstance(module.dynamic_imports, dict):
                    # 旧格式：字典
                    dynamic_imports.update(module.dynamic_imports)
                    #logger.info(f"✅ 发现并加载 {module_name}.dynamic_imports (字典格式)")
                elif isinstance(module.dynamic_imports, list):
                    # 新格式：函数对象列表
                    func_names = [func.__name__ for func in module.dynamic_imports if callable(func)]
                    dynamic_imports[module_name] = func_names
                    #logger.info(f"✅ 发现并加载 {module_name}.dynamic_imports (列表格式)")
                else:
                    logger.warning(f"⚠️ {module_name}.dynamic_imports 格式不正确")

            # 加载 function_declarations
            if hasattr(module, "function_declarations"):
                if isinstance(module.function_declarations, list):
                    all_function_declarations.extend(module.function_declarations)
                    #logger.info(f"✅ 发现并加载 {module_name}.function_declarations ({len(module.function_declarations)} 个)")

        except Exception as e:
            logger.error(f"❌ 无法导入 {module_name}: {e}")
            traceback.print_exc()
            continue

def rescan():
    """重新扫描 run/*，重建 dynamic_imports 与 all_function_declarations。

    func_map 在模块导入时构建一次；当运行期新增/修改了带 tool 的插件（如 ai_code_generator
    生成的 tool），调用本函数即可让新 tool 进入 build_tool_map()/get_tool_declarations()。
    对新增/改动的模块做 importlib.reload，保证读到磁盘上的最新 dynamic_imports/function_declarations。
    """
    dynamic_imports.clear()
    all_function_declarations.clear()

    for root, dirs, files in os.walk(PLUGIN_DIR):
        if "__init__.py" not in files:
            continue
        module_name = root.replace(os.sep, ".")
        try:
            if module_name in sys.modules:
                module = importlib.reload(sys.modules[module_name])
            else:
                module = importlib.import_module(module_name)

            if hasattr(module, "dynamic_imports"):
                if isinstance(module.dynamic_imports, dict):
                    dynamic_imports.update(module.dynamic_imports)
                elif isinstance(module.dynamic_imports, list):
                    func_names = [f.__name__ for f in module.dynamic_imports if callable(f)]
                    dynamic_imports[module_name] = func_names

            if hasattr(module, "function_declarations") and isinstance(module.function_declarations, list):
                all_function_declarations.extend(module.function_declarations)
        except Exception as e:
            logger.error(f"❌ rescan 无法导入 {module_name}: {e}")
            traceback.print_exc()
            continue

    logger.info(f"[func_map] rescan 完成：{len(dynamic_imports)} 个模块，{len(all_function_declarations)} 条声明")
    return len(all_function_declarations)


def build_tool_map():
    tools = {}
    for module_name, imports in dynamic_imports.items():
        try:
            if isinstance(imports, list):
                try:
                    module = importlib.import_module(module_name)
                    for func_name in imports:
                        if isinstance(func_name, str):
                            if hasattr(module, func_name):
                                func = getattr(module, func_name)
                                if callable(func):
                                    tools[func_name] = func
                                    #logger.info(f"✅ 成功加载 {module_name}.{func_name}")
                                else:
                                    logger.warning(f"⚠️ {module_name}.{func_name} 不是可调用对象")
                            else:
                                logger.warning(f"⚠️ {module_name} 中不存在 {func_name}")
                        elif callable(func_name):
                            tools[func_name.__name__] = func_name
                            #logger.info(f"✅ 成功加载 {module_name}.{func_name.__name__}")
                        else:
                            logger.warning(f"⚠️ {module_name} 中的 {func_name} 既不是字符串也不是可调用对象")
                except Exception as e:
                    logger.error(f"❌ 无法导入模块 {module_name}: {e}")
                    traceback.print_exc()
            else:
                logger.warning(f"⚠️ {module_name} 的 dynamic_imports 格式不正确: {type(imports)}")
        except Exception as e:
            logger.error(f"❌ 处理模块 {module_name} 时出错: {e}")
            traceback.print_exc()

    return tools


NETWORK_SEARCH_FUNCTIONS = {"search_net", "read_html"}
OFFICIAL_SEARCH_FUNCTIONS = {"search_with_official_api"}


def build_tool_fixed_params(bot=None, event=None, config=None):
    """统一的工具固定参数（供新 client 的 tool_fixed_params 使用）"""
    fixed = {}
    if bot is not None:
        fixed["bot"] = bot
    if event is not None:
        fixed["event"] = event
    if config is not None:
        fixed["config"] = config
    return {"all": fixed}


def get_tool_declarations(config=None):
    declarations = all_function_declarations
    
    # 如果开启了官方搜索功能，过滤掉自定义联网函数
    if config is not None:
        try:
            google_search_enabled = config.ai_llm.config["llm"].get("google_search", False)
            url_context_enabled = config.ai_llm.config["llm"].get("url_context", False)
            
            if google_search_enabled or url_context_enabled:
                declarations = [
                    decl for decl in declarations 
                    if decl.get("name") not in NETWORK_SEARCH_FUNCTIONS
                ]
                logger.info(f"已过滤联网相关函数 {NETWORK_SEARCH_FUNCTIONS}，因为官方搜索功能已开启")
            else:
                declarations = [
                    decl for decl in declarations 
                    if decl.get("name") not in OFFICIAL_SEARCH_FUNCTIONS
                ]
        except Exception as e:
            logger.warning(f"检查搜索配置时出错: {e}")
    
    return declarations


def filter_tools_by_config(tools, config=None):
    if config is None:
        return tools
    
    try:
        google_search_enabled = config.ai_llm.config["llm"].get("google_search", False)
        url_context_enabled = config.ai_llm.config["llm"].get("url_context", False)
        
        if google_search_enabled or url_context_enabled:
            filtered_tools = {
                name: func for name, func in tools.items() 
                if name not in NETWORK_SEARCH_FUNCTIONS
            }
            logger.info(f"已从 tools 中过滤联网相关函数 {NETWORK_SEARCH_FUNCTIONS}")
            return filtered_tools
        else:
            filtered_tools = {
                name: func for name, func in tools.items() 
                if name not in OFFICIAL_SEARCH_FUNCTIONS
            }
            return filtered_tools
    except Exception as e:
        logger.warning(f"过滤工具时检查配置出错: {e}")
    
    return tools
