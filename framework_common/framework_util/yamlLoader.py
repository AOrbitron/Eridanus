import os
from ruamel.yaml import YAML
from typing import Any, Callable, List
from concurrent.futures import ThreadPoolExecutor
import threading
import time

from framework_common.utils.install_and_import import install_and_import

watchdog = install_and_import("watchdog")
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from framework_common.utils.system_logger import get_logger

logger = get_logger("YAMLManager")


class YAMLFileHandler(FileSystemEventHandler):
    def __init__(self, yaml_manager):
        self.yaml_manager = yaml_manager
        self.pending_reloads = {}  # 待处理的重载任务
        self.debounce_delay = 0.3  # 防抖延迟时间（秒）
        self.lock = threading.Lock()
        super().__init__()

    def on_modified(self, event):
        if event.is_directory:
            return

        file_path = event.src_path
        if file_path.endswith(('.yaml', '.yml')):
            self._schedule_reload(file_path)

    def _schedule_reload(self, file_path):
        """调度文件重载，使用定时器防抖"""
        with self.lock:
            if file_path in self.pending_reloads:
                self.pending_reloads[file_path].cancel()

            timer = threading.Timer(self.debounce_delay, self._execute_reload, args=[file_path])
            self.pending_reloads[file_path] = timer
            timer.start()

    def _execute_reload(self, file_path):
        """执行实际的文件重载"""
        with self.lock:
            # 清理已完成的任务
            if file_path in self.pending_reloads:
                del self.pending_reloads[file_path]

        # 执行重载
        self.yaml_manager.reload_file(file_path)


class PluginConfig:
    def __init__(self, name, data, file_paths, save_func):
        self._data = data
        self._file_paths = file_paths
        self._name = name
        self._save_func = save_func

    def __getattr__(self, config_name):
        if config_name in ["_data", "_file_paths", "_save_func", "_name"]:
            return self.__getattribute__(config_name)
        if config_name in self._data:
            return self._data[config_name]
        raise AttributeError(f"Plugin {self._name} has no config '{config_name}'.")

    def __setattr__(self, config_name, value):
        if config_name in ["_data", "_file_paths", "_save_func", "_name"]:
            super().__setattr__(config_name, value)
        elif config_name in self._data:
            self._data[config_name] = value
            self._save_func(config_name, self._name)
        else:
            raise AttributeError(f"Plugin {self._name} has no config '{config_name}'.")


