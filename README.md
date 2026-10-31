<p align="center">
  <img src="https://github.com/AOrbitron/Eridanus/blob/master/web/dist/eridanus.svg" width="250" height="250" alt="Shiro">
</p>

<div align="center">

# Eridanus

_🎊 基于 [OneBot](https://github.com/howmanybots/onebot/blob/master/README.md) 协议的多功能bot兼python开发框架 🎊_<br>

</div>

<p align="center">
    <a href="https://github.com/AOrbitron/Eridanus/issues"><img src="https://img.shields.io/github/issues/AOrbitron/Eridanus?style=flat-square" alt="issues" /></a>
    <a href="https://github.com/AOrbitron/Eridanus/blob/master/LICENSE"><img src="https://img.shields.io/github/license/AOrbitron/Eridanus?style=flat-square" alt="license"></a>
    <a href=""><img src="https://img.shields.io/badge/QQ群-1050663831-brightgreen.svg?style=flat-square" alt="qq-group"></a>
    <a href="https://github.com/howmanybots/onebot"><img src="https://img.shields.io/badge/OneBot-v11-blue?style=flat-square&logo=data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAEAAAABABAMAAABYR2ztAAAAIVBMVEUAAAAAAAADAwMHBwceHh4UFBQNDQ0ZGRkoKCgvLy8iIiLWSdWYAAAAAXRSTlMAQObYZgAAAQVJREFUSMftlM0RgjAQhV+0ATYK6i1Xb+iMd0qgBEqgBEuwBOxU2QDKsjvojQPvkJ/ZL5sXkgWrFirK4MibYUdE3OR2nEpuKz1/q8CdNxNQgthZCXYVLjyoDQftaKuniHHWRnPh2GCUetR2/9HsMAXyUT4/3UHwtQT2AggSCGKeSAsFnxBIOuAggdh3AKTL7pDuCyABcMb0aQP7aM4AnAbc/wHwA5D2wDHTTe56gIIOUA/4YYV2e1sg713PXdZJAuncdZMAGkAukU9OAn40O849+0ornPwT93rphWF0mgAbauUrEOthlX8Zu7P5A6kZyKCJy75hhw1Mgr9RAUvX7A3csGqZegEdniCx30c3agAAAABJRU5ErkJggg=="></a>
</p>

<p align="center">
  <a href="https://eridanus.netlify.app">文档</a>
  ·
  <a href="https://github.com/AOrbitron/Eridanus/releases">下载</a>
  ·
  <a href="https://eridanus.netlify.app/getting-started/">快速开始</a>
  ·
  <a href="">参与贡献</a>
</p>

# 部署
[文档](https://eridanus-doc.vercel.app)
[文档 备用站1](https://eridanus.netlify.app)   
[文档 备用站2](https://eridanus.apollodorus.xyz)   
 


如使用快捷部署部署失败，请参照文档部署。
# 交流
QQ群：1050663831  [点击加入](https://qm.qq.com/q/4iD3sVJNZe)
telegram群组：[点击加入](https://t.me/+BUcoYoUebgIzMWFl)

**如果您对此项目的开发工作感兴趣，欢迎加入我们🎉。**

# 更新计划
- [x] 接入telegram
- [x] Android 悬浮窗助理 App (Eridanus-Android)


# 架构与多平台接入 (Architecture & Multi-Platform Hub)

Eridanus 采用基于 **OneBot v11 协议标准**与**事件驱动中心 Hub** 的多端统一桥接架构：无需重复启动多份 Bot 核心插件，通过 WebUI 服务端作为 WebSocket Hub 中转，实现 QQ、WebUI、Telegram 以及移动端（如 Android 悬浮窗应用）的无缝接入与共享上下文。

### 核心架构示意图
```text
 ┌───────────────────────┐          ┌────────────────────────┐
 │   QQ (OneBot v11)     │          │    Telegram Bot API    │
 │ (Snowluma /LLOneBot等) │          │ (长轮询 / sendDocument) │
 └───────────┬───────────┘          └───────────┬────────────┘
             │                                  │
     (正向/反向 WS)                      (双向事件与消息转换)
             │                                  │
             ▼                                  ▼
 ┌───────────────────────────────────────────────────────────┐
 │          Eridanus Multi-Platform WebSocket Hub            │
 │                    (web/server_new.py)                    │
 │                                                           │
 │  * 虚拟路由分发 (Virtual Group Router):                    │
 │    - 真实 QQ 群: 原样透传                                  │
 │    - WebUI 模拟群: 879886836                              │
 │    - Telegram 群/频道: 11111{chat_id}                     │
 │    - Android 悬浮端: 222222                               │
 │                                                           │
 │  * 来源标记字段 (adapter_source):                         │
 │    - qq / webui / telegram / android                      │
 │    - 支持针对非 QQ 平台关闭图片混淆/灰度与 PDF 加密等限制 │
 └─────────────────────────────┬─────────────────────────────┘
                               │
                       (OneBot v11 内部总线)
                               ▼
 ┌───────────────────────────────────────────────────────────┐
 │               Eridanus Bot Core & Plugins                 │
 │                                                           │
 │  * 插件生态: Mai_Reply / 资源搜索 / 屏幕视觉建议 / 数据库 │
 │  * 记忆共享: 跨平台通过 /bind <qq_id> 共享相同用户上下文   │
 └───────────────────────────────────────────────────────────┘
                               ▲
                               │
            ┌──────────────────┴──────────────────┐
            │                                     │
 ┌──────────┴──────────┐               ┌──────────┴──────────┐
 │    WebUI 前端网页    │               │  Android 悬浮窗应用  │
 │  (Vue / WebSocket)  │               │ (屏幕识别/翻译/建议) │
 └─────────────────────┘               └─────────────────────┘
```

### 多端协同与路由设计

1. **统一适配与无缝透传**：
   - 所有的入站消息（QQ、WebUI、Telegram、Android）在进入 Bot 处理流水线前，均被规范化为标准的 OneBot v11 GroupMessageEvent 或 PrivateMessageEvent。
   - 消息携带统一的 `adapter_source`（取值 `qq`、`webui`、`telegram`、`android`），供业务插件优雅识别终端来源。
2. **免二次启动插件 (Single Instance Multi-Client)**：
   - Eridanus 作为标准 OneBot 客户端连接本地 Hub，所有插件仅在内存中加载一次，无需为每个平台单独拉起 Bot 实例。
3. **Telegram 增强能力**：
   - **合并转发相册化**：支持 OneBot Node 消息节点，将多个图片合并为单个 Telegram sendMediaGroup 原生相册发出，告别刷屏。
   - **文件原样传输**：针对 JM 漫画、PDF 下载与大文件，直接通过 Telegram sendDocument 接口传输，当目标为 Telegram 时自动绕过加密并免去密码提示。
   - **上下文绑定**：发送 `/bind <QQ号>` 即可将 Telegram 会话与对应的 QQ 用户 ID 关联，实现跨端上下文与长期记忆互通。

# 派生项目
- [Achernar](https://github.com/AOrbitron/Achernar) cpolar隧道本地反向代理，kaggle自动切换账号运行指定脚本。(用于在kaggle持久化部署ai绘画等服务)
- [vits api](https://github.com/avilliai/vits_api) 本地部署vits语音合成服务端，已打包。
- [Eridanus-dep](https://github.com/AOrbitron/eridanus-dep) 一个轻量化、易于上手的onebot v11 python SDK。
- [material-dashboard](https://github.com/avilliai/material-dashboard) 基于原版material-dashboard项目修改而成的Eridanus webui。
- [Eridanus-Android](https://github.com/AOrbitron/Eridanus-Android) Eridanus Android 悬浮窗副驾驶与多模态屏幕翻译助理。
# 开源协议
Eridanus is licensed under [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) . Everyone is FREE to access, use, modify, and redistribute this project under the same license, but commercial use is strictly prohibited.  
Unauthorized commercial usage of Eridanus is explicitly forbidden under this license.   
If you like the project, please give it a star!    

[![License: CC BY-NC-SA 4.0](https://licensebuttons.net/l/by-nc-sa/4.0/88x31.png)](https://creativecommons.org/licenses/by-nc-sa/4.0/)

Eridanus 采用 [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) 许可证。任何人均可免费获取、使用、修改，并以相同协议重新分发本项目，但仅限于非商业用途。   
未经授权的任何商业用途均被禁止。      
如果你喜欢这个项目，请给我们一个 Star！
# Thanks to all contributors for their efforts

<a href="https://github.com/AOrbitron/Eridanus/graphs/contributors" target="_blank">
  <img src="https://contrib.rocks/image?repo=AOrbitron/Eridanus" />
</a>

> Live2D 模型作者：[【免费模型】这么可爱的小狗免费带回家！](https://www.bilibili.com/video/BV1LM41137vK)

[![Star History Chart](https://api.star-history.com/svg?repos=AOrbitron/Eridanus&type=Date)](https://www.star-history.com/#AOrbitron/Eridanus&Date)
