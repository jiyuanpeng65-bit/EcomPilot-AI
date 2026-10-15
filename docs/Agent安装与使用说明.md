# EcomPilot AI：文件与使用说明

本仓库是公开求职作品，包含一个 Agent、一个 Skill、统计辅助程序、样本测试与真实展示截图。本机部署、管理员凭据辅助工具和内部运维资料不在公开范围内。

## 文件

- `agents/ecompilot-agent.md`：任务接收、调用 Skill、检查结果和授权后的飞书发送。
- `skills/erp-business-report/SKILL.md`：唯一业务 Skill；规则在 `references/`，查询与统计辅助程序在 `scripts/`。
- `.codebuddy-plugin/plugin.json`：WorkBuddy 原生专家包清单。
- `tests/test_business_report.py`：不调用真实 ERP 的构造样本测试。

## 在自己的环境使用

1. 自行准备可用的 ERPNext 测试系统、独立只读 API 账号，以及 WorkBuddy 已连接的飞书工具。本仓库不提供账号、密钥或私人接收目标。
2. 将 Skill 的 `references/runtime.json` 占位内容替换为自己的本机路径、只读账号名称和演示公司。公开版查询适配器从进程环境变量 ERPNEXT_API_KEY、ERPNEXT_API_SECRET 读取凭据；请由自己的可信本机凭据管理方式注入，不在源码、JSON配置或日志中保存真实值。原作者本机的DPAPI与管理员辅助工具不公开，也未被此次发布修改。
3. 在 WorkBuddy 中按本机专家管理规范加载此包，确认一个 Agent 和一个 Skill 可识别。先输入“调用 erp-business-report，查询全部演示数据，阈值20，只展示，不发送”。
4. 手动核对报告后，明确确认接收目标、报告和发送身份，再使用自己已有的飞书连接器。需要每日运行时，在 WorkBuddy 中另行配置09:00（Asia/Shanghai）任务；复制源码不会自动创建调度。

仅业务读取使用 API 账号，禁止管理员回退，不修改商品、订单、库存或权限。ERPNext 和连接器的安装、授权由各自官方流程负责；本公开作品不包含私有环境的初始化脚本。
