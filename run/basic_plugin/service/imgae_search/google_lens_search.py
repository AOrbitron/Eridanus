import asyncio
import json
import logging
import os
import shutil
import subprocess
from typing import Any, Dict, List, Optional

logger = logging.getLogger('google_lens_search')

DEFAULT_LENS_BIN_PATHS = [
    os.path.join(os.path.dirname(__file__), 'google_lens_search', 'bin', 'lens_cli.mjs'),
]

def find_node_executable() -> Optional[str]:
    """跨平台检索 Node.js 可执行文件路径。优先检查 PATH，其次检查环境变量及宿主机/容器常见安装路径。"""
    node_cmd = shutil.which('node')
    if node_cmd and os.path.exists(node_cmd):
        return os.path.abspath(node_cmd)

    for env_key in ('NODE_PATH', 'NODE_EXE', 'NODE_BIN', 'NODE'):
        v = os.environ.get(env_key)
        if v and os.path.exists(v):
            return os.path.abspath(v)

    import glob
    candidates = [
        '/usr/bin/node',
        '/usr/local/bin/node',
        '/bin/node',
        '/usr/sbin/node',
        '/opt/node/bin/node',
        os.path.expanduser('~/.nvm/versions/node/*/bin/node'),
        '/root/.nvm/versions/node/*/bin/node',
        r'C:\Program Files\nodejs\node.exe',
        r'C:\Program Files (x86)\nodejs\node.exe',
        os.path.expanduser(r'~\AppData\Roaming\nvm\nodejs\node.exe'),
        os.path.expanduser(r'~\AppData\Local\Programs\node\node.exe'),
    ]

    for pat in candidates:
        for match in glob.glob(pat):
            if os.path.isfile(match) and os.access(match, os.X_OK | os.R_OK):
                return os.path.abspath(match)
    return None


def get_configured_proxy() -> Optional[str]:
    """通过项目的 YAMLManager 从 run/common_config/basic_config.yaml 中读取代理配置"""
    try:
        from framework_common.framework_util.yamlLoader import YAMLManager
        mgr = YAMLManager.get_instance()
        basic_cfg = None
        if hasattr(mgr, 'common_config') and hasattr(mgr.common_config, 'basic_config'):
            basic_cfg = mgr.common_config.basic_config
        elif hasattr(mgr, 'data'):
            basic_cfg = mgr.data.get('common_config', {}).get('basic_config', {})

        if isinstance(basic_cfg, dict):
            proxy_cfg = basic_cfg.get('proxy', {}) or {}
            if isinstance(proxy_cfg, dict):
                http_p = proxy_cfg.get('http_proxy')
                if http_p and str(http_p).strip():
                    return str(http_p).strip()
                socks_p = proxy_cfg.get('socks_proxy')
                if socks_p and str(socks_p).strip():
                    return str(socks_p).strip()
            elif isinstance(proxy_cfg, str) and proxy_cfg.strip():
                return proxy_cfg.strip()
    except Exception:
        pass

    try:
        cfg_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'common_config', 'basic_config.yaml'))
        if os.path.exists(cfg_path):
            import yaml
            with open(cfg_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict):
                proxy_cfg = data.get('proxy', {}) or {}
                if isinstance(proxy_cfg, dict):
                    http_p = proxy_cfg.get('http_proxy')
                    if http_p and str(http_p).strip():
                        return str(http_p).strip()
                    socks_p = proxy_cfg.get('socks_proxy')
                    if socks_p and str(socks_p).strip():
                        return str(socks_p).strip()
                elif isinstance(proxy_cfg, str) and proxy_cfg.strip():
                    return proxy_cfg.strip()
    except Exception:
        pass

    for k in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy'):
        v = os.environ.get(k)
        if v and str(v).strip():
            return str(v).strip()
    return None

def find_lens_script_path() -> Optional[str]:
    custom_path = os.environ.get('GOOGLE_LENS_SEARCH_PATH') or os.environ.get('GOOGLE_LENS_PATH')
    if custom_path and os.path.exists(custom_path):
        return os.path.abspath(custom_path)
    for p in DEFAULT_LENS_BIN_PATHS:
        if os.path.exists(p):
            return os.path.abspath(p)
    return None

