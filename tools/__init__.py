"""znew Agent 工具包

导出 tool schemas 和 handlers，供 agent.py 使用。
"""
from . import code_analyse, feishu_notify

# Tool schema 定义（Anthropic SDK 格式）
TOOLS = [
    {
        "name": "code_analyse",
        "description": (
            "分析测试失败日志，定位代码库中的 Bug。"
            "输入：测试场景描述 (situation) 和失败日志 (failed_log)。"
            "输出：错误根因、Bug 位置、修复建议、置信度。"
            "如果未提供 target_repo_path，将自动使用 .env 中配置的 DEBUG_PROJECT_PATH。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "situation": {
                    "type": "string",
                    "description": "测试场景描述，例如：用户说'往前走'但机器人没有移动",
                },
                "failed_log": {
                    "type": "string",
                    "description": "测试失败日志的完整内容",
                },
                "target_repo_path": {
                    "type": "string",
                    "description": "可选。目标代码仓库的绝对路径，默认从 .env 读取",
                },
            },
            "required": ["situation", "failed_log"],
        },
    },
    {
        "name": "feishu_notify",
        "description": (
            "发送飞书文本消息通知给指定接收人，消息内容为报告文件。"
            "输入：报告文件路径 (report_path)。"
            "输出：发送结果（成功/失败）。"
            "如果未提供 receive_id，将自动使用 .env 中配置的 receive_id。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "report_path": {
                    "type": "string",
                    "description": "报告文件路径（绝对路径或相对于项目根目录），文件内容直接作为消息正文发送",
                },
                "receive_id": {
                    "type": "string",
                    "description": "可选。接收者的飞书 open_id，默认从 .env 读取",
                },
            },
            "required": ["report_path"],
        },
    },
]

# Tool handler 映射
TOOL_HANDLERS = {
    "code_analyse": code_analyse.run,
    "feishu_notify": feishu_notify.run,
}
