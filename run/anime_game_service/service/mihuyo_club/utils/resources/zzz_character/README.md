# 绝区零角色攻略资源

角色别名来自 [ZZZure/ZZZeroUID](https://github.com/ZZZure/ZZZeroUID) 的
`ZZZeroUID/utils/alias/char_alias.json`，参考提交
`86b159f4121abf7bcd3fb6975c2fafb5a59acb96`。
上游许可证见 [LICENSE-ZZZeroUID](../zzz_note/LICENSE-ZZZeroUID)。

攻略图同时获取上游 `ZZZeroUID/guide/cat/`（猫冬）和 `guide/flower/`（听雨惊花），
分别保存在 `mihuyo_club/data/ZZZ/character/cat/` 和 `character/flower/`。
旧 `角色攻略/` 目录的图片及增量更新记录会迁移到新目录。图片和攻略内容归原作者所有。

配置位于 `run/anime_game_service/config.yaml` 的 `mihuyo_club.zzz` 下：

```yaml
mihuyo_club:
  update_resource_auto: True
  zzz:
    resource_source: "auto"
    first_resource: "猫冬"
```

`resource_source` 默认 `auto`，使用配置的 HTTP 代理并发测速上游 11 个镜像，
从有效目录中选择响应最快的节点下载。指定节点时只使用该节点，不进行测速或切换。
节点名称为 `CNJS`、`TW`、`SG`、`US`、`Azure SG`、`Oracle KR`、`Oracle JP`、
`MiniGG`、`Lulu`、`TakeyaYuki`、`Elysia`。日志会提示测速开始和选中的节点。

`first_resource` 可选 `猫冬`（默认）或 `听雨惊花`；查询先找指定提供方，缺失时查找另一家，
两家都没有时提示“缺失资源，需要更新”。启动更新、手动更新均下载两家攻略。

启动时异步检查文件大小和修改时间，补充缺失或更新过的图片；
手动发送“绝区零更新资源”会重新下载该游戏的攻略图。更新失败时保留旧图。
启动检查和手动更新均使用 `config.common_config.basic_config['proxy']['http_proxy']`，
配置为空时传入 `None`。后台任务在机器人主事件循环中运行，插件卸载时取消并等待下载结束。
启动时会输出 INFO 提示；整个启动更新超过 60 秒后取消全部下载，并输出停止更新的 INFO 提示。
查询例：“绝区零艾莲攻略”“zzz星见雅攻略”“绝区零角色攻略11号”。
