# 绝区零抽卡卡片素材

抽卡池头图、S 级记录蒙版与情绪插图来自 [ZZZure/ZZZeroUID](https://github.com/ZZZure/ZZZeroUID)，参考版本 `86b159f4121abf7bcd3fb6975c2fafb5a59acb96`。

- `texture2d/` 中的卡池图、抽卡条目蒙版、UP 标记和等级插图：上游 `zzzerouid_gachalog/texture2d/`
- `bg.jpg`、`footer.png`、`SRANK.png`：上游 `utils/texture2d/`
- `player_card_min.png`、`zzz_fonts.ttf`：复用本项目 `../zzz_note/` 中的同源素材
- 抽卡卡片布局和 S 级条目样式参考上游 `zzzerouid_gachalog/draw_gachalogs.py`

上游许可证为 GNU Affero General Public License v3.0，文本保留在 `../zzz_note/LICENSE-ZZZeroUID`。素材及原设计归上游原作者所有。本项目自行实现了适配数据结构的绘制逻辑。

## 调频数据来源与缓存

国服首次自动取数使用官方调频统计接口 `/event/nap_gacha_record/api/zzz/` 的 `index`、`cur_pool_stat`、`hist_pool_stat`，按版本分批获取历史 S 级记录，并校验记录数量、累计抽数序号和垫数；日常普通更新使用旧的逐抽接口。新接口不提供完整的 A/B 级逐抽明细，不能将统计记录当成逐抽记录保存。

缓存仍在 `data/ZZZ/gacha/players/<游戏UID>.json`：`statistics` 保存新接口原始统计与历史记录，`data` 保留旧接口逐抽记录，`legacy_data_time` 标记旧接口最近成功更新的时间。绘制和新增抽数统计统一合并两种来源，通过同一次 S 级出货的物品 ID、时间及累计抽数位置去重，使用旧记录补充统计尚未同步的尾部。无法对齐的本地 S 级记录仍会显示，未知抽数标注 `?抽` 并提示。

- 首次发送 `绝区零抽卡记录`，本地没有记录时：仅请求新接口并保存，不自动追加旧接口查询；新接口失败时提示重试。
- `绝区零更新抽卡记录`：仅请求旧接口，按卡池从最新记录往前分页，遇到已有逐抽 ID 或与新接口历史匹配的 S 级记录后停止。若此前仅有新接口缓存，也可通过匹配 S 级记录确定合并位置；没有匹配点时继续读取全部可用记录。
- `绝区零全量更新抽卡记录`：两个接口都完整请求，保留本地旧记录并备份原缓存。
- `绝区零抽卡记录`：使用已保存的两种数据合并绘制；`绝区零查看抽卡记录` 效果相同。

全量更新时，单个来源失败不会清空另一个来源的缓存；本次请求的来源均失败时不写入缓存。新接口及数据合并实现在 `utils/zzz_gacha.py`，请求调度、持久化及绘制接入在 `command/card.py`。
