---
name: zhuque-ai-check
description: 用腾讯朱雀官方网页检测文本、论文或文档的 AI 特征，批量提交并核对全文覆盖，保存完整分段结果、截图和 PDF 报告。用户要求朱雀检测、查询长度限制或归档检测报告时使用。
---

# 朱雀 AI 检测

官方入口：<https://matrix.tencent.com/ai-detect/>。沿用用户指定的浏览器和会话；本机 agent-browser 默认使用 Clearcote。新任务用具名 session，需要登录时使用可见窗口。一般浏览操作参考可用的 agent-browser 技能或 CLI 帮助。辅助脚本需要 Python 3、agent-browser；PDF 提取与核验还需要 PATH 中的 pdftotext、pdfinfo。

## 输入与限制

用户请求检测指定文件，即授权上传这些文件；不要顺带上传其他资料。明确输入范围是全文、正文还是选段。PDF 默认提取全部可提取页面文字，保留原件；记录 OCR、公式、目录和参考文献等输入条件。

```bash
rtk proxy python <skill-dir>/scripts/zhuque.py prepare --out ./zhuque-results paper.pdf other.txt
rtk proxy agent-browser --session zhuque --headed open https://matrix.tencent.com/ai-detect/
```

脚本支持 UTF-8 TXT、PDF、DOCX；DOCX 提取主文档和表格，不含页眉、脚注等附加部分。以生成的 inputs/ 文件作为实际上传和内容核对依据，不改写文字。

执行时核对当前格式、长度、大小和额度规则。2026-11-03 观察到上传声明 TXT/DOCX、文件上限 10 MiB、手动文本最低计数 350；英文纯字母单词按一个单位计。未发现明确字符数上限，12 万字符 TXT 曾完整返回。这些历史观察不能当成当前无限制或固定每日额度。必要时检查当前官方前端并保存精简校验依据，避免读出账户令牌。

## 每篇闭环

1. 对照 manifest.json 上传 inputs/ 中的对应文件。上传会自动开始检测，不要再立即点击检测。验证码、处理中、空比例、旧文本、仅有 OK 消息均不算成功；等待当前文件完成。
2. 采集完整结果和截图：

   ```bash
   rtk proxy python <skill-dir>/scripts/zhuque.py capture --out ./zhuque-results --id 01 --session zhuque
   ```

   脚本核对文件名（若可获取）、输入哈希、返回全文和比例，保存每段的 text、label、conf、order、position。缺失精确 conf 或全文不对应时停止，不将只有颜色/长度的记录当成完整结果。
3. 保存并核验官网模板 PDF：

   ```bash
   rtk proxy python <skill-dir>/scripts/zhuque.py export --out ./zhuque-results --id 01 --session zhuque
   ```

   命令点击官网报告按钮，临时接管新建报告 iframe 的 print，保留原样 HTML 和补上原站资源基址的可打开副本，再用浏览器导出 PDF；不发起检测请求、不改变检测结果。若未捕获到报告，停止并读 [报告恢复与故障处理](references/report-recovery.md)。
4. 检查 PDF 的首页、正文页和末页图像，确认官网图表、样式和文字正常。只有完整数据、全文核对、截图和 PDF 核验全部成功，才上传下一篇。上一步失败后继续上传，可能在验证码期间替换待测文件。额度耗尽时保留已完成项，不更换身份重置额度，不自动重复检测。

验证码按当前运行环境规则处理；需要用户登录或接管时保留窗口。某次用户允许代操作验证码，不代表所有后续环境都授权。相同检测或导出错误连续两次后，保存现场并说明具体阻塞，避免循环消耗额度。

## 归档与恢复

```bash
rtk proxy python <skill-dir>/scripts/zhuque.py summary --out ./zhuque-results
```

交付 index.html、summary.json、实际上传文件、完整 JSON、截图和逐篇 PDF。分别列人工特征、疑似 AI、AI 特征；记录输入哈希、模型日期、原结果采集时间、报告导出时间和内容核对状态。检测占比不等同作者实际使用 AI 的比例。

结果被覆盖或配额推送影响页面时，先读 [恢复说明](references/report-recovery.md)。只有真实精确分段数据完整，才支持恢复导出。`capture --from-json <saved-result.json>` 验证并导入已有结果，不调用检测；`export --restore` 将已验证的归档恢复到网页显示，仅用于导出并记录恢复时间。缺失的 conf 不能从颜色补造。
