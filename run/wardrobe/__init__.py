# -*- coding: utf-8 -*-
"""
Wardrobe Module (衣橱系统)
"""

plugin_description = "衣橱系统"

try:
    from run.wardrobe.wardrobe_manager import (
        WardrobeManager,
        get_wardrobe_manager,
        call_change_outfit,
        build_change_outfit_declaration,
        get_function_declarations
    )
except Exception:
    try:
        from .wardrobe_manager import (
            WardrobeManager,
            get_wardrobe_manager,
            call_change_outfit,
            build_change_outfit_declaration,
            get_function_declarations
        )
    except Exception:
        WardrobeManager = None
        get_wardrobe_manager = None
        call_change_outfit = None
        build_change_outfit_declaration = None
        get_function_declarations = None

dynamic_imports = {
    "run.wardrobe.wardrobe_manager": [
        "call_change_outfit",
    ]
}

# 启动时根据 config.yaml 动态构建 function_declarations，无须硬编码冗长列表，并支持运行时热重载
if build_change_outfit_declaration:
    function_declarations = [build_change_outfit_declaration()]
else:
    function_declarations = []


def refresh_function_declarations(plugin_name=None):
    """Keep the declaration object already collected by the framework up to date."""
    if plugin_name not in (None, "wardrobe") or not build_change_outfit_declaration:
        return
    updated = build_change_outfit_declaration()
    if function_declarations:
        function_declarations[0].clear()
        function_declarations[0].update(updated)
    else:
        function_declarations.append(updated)


# Use the framework's existing reload hook; all refresh behavior belongs to this plugin.
if WardrobeManager:
    from .wardrobe_manager import YAMLManager
    if YAMLManager is not None:
        _yaml_manager = YAMLManager.get_instance()
        if _yaml_manager is not None:
            _yaml_manager.register_reload_callback(refresh_function_declarations)

__all__ = [
    "WardrobeManager",
    "get_wardrobe_manager",
    "call_change_outfit",
    "build_change_outfit_declaration",
    "get_function_declarations",
    "plugin_description",
    "dynamic_imports",
    "function_declarations"
]
