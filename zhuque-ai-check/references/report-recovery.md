# 官网报告与恢复

“下载报告”不是返回服务器 PDF。已观察到的实现：DownloadButton 渲染 `#report-container`，克隆到同源 iframe，将 canvas 换成图片，再调用 iframe 的 print，随后删除 iframe。浏览器“另存为 PDF”才产生文件。模板中的“检测时间”可能取导出时的当前时间，因此必须另外保留原始采集时间。

## 导出故障

辅助脚本只临时接管新建且包含 `#report-container` 的同源 iframe 的 print，捕获原样 HTML。它不调用隐藏检测 API、修改模型结果、重置额度或修改浏览器持久配置。网站更新后，先核对当前 DOM 和前端实现，不机械重复点击按钮。

原生打印窗口弹出时，页面 eval/press 可能超时，而页面截图仍显示旧内容。先检查实际打印窗口，保存 PDF 或关闭它。可用本机桌面截图和原生 UI 工具；没有对应能力时让用户接管。不要关闭其他会话。文件保存注意输入法，使用粘贴或临时英文输入并恢复状态；以实际文件和 PDF 核验为准。

本地 HTML 必须保留原站资源基址，否则相对 CSS 链接会在 file:// 下失效。脚本保留原始模板和加入 base 的渲染副本，确认样式表加载后才导出；长论文恢复数据通过 eval --stdin 传输，避免系统单个命令参数长度限制。

PDF 必须通过文件名、逐段四位小数 conf、全部分段文字和末尾文字核验，并渲染检查排版。OCR/字体导致核验失败时，保留文件与具体错误，打开原始模板和输出 PDF 对照，不直接标为完成。

## 恢复已有结果

新文件会覆盖旧结果。WebSocket 的额度更新也可能把根组件 data 换成仅有 status/availableUses 的对象，但 segmentLabel 和总体 confidence 仍保留。读取当前显示使用的真实分段属性，只采集白名单字段；不要输出整个组件、feedback token、cookie 或请求头。

恢复前核对分段合并文本与输入一致、比例有效，并保留原始来源。缺少精确 conf 的旧记录只能生成明确标注的本地汇总，不能还原完整官网报告。新一轮检测必须与旧记录分开。

```bash
rtk proxy python <skill-dir>/scripts/zhuque.py capture --out ./recovered --id 01 --from-json saved-result.json
rtk proxy python <skill-dir>/scripts/zhuque.py export --out ./recovered --id 01 --session zhuque --restore
```

`--restore` 只将已验证的真实结果恢复到网页显示，保留当前账户额度，不请求检测。导出文件记录来源为历史结果恢复，不能声称新检测或原检测时间重新发生。
