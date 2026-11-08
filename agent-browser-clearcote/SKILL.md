---
name: agent-browser-clearcote
description: "使用本机全局安装的 Clearcote Chromium 驱动 agent-browser。用户要求 Clearcote 接入、使用 agent-browser 浏览或自动化网页、排查其浏览器路径与 CDP 连接时使用。"
---

# Agent Browser + Clearcote

本机的 `agent-browser` 默认使用 Clearcote，普通浏览任务直接使用现有安装。

## 全局安装

- 浏览器：`~/.local/share/clearcote-browser/browser/chrome`
- 配置：`~/.agent-browser/config.json`
- 下载件、签名及验证记录：`~/.local/share/clearcote-browser/`
- 初始验证组合：agent-browser 0.23.4、Clearcote 开源版 v0.1.0-pre.25 / Chromium 151.0.7922.108。版本可能更新，排障时读取实际版本。

配置包含浏览器绝对路径、Linux/Chrome persona、Asia/Shanghai 时区和迁移前的固定 seed `paper-workspace`；保留此 seed 是为了延续原来的身份。`headed` 沿用用户设置，HTTPS 证书检查已开启。

## 使用

为任务选一个具名 session，在同一任务后续命令中复用。项目无需再放置 `agent-browser.json`。

```bash
rtk proxy agent-browser --session clearcote open https://example.com
rtk proxy agent-browser --session clearcote snapshot -i
# 根据当前快照中的 @eN 执行 click、fill 等操作。
rtk proxy agent-browser --session clearcote close
```

通用命令查看 `agent-browser --help`。支持时可读取 `agent-browser skills get core`；本机 0.23.4 不支持 `skills` 子命令，其配套说明位于 `/usr/lib/node_modules/agent-browser/skills/agent-browser/SKILL.md`。需要完整网页自动化流程时读取该说明。

## 配置与身份

- 配置优先级：用户全局配置 < 当前目录项目配置 < 环境变量 < CLI 参数。发现启动了其他浏览器时，按此顺序检查覆盖来源，不要直接重写项目配置。
- 启动参数属于 session 的后台 daemon；修改配置后，关闭自己使用的 session 再启动。不要关闭其他任务的 session。
- 临时无界面运行可在首次启动时加 `--headed false`。
- session 名用于隔离自动化会话，不会自动更换指纹 seed。需要另一个身份时，在首次启动该 session 时使用 `--args` 传入新的 `--fingerprint=...`，并保留所需的其他 persona 和时区参数；CLI 的 `--args` 会覆盖配置中的整组参数。
- Clearcote 的 persona 已在引擎中实现；不额外注入 JavaScript stealth 插件。

## CDP 与验证边界

通常使用默认的自定义可执行文件启动方式即可。需要另一客户端接入时，用 `agent-browser --session clearcote get cdp-url` 获取地址，再用另一个具名 session 执行 `connect <ws-url>`。连接后检查 `tab list`：初始页面可能是 `about:blank`，不要假定复用了原标签页。调试端点保持在本机回环地址。

接入验证应检查实际浏览器路径、页面读取以及一次可观察的交互结果；只有命令返回成功不够。2026-11-03 已验证直接启动、CDP 连接、快照、填表、点击、截图及 `navigator.webdriver=false`。这些结果不代表已通过任意网站的反自动化检测。