async def search_google_lens(
    image_path: str,
    proxy: Optional[str] = None,
    engines: Optional[str] = None,
    timeout: int = 75,
    strict: bool = True,
    max_accounts: int = 5,
    browser_exe: Optional[str] = None,
) -> Dict[str, Any]:
    if not image_path or not os.path.exists(image_path):
        return {'status': 'error', 'message': f'本地图片不存在: {image_path}', 'accounts': []}

    lens_bin = find_lens_script_path()
    if not lens_bin:
        return {'status': 'error', 'message': '未找到 Google Lens 核心脚本，请确认安装路径', 'accounts': []}

    node_cmd = find_node_executable()
    if not node_cmd:
        return {'status': 'error', 'message': '未检测到 Node.js 环境，请先安装 Node.js (推荐 v18/v20+) 并加入环境变量 PATH', 'accounts': []}

    cmd = [
        node_cmd,
        lens_bin,
        os.path.abspath(image_path),
        '--json',
        '--max',
        str(max_accounts),
        '--timeout',
        str(timeout),
    ]

    if engines:
        eng_list = [('lens' if e.strip() == 'google_lens' else e.strip()) for e in str(engines).split(',') if e.strip()]
        if eng_list:
            cmd.extend(['--engines', ','.join(eng_list)])
    else:
        cmd.extend(['--engines', 'lens,saucenao,tracemoe'])
    if not strict:
        cmd.append('--no-strict')
    effective_proxy = str(proxy).strip() if (proxy and str(proxy).strip()) else get_configured_proxy()
    if effective_proxy:
        cmd.extend(['--proxy', effective_proxy])
    if browser_exe and os.path.exists(browser_exe):
        cmd.extend(['--browser', os.path.abspath(browser_exe)])

    # 将代理同步注入子进程环境，以便 Node.js 原生 fetch 及各网络库生效
    sub_env = dict(os.environ)
    if effective_proxy:
        sub_env['HTTP_PROXY'] = effective_proxy
        sub_env['HTTPS_PROXY'] = effective_proxy
        sub_env['ALL_PROXY'] = effective_proxy
        sub_env['http_proxy'] = effective_proxy
        sub_env['https_proxy'] = effective_proxy
        sub_env['all_proxy'] = effective_proxy

    def _sync_exec() -> subprocess.CompletedProcess:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            env=sub_env,
            timeout=timeout + 30,
        )

    try:
        # 使用 asyncio.to_thread 兼容 Windows 下任何 EventLoopPolicy (如 SelectorEventLoopPolicy)
        completed = await asyncio.to_thread(_sync_exec)
        out_str = completed.stdout.strip()
        err_str = completed.stderr.strip()

        if completed.returncode != 0 and not out_str:
            logger.warning(f'Google Lens 进程退出异常 {completed.returncode}: {err_str}')
            return {'status': 'error', 'message': f'Google Lens 执行失败 (code {completed.returncode}): {err_str}', 'accounts': []}

        json_start = out_str.find('{')
        json_end = out_str.rfind('}')
        if json_start != -1 and json_end != -1 and json_end > json_start:
            payload = json.loads(out_str[json_start : json_end + 1])
            accounts = payload.get('accounts', [])
            return {
                'status': 'success',
                'accounts': accounts,
                'web_results': payload.get('webResults', []),
                'text': payload.get('text', ''),
                'engines_used': payload.get('enginesUsed', []),
                'failures': payload.get('failures', []),
                'elapsed_ms': payload.get('elapsedMs', 0),
            }

        return {'status': 'error', 'message': f'解析返回结果失败: {out_str or err_str}', 'accounts': []}

    except subprocess.TimeoutExpired:
        return {'status': 'error', 'message': f'Google Lens 检索超时 ({timeout}s)', 'accounts': []}
    except Exception as e:
        err_msg = str(e) or repr(e)
        logger.error(f'执行 Google Lens 检索异常: {err_msg}')
        return {'status': 'error', 'message': err_msg, 'accounts': []}
