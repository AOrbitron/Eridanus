# -*- coding: utf-8 -*-
import os
import sys
import hashlib
import subprocess

def get_sha256(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()

print("=== STARTING YAMLMANAGER INTEGRATION & EXPANSION VERIFICATION ===")

# 1. Baseline verification
baseline_path = "artifacts_wardrobe/wardrobe_manager.py.baseline"
baseline_sha = get_sha256(baseline_path)
print(f"[1] Baseline SHA256: {baseline_sha}")
baseline_text = open(baseline_path, "r", encoding="utf-8").read()
has_ym_baseline = "_has_yaml_manager" in baseline_text
print(f"[1] Baseline has _has_yaml_manager: {has_ym_baseline} (Expected: False)")
assert not has_ym_baseline, "Baseline should not contain _has_yaml_manager"

# 2. Modified verification
modified_path = "artifacts_wardrobe/wardrobe_manager.py.modified"
target_path = "run/wardrobe/wardrobe_manager.py"
mod_sha = get_sha256(modified_path)
tgt_sha = get_sha256(target_path)
print(f"[2] Modified SHA256: {mod_sha}")
print(f"[2] Target   SHA256: {tgt_sha}")
assert mod_sha == tgt_sha, "Target must equal modified artifact"

# 3. Dynamic runtime test
from framework_common.framework_util.yamlLoader import YAMLManager
import run.wardrobe.wardrobe_manager as rwm
import run.wardrobe as rw

# Reset WardrobeManager singleton for clean test
rwm.WardrobeManager._instance = None
wm = rwm.WardrobeManager.get_instance()
print(f"[3a] WardrobeManager initialized. _yaml_manager connected: {wm._yaml_manager is not None}")
assert wm._yaml_manager is not None, "WardrobeManager should connect to YAMLManager"
assert wm._registered_reload_cb is True, "WardrobeManager should register reload callback"

# 3b. Verify outfits count (now 70 outfits)
outfits = wm.get_outfits()
print(f"[3b] Total outfits loaded via YAMLManager: {len(outfits)}")
assert len(outfits) >= 70, f"Must load all 70 outfits, got {len(outfits)}"

# 3c. Verify new sleepwear and no_hat flag
sleepwear_checks = [
    ("洛丽塔梦幻荷叶边睡裙", "梦幻洛丽塔睡裙"),
    ("半透明月光轻纱吊带睡裙", "半透明轻纱吊带"),
    ("黑天鹅半透明蕾丝吊带睡裙", "黑天鹅黑色轻纱"),
    ("哥特轻纱洛丽塔睡裙", "哥特轻纱黑紫睡裙"),
    ("薄荷轻纱清凉吊带睡裙", "薄荷绿轻纱吊带"),
]
for expected_name, query in sleepwear_checks:
    matched = wm.match_outfit(query)
    print(f"    [Sleepwear Match] Query: '{query}' -> Matched: '{matched}'")
    assert matched == expected_name, f"Query '{query}' should match '{expected_name}', got '{matched}'"
    info = wm.get_outfit(expected_name)
    assert info.get("no_hat") is True, f"{expected_name} must have no_hat=True"
print("[3c] Expanded sleepwear matching & no_hat checks PASS")

# 3d. Verify new daily outfits & priority
daily_checks = [
    ("甜心猫耳奶绒开衫", "可爱猫咪开衫"),
    ("法式小碎花吊带连衣裙", "法式碎花吊带"),
    ("软萌娃娃领格纹背带裙", "减龄娃娃领背带裙"),
    ("慵懒小熊露肩连帽卫衣", "小熊露肩卫衣"),
]
for expected_name, query in daily_checks:
    matched = wm.match_outfit(query)
    print(f"    [Daily Match] Query: '{query}' -> Matched: '{matched}'")
    assert matched == expected_name, f"Query '{query}' should match '{expected_name}', got '{matched}'"

# Verify default outfit priority: "常服" must match "默认常服" rather than "常服1"
assert wm.match_outfit("常服") == "默认常服", "Query '常服' must prioritize 默认常服"
assert wm.match_outfit("默认常服") == "默认常服", "Query '默认常服' must match 默认常服"
assert wm.match_outfit("街头常服") == "常服1", "Query '街头常服' must match 常服1"
assert wm.match_outfit("常服1") == "常服1", "Query '常服1' must match 常服1"
print("[3d] Daily expansion & priority tests PASS")

# 3e. Verify 默认常服 tags are clean (no Chinese '或者')
default_outfit = wm.get_outfit("默认常服")
assert "或者" not in default_outfit.get("clothing_tags", ""), "默认常服 must not contain Chinese '或者'"
print(f"[3e] 默认常服 clean tags: {default_outfit.get('clothing_tags')[:60]}...")

# 3f. Verify save via YAMLManager preserves comments in config.yaml
curr_outfit = wm.get_current_outfit()
print(f"[3f] Active outfit before test: {curr_outfit['name']}")
wm.set_current_outfit("半透明月光轻纱吊带睡裙")
assert wm.get_current_outfit()["name"] == "半透明月光轻纱吊带睡裙"
yaml_content = open("run/wardrobe/config.yaml", "r", encoding="utf-8").read()
assert "# 系统总开关" in yaml_content, "Comments must be preserved after YAMLManager save"
assert "# 角色外观基础锚点" in yaml_content, "Section comments must be preserved"
print("[3f] YAMLManager save_yaml test PASS (comments intact in config.yaml)")

# 3g. Verify dynamic function declaration building
decl = rwm.build_change_outfit_declaration()
outfit_desc = decl["parameters"]["properties"]["outfit_name"]["description"]
print(f"[3g] Dynamic declaration outfit_name desc ({len(outfit_desc)} chars): {outfit_desc[:60]}...")
assert "config.yaml" in outfit_desc
assert len(outfit_desc) < 200, "Description must remain concise"
print("[3g] Dynamic function declaration PASS")

# 3h. Test external reload callback
for cb in wm._yaml_manager._reload_callbacks:
    cb("wardrobe")
print(f"[3h] Reload callback triggered. Current outfit after reload: {wm.get_current_outfit()['name']}")
assert wm.get_current_outfit()["name"] == "半透明月光轻纱吊带睡裙"

# Restore original outfit
wm.set_current_outfit("机能风骑行皮衣")
print(f"[3i] Restored active outfit: {wm.get_current_outfit()['name']}")

# 4. Rollback test
temp_target = "temp_rollback_wm.py"
with open(temp_target, "wb") as f:
    f.write(open(modified_path, "rb").read())
assert get_sha256(temp_target) == mod_sha

res = subprocess.run(["sh", "artifacts_wardrobe/ROLLBACK.sh", temp_target], capture_output=True, text=True)
print(f"[4] Rollback script return code: {res.returncode}")
print(f"[4] Rollback stdout: {res.stdout.strip()}")
restored_sha = get_sha256(temp_target)
print(f"[4] Restored copy SHA256: {restored_sha}")
assert restored_sha == baseline_sha, "Rollback copy must match pristine baseline byte-for-byte"
if os.path.exists(temp_target):
    os.remove(temp_target)

print("=== ALL YAMLMANAGER INTEGRATION & EXPANSION VERIFICATION CHECKS PASSED ===")
