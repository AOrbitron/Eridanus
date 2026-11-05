"""One-time plugin configuration migrations, run before YAMLManager loads files.

Keep update-script imports out of this module: tool.py has interactive side effects.
"""

from copy import deepcopy
from pathlib import Path
import os
import tempfile

from ruamel.yaml import YAML


CORE_REPLY_MIGRATION_FLAG = "legacy_mai_reply_migrated"
WARDROBE_LEGACY_KEYS = ("outfits_v4", "outfits_v3", "outfits_v2", "outfits")


def _value_kind(value):
    # ruamel adds scalar subclasses for quoting/formatting. Compare YAML types,
    # while keeping bool distinct from int (Python's bool subclasses int).
    for kind in (dict, list, bool, str, int, float):
        if isinstance(value, kind):
            return kind
    return type(value)


def merge_config_values(template, previous):
    """Merge only keys present in the new schema and with the same YAML type.

    Mappings recurse to retain new defaults. Scalars and whole lists use the old
    value, including empty lists; removed keys and changed types are discarded.
    """
    for key, value in previous.items():
        if key not in template or _value_kind(template[key]) is not _value_kind(value):
            continue
        if isinstance(template[key], dict):
            merge_config_values(template[key], value)
        else:
            template[key] = deepcopy(value)
    return template


def _load_mapping(path):
    yaml = YAML()
    yaml.preserve_quotes = True
    with path.open(encoding="utf-8") as stream:
        data = yaml.load(stream)
    if not isinstance(data, dict):
        raise ValueError(f"Expected a YAML mapping: {path}")
    return data


def _atomic_save(path, data):
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.width = 4096
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            yaml.dump(data, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _legacy_source(run_dir, filename):
    # Exact layout produced by tool.clean_and_backup_file; do not scan arbitrary
    # temp files, whose age and ownership cannot be established.
    candidates = (
        run_dir.parent / "temp" / "yaml_backup" / f"run__mai_reply__{filename}",
        run_dir / "mai_reply" / filename,
    )
    return next((path for path in candidates if path.is_file()), None)


def _migrate_core_reply(run_dir, logger):
    target = run_dir / "core_reply" / "config.yaml"
    if not target.is_file():
        return
    config = _load_mapping(target)
    # Missing is deliberately not false: only the shipped opt-in marker triggers
    # the migration, and a completed migration never reads legacy files again.
    if config.get(CORE_REPLY_MIGRATION_FLAG) is not False:
        return

    pending = []
    sources = []
    for filename in ("config.yaml", "rag.yaml", "proactive.yaml"):
        destination = target.parent / filename
        source = _legacy_source(run_dir, filename)
        if source is None or not destination.is_file():
            continue
        current = config if filename == "config.yaml" else _load_mapping(destination)
        merge_config_values(current, _load_mapping(source))
        sources.append(str(source))
        if filename != "config.yaml":
            pending.append((destination, current))

    # Parse and merge everything before writing. Save the completion marker last;
    # interrupted/failed writes can safely retry the idempotent merge next time.
    for destination, current in pending:
        _atomic_save(destination, current)
    config[CORE_REPLY_MIGRATION_FLAG] = True
    _atomic_save(target, config)
    if sources:
        logger.warning(
            "mai_reply -> core_reply: 已合并旧用户配置，建议重启一次。迁移已完成，"
            "以后不再读取旧备份；源文件保持不变。来源: " + ", ".join(sources)
        )


def _migrate_wardrobe(run_dir, logger):
    target = run_dir / "wardrobe" / "config.yaml"
    if not target.is_file():
        return
    config = _load_mapping(target)
    if not isinstance(config, dict):
        return

    has_legacy = any(k in config for k in WARDROBE_LEGACY_KEYS)
    if not has_legacy:
        return

    if "outfits_v5" not in config or not isinstance(config["outfits_v5"], dict):
        config["outfits_v5"] = {}

    v5 = config["outfits_v5"]
    migrated_custom = []

    for legacy_key in WARDROBE_LEGACY_KEYS:
        legacy_data = config.get(legacy_key)
        if isinstance(legacy_data, dict):
            for name, outfit_val in legacy_data.items():
                if name not in v5:
                    v5[name] = deepcopy(outfit_val)
                    migrated_custom.append(name)
        config.pop(legacy_key, None)

    _atomic_save(target, config)
    msg = f"wardrobe: 已清理历史键 {WARDROBE_LEGACY_KEYS}，"
    if migrated_custom:
        msg += f" 并将旧版本自定义预设迁移至 outfits_v5: {migrated_custom}"
    else:
        msg += " 未发现需要迁移的旧预设"
    logger.warning(msg)


def migrate_plugin_configs(run_dir, logger):
    """Migration registry; failures retain the marker for the next startup."""
    run_dir = Path(run_dir).resolve()
    for migration in (_migrate_core_reply, _migrate_wardrobe):
        try:
            migration(run_dir, logger)
        except Exception as exc:
            logger.warning(
                f"配置迁移失败，将在下次启动重试: {exc}"
            )
