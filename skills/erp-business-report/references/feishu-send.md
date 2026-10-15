# 复用现有飞书发送

现有连接器是 `feishu@workbuddy-connector-plugins-official`，认证由现有工具管理，不提取其 Token。

Windows 本机已有 CLI：
`%USERPROFILE%\.workbuddy\binaries\node\cli-connector-packages\node_modules\@larksuite\cli\bin\lark-cli.exe`

主 Agent 必须先读取现有连接器的 `lark-shared/SKILL.md`、`lark-im/references/lark-im-messages-send.md` 和实际 `--help`。全局通知可通过本进程 `CLI_NO_UPDATE_NOTIFIER=1`、`CLI_NO_SKILLS_NOTIFIER=1` 静默，不修改认证。

流程：展示实时报告 → 用户确认具体接收人/群和发送内容及 user/bot 身份 → 发送 → 检查真实返回。姓名用现有只读 `contact +search-user --query ... --as user` 核对；多候选让用户选，不能猜。可保存非敏感目标ID但这不是以后所有消息的永久发送授权。

`im +messages-send --user-id <已确认ou_ID> --as <已确认身份> --markdown - --idempotency-key <唯一键> --json` 用标准输入传报告。首次默认先短测试、收到后发报告；用户明确跳过短测试则遵循用户要求。

键为不超过50字节的 report_id 与 target 的哈希。只在 `exit=0`、`ok=true` 且存在 message_id 时确认“工具发送成功”，不声称用户已经看到。只保留非敏感发送时间、目标、report_id、message_id 到本地私有记录。CLI 单次幂等保护有时间限制，不能依赖它作长期去重；查询本地成功记录避免重复发相同 report_id。超时/未知结果停止重试，先通过已有只读消息工具核查。

退出10或高风险确认阻拦必须解释具体原因并请求用户必要确认，不自动追加 `--yes`。认证/权限不足如实说明，不换新应用/账号绕过。

本阶段无定时发送、无飞书入站、无双向聊天。
