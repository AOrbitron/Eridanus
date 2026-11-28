# 绝区零便签素材

来自 [ZZZure/ZZZeroUID](https://github.com/ZZZure/ZZZeroUID)，参考版本
`86b159f4121abf7bcd3fb6975c2fafb5a59acb96`。

- PNG 素材：`ZZZeroUID/zzzerouid_stamina/texture2d/`
- `background.jpg`：`ZZZeroUID/utils/texture2d/bg.jpg`
- `zzz_fonts.ttf`：`ZZZeroUID/utils/fonts/zzz_fonts.ttf`
- `player_card_min.png`：`ZZZeroUID/utils/texture2d/player_card_min.png`
- 布局参考：`ZZZeroUID/zzzerouid_stamina/draw_zzz_stamina.py`

上游许可证为 GNU Affero General Public License v3.0，保留于
[LICENSE-ZZZeroUID](LICENSE-ZZZeroUID)。素材及原设计归上游原作者所有。
Eridanus 中的适配函数位于 `utils/draw_note.py`，使用本项目已获取的数据，
不依赖 gsuid_core 或 manshuo_draw，也不会为绘制额外请求游戏接口。
头像使用查询对象的 QQ 头像，获取失败时绘制默认头像；角色名称、等级与大区名称
使用本项目的游戏角色记录接口数据，游戏 UID 使用角色记录或登录时保存的数据。

原神、崩铁便签也复用此目录的背景、玩家信息卡、状态图标与字体，树脂、宝钱和
开拓力面板由 Pillow 绘制；角色资料直接复用本次便签请求中的角色记录，不额外查询。
三个游戏的玩家信息卡在 UID 右侧显示与区服标签相同样式的游戏名称。