class YAMLManager:
    _instance = None
    _lock = threading.Lock()

    def __init__(self, plugins_dir=None):
        """
        初始化 YAML 管理器，自动并行加载 run 目录下及各插件文件夹中的 YAML 文件。
        """
        self.yaml = YAML()
        self.yaml.preserve_quotes = True
        self.yaml.allow_duplicate_keys = True

        self.data = {}
        self.file_paths = {}
        self.path_to_key = {}  # 文件路径到配置键的映射
        self._reload_callbacks: List[Callable[[str], None]] = []  # 文件重载回调列表

        # 设置监控目录
        self.run_dir = os.path.join(os.getcwd(), plugins_dir or "run")
        if not os.path.exists(self.run_dir):
            raise FileNotFoundError(f"Run directory {self.run_dir} not found.")

        # 初始加载所有文件
        from framework_common.framework_util.config_migrations import migrate_plugin_configs
        migrate_plugin_configs(self.run_dir, logger)
        self._load_all_files()

        # 启动文件监控
        self._start_file_watcher()

        YAMLManager._instance = self

    def register_reload_callback(self, callback: Callable[[str], None]):
        """
        注册一个在 YAML 文件重载完成后触发的回调。
        callback 接收一个参数：plugin_name (str)，根目录文件为 None。
        """
        self._reload_callbacks.append(callback)

    def _load_all_files(self):
        """加载所有YAML文件"""
        yaml_files = []

        # 收集所有YAML文件
        for item in os.listdir(self.run_dir):
            item_path = os.path.join(self.run_dir, item)
            # Ignore legacy YAML restored by older updaters after a rename.
            if item == "mai_reply" and os.path.isdir(os.path.join(self.run_dir, "core_reply")):
                continue

            if os.path.isdir(item_path):
                # 插件文件夹
                for file_name in os.listdir(item_path):
                    if file_name.endswith((".yaml", ".yml")):
                        file_path = os.path.join(item_path, file_name)
                        config_name = os.path.splitext(file_name)[0]
                        yaml_files.append((item, config_name, file_path))
            elif item.endswith((".yaml", ".yml")):
                # 根目录下的YAML文件
                file_path = item_path
                config_name = os.path.splitext(item)[0]
                yaml_files.append((None, config_name, file_path))

        # 并行加载
        def load_yaml_file(args):
            plugin_name, config_name, file_path = args
            yaml_instance = YAML()
            yaml_instance.preserve_quotes = True
            yaml_instance.allow_duplicate_keys = True

            try:
                with open(file_path, 'r', encoding='utf-8') as file:
                    return plugin_name, config_name, file_path, yaml_instance.load(file)
            except Exception as e:
                logger.info(f"Error loading {file_path}: {e}")
                return plugin_name, config_name, file_path, {}

        with ThreadPoolExecutor() as executor:
            for plugin_name, config_name, file_path, data in executor.map(load_yaml_file, yaml_files):
                self._store_config(plugin_name, config_name, file_path, data)

    def _store_config(self, plugin_name, config_name, file_path, data):
        """存储配置数据"""
        if plugin_name is None:
            # 根目录文件
            self.data[config_name] = data
            self.file_paths[config_name] = file_path
            self.path_to_key[file_path] = (None, config_name)
        else:
            # 插件文件夹中的文件
            if plugin_name not in self.data:
                self.data[plugin_name] = {}
                self.file_paths[plugin_name] = {}

            self.data[plugin_name][config_name] = data
            self.file_paths[plugin_name][config_name] = file_path
            self.path_to_key[file_path] = (plugin_name, config_name)

    def _start_file_watcher(self):
        """启动文件监控"""
        self.event_handler = YAMLFileHandler(self)
        self.observer = Observer()
        self.observer.schedule(self.event_handler, self.run_dir, recursive=True)
        self.observer.start()

    def _update_with_override(self, old_data, new_data):
        """
        用新数据完全覆盖旧数据，保持对象引用和注释

        :param old_data: 原始数据对象（要保持引用）
        :param new_data: 新加载的数据
        """
        from ruamel.yaml.comments import CommentedMap

        if not isinstance(old_data, (dict, CommentedMap)) or not isinstance(new_data, (dict, CommentedMap)):
            return new_data

        # 清空old_data但保持对象引用
        old_data.clear()

        # 将新数据复制到old_data
        for key, value in new_data.items():
            old_data[key] = value

        # 保留注释信息
        if isinstance(new_data, CommentedMap) and hasattr(new_data, 'ca'):
            if not hasattr(old_data, 'ca'):
                old_data.ca = type(new_data.ca)()

            for attr_name in dir(new_data.ca):
                if not attr_name.startswith('_'):
                    try:
                        attr_value = getattr(new_data.ca, attr_name)
                        if not callable(attr_value):
                            setattr(old_data.ca, attr_name, attr_value)
                    except:
                        pass

    def reload_file(self, file_path):
        """重新加载单个文件，用新数据完全覆盖旧数据"""
        if file_path not in self.path_to_key:
            return

        plugin_name, config_name = self.path_to_key[file_path]

        try:
            # 创建新的YAML实例以保持注释
            yaml_loader = YAML()
            yaml_loader.preserve_quotes = True
            yaml_loader.indent(mapping=2, sequence=4, offset=2)
            yaml_loader.allow_duplicate_keys = True
            yaml_loader.width = 4096

            with open(file_path, 'r', encoding='utf-8') as file:
                new_data = yaml_loader.load(file)

            if plugin_name is None:
                # 根目录文件
                old_data = self.data[config_name]
                if isinstance(old_data, dict) and isinstance(new_data, dict):
                    self._update_with_override(old_data, new_data)
                else:
                    self.data[config_name] = new_data
            else:
                # 插件配置
                old_data = self.data[plugin_name][config_name]
                if isinstance(old_data, dict) and isinstance(new_data, dict):
                    self._update_with_override(old_data, new_data)
                else:
                    self.data[plugin_name][config_name] = new_data

            logger.info(f"文件重新加载完成: {file_path}")

            # 触发已注册的回调，通知对应的插件名
            if plugin_name:
                for cb in self._reload_callbacks:
                    try:
                        cb(plugin_name)
                    except Exception as e:
                        logger.error(f"reload callback 执行出错 (plugin={plugin_name}): {e}")

        except Exception as e:
            logger.error(f"重新加载文件时出错 {file_path}: {e}")
            import traceback
            traceback.print_exc()

    def stop_watching(self):
        """停止文件监控"""
        if hasattr(self, 'observer'):
            self.observer.stop()
            self.observer.join()

    @staticmethod
    def get_instance() -> 'YAMLManager':
        """获取已创建的 YAMLManager 实例（线程安全）"""
        with YAMLManager._lock:
            if YAMLManager._instance is None:
                YAMLManager._instance = YAMLManager()
            return YAMLManager._instance

    def save_yaml(self, config_name: str, plugin_name: str = None):
        """保存某个 YAML 数据到文件"""
        if plugin_name is None:
            if config_name not in self.file_paths:
                raise ValueError(f"YAML file {config_name} not managed by YAMLManager.")
            file_path = self.file_paths[config_name]
            data = self.data[config_name]
        else:
            if plugin_name not in self.file_paths or config_name not in self.file_paths[plugin_name]:
                raise ValueError(f"YAML file {config_name} in plugin {plugin_name} not managed by YAMLManager.")
            file_path = self.file_paths[plugin_name][config_name]
            data = self.data[plugin_name][config_name]

        with open(file_path, 'w', encoding='utf-8') as file:
            self.yaml.dump(data, file)

    def __getattr__(self, name: str):
        """允许通过属性访问插件或直接 YAML 数据"""
        if name in self.data:
            if isinstance(self.data[name], dict) and name in self.file_paths and isinstance(self.file_paths[name],
                                                                                            dict):
                # 插件文件夹
                return PluginConfig(name, self.data[name], self.file_paths[name], self.save_yaml)
            else:
                # 直接在 run 目录下的 YAML 文件
                return self.data[name]
        raise AttributeError(f"YAMLManager has no plugin or config '{name}'.")

    def __setattr__(self, name: str, value: Any):
        """允许通过属性修改 YAML 数据"""
        if name in ["yaml", "data", "file_paths", "path_to_key", "run_dir", "event_handler", "observer", "_instance",
                    "_lock", "_reload_callbacks"]:
            super().__setattr__(name, value)
        elif hasattr(self, 'data') and name in self.data and not isinstance(self.data[name], dict):
            self.data[name] = value
            self.save_yaml(name)
        else:
            if hasattr(self, 'data'):
                raise AttributeError(f"YAMLManager cannot set attribute '{name}' directly.")
            super().__setattr__(name, value)

    def __del__(self):
        """析构函数，停止文件监控"""
        self.stop_watching()


# 测试示例
if __name__ == "__main__":
    import tempfile

    config = YAMLManager()
    print(config.ai_llm.config, type(config.ai_llm.config))
