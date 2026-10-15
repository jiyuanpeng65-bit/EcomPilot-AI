---
name: erp-business-report
description: "查询本机真实 ERPNext 的商品、销售订单和库存，按今日、昨日、最近7天、指定日期或全部演示数据统计金额与状态、识别库存风险、生成中文老板日报；每次重新只读查询，支持库存阈值参数和飞书发送前的数据核验。"
version: "1.0.0"
author: "EcomPilot"
---

# ERP 经营日报

本 Skill 负责业务查询、规则、分析与报告；主 Agent 负责接收任务、审核、展示和授权后的飞书发送。无需新的框架、服务、MCP 服务器或定时器。

## 实际执行

先读取本目录 `references/runtime.json` 和 [业务规则](references/business-rules.md)。运行本目录 `scripts/report.py`，它调用 Windows PowerShell 的只读采集程序，公开版从当前进程环境变量 `ERPNEXT_API_KEY` 和 `ERPNEXT_API_SECRET` 获取已授权的只读凭据；由本机可信凭据管理方式注入，不写入仓库、不展示其值。示例（将路径解析为本 Skill 实际安装目录）：

```powershell
python "<Skill实际目录>\scripts\report.py" --period all-demo --json
python "<Skill实际目录>\scripts\report.py" --period today --threshold 20 --json
python "<Skill实际目录>\scripts\report.py" --period yesterday --json
python "<Skill实际目录>\scripts\report.py" --period last7 --json
python "<Skill实际目录>\scripts\report.py" --period range --start 2026-10-01 --end 2026-10-14 --threshold 60 --json
```

日期采用 Asia/Shanghai，最近7天包含今天与前6天。范围含起止日期。`all-demo` 查询当前配置演示公司全部可读取订单，报告显示实际订单日期范围，不使用固定历史答案。

每次任务必须重新运行，不缓存旧日报替代真实查询。JSON 中 `report` 是应展示/发送的正文，`analysis` 是具体订单/SKU证据，`report_id` 用于发送追踪。退出0且 `complete:true` 才是完整报告；退出3为部分查询或字段缺失，必须保留“数据不完整”；退出2为参数/安全连接错误，停止，不能编造报告或使用管理员。零订单只有查询完整时才是已核实的0。

采集器验证当前 API 身份，并只 GET Item、Sales Order、Bin；公司范围和已有 User Permission 同时生效。逐页按 `name asc` 读取直到空页，按实际返回数量推进，识别重复页及页数上限。权限403、网络错误、字段缺失、分页中断分别标明缺口，不扩权。环境变量缺失时停止并说明原因；不能把真实凭据写入源码、配置文件、日志或 Git。

## 报告与发送

使用程序生成的四段中文手机端报告：订单概况、库存概况、重点事项、数据说明。重要结论可追溯 `analysis.orders`、`analysis.inventory`。报告过长时正文可摘要，但不能删掉完整性警告或改变金额/业务含义，未展示的明细在 WorkBuddy 按需查阅 `analysis`。

所有解释依 [业务规则](references/business-rules.md)，禁止将销售订单金额解释成收款、利润或收入，禁止推测实际物流。

发送由主 Agent 使用现有连接器完成，遵循 [飞书约定](references/feishu-send.md)。未明确授权就只展示；不要自动发送或自动启用调度。未来调度接入说明见项目 `docs/Agent安装与使用说明.md`。
