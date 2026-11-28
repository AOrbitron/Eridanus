# 图鉴与基质查询来源

移植日期：2026-11-26。项目中保留上游的功能逻辑，不依赖参考仓库的本机路径或 gsuid_core 运行环境。

| 本地文件 | 来源与参考提交 | 适配内容 |
| --- | --- | --- |
| `arknights_wiki.py` | [ArknightsUID](https://github.com/baiqwerdvd/ArknightsUID)，qwerdvd，`0187dd985c897f444391fae050a82b728877382e` 的 `arknightsuid_wiki/draw_wiki_img.py`：`get_wiki_info`、`get_equip_info` | 直接读取原始 JSON；保留属性、最高等级技能、天赋、潜能、信赖、全部模组等级。补齐原始字符串枚举、特性黑板、技能持续时间及 C# 百分比格式。模组同时处理 TRAIT/TALENT/DISPLAY/DATA_ONLY 描述，并标明潜能要求。 |
| `draw_wiki.py` | 上述图鉴文字输出 | 使用本项目字体重新排版并自动分张，完整保留文字内容。上游启用的是 `text2pic`，未采用其未启用的实验性 `draw_wiki` 固定坐标布局。 |
| `endfield_gamedata/character_weapon_info.py`、`i18n_text.py`、`weapon_gem_info.py` | [BeyondUID](https://github.com/baiqwerdvd/BeyondUID)，baiqwerdvd，`95ba169a299db1371f656442c386e7cdd801e106` 的 `beyonduid_gamedata/` 同名文件 | 保留名称查找、国际化、完美基质、副本词条池及推荐排序；替换数据目录为 Eridanus 的完整表快照。 |
| `draw_gem.py` | BeyondUID 同一提交的 `beyonduid_gem/draw_img.py` | 保留多武器共锁、三基础和一个附加/技能词条约束、完整/部分方案、可顺带刷的武器、角色徽标及深色金色图卡。替换字体、原始素材路径、页脚和图片输出适配，每次重新绘图。 |
| `guide_resource.py`、`guide_image.py`、`../command/guide.py` | Eridanus 本地适配；指令形式参考本项目 `mihuyo_club/command/character.py` | 按游戏前缀、类别（干员/模组/武器）和查询词（图鉴/攻略）分派，保留名称前/后置；首次按需下载、主动更新、整组校验后原子替换，失败保留旧资源；复用游戏原始头像，不复用成品图。 |

两个上游均在 `pyproject.toml` 声明 `GPL-3.0-or-later`。上述移植和衍生文件沿用该许可，许可证全文见 [LICENSE-GUIDE-GPL-3](LICENSE-GUIDE-GPL-3)。各游戏原始数据及图片的权利归相应权利人，代码许可不改变游戏素材权利。

明日方舟表来自 [Kengxxiao/ArknightsGameData](https://github.com/Kengxxiao/ArknightsGameData) 的 `zh_CN/gamedata/excel/`：`character_table`、`skill_table`、`uniequip_table`、`battle_equip_table`。读取原始 JSON 避免新增 `torappu-excel` 依赖；上游 `EXCEL.BATTLE_EQUIP_TABLE.equips` 是其 Python 封装，下载的原表本身直接以 `uniequip_*` 为键。

终末地使用 BeyondUID 同款镜像的 `BeyondUID/TableCfg/` 12 张表及 `BeyondUID/resource/` 原始图标。资源可能滞后于游戏更新，可通过对应游戏的“更新资源”重取；未找到的干员或基质推荐会明确提示，不使用猜测数据。多个英文武器名称可各自用英文双引号包裹后以空格分隔。

游戏表保存在 `service/skland/data/guides/<game>/tables.json`，原始头像复用 `data/gacha/<game>/assets/`。成品图仅写入项目根目录 `data/pictures/cache/`，随机文件名，不存成品图索引、不读取旧成品。
