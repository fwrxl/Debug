"""全局反思单元测试 - 使用真实 LLM 测试 global_reflect"""
import sys
from pathlib import Path
import os

# 加载 .env 环境变量（与 debug_robot_scenario2.py 一致）
project_root = Path(__file__).parent.parent.parent
env_file = project_root / ".env"
if env_file.exists():
    with open(env_file, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value

sys.path.insert(0, str(project_root))

import unittest
from agent.reflection.reflector import ReflectionModule


class TestGlobalReflection(unittest.TestCase):
    """测试全局反思模块（真实 LLM）"""

    def setUp(self):
        """初始化测试环境"""
        self.reflector = ReflectionModule(config={})
        self.situation = "用户说往前走但机器人没有反应"
        self.failed_log = """
# === 阶段1: 意图分类 ===
[IntentEnsemble] 裁决完成 intent=2 conf=0.42 cost=127ms
[Ensemble] trace rule_fast: intent=2 conf=0.8 cost=1ms reasons=['chat_pattern']
[Ensemble] trace llm_light: intent=1 conf=0.65 cost=120ms reasons=['llm_light']
[Ensemble] trace llm_cmd: intent=1 conf=0.7 cost=115ms reasons=['llm_cmd']
⚠️  裁决失败: 意图=2(闲聊) 但 rule_fast+llm_cmd 都命中指令

# === 阶段4: 参数提取 ===
[ParameterExtractor] regex="往<方向>走" no match in "往前走"
⚠️  参数提取失败: 缺少"方向"参数，回退到默认"前"

# === 阶段5: 协议生成 ===
[ProtocolBuilder] template="move_forward" found
✅ 协议生成成功
        """

    def _create_branch_results(self, upstream_conf=0.92, downstream_conf=0.60):
        """构建标准分支结果"""
        return [
            {
                "module": "intent_classifier",
                "reflection_confidence": upstream_conf,
                "reflection_reason": "裁决组件错误输出闲聊意图",
                "reflection_evidence": [
                    "日志行：'[IntentEnsemble] 裁决完成 intent=2 conf=0.42'",
                    "日志行：'⚠️ 裁决失败: 意图=2 但 rule_fast+llm_cmd 都命中指令'"
                ],
                "reflection_uncertainty": "无"
            },
            {
                "module": "parameter_extractor",
                "reflection_confidence": downstream_conf,
                "reflection_reason": "正则匹配失败，方向参数丢失",
                "reflection_evidence": [
                    "日志行：'[ParameterExtractor] regex=\"往<方向>走\" no match in \"往前走\"'"
                ],
                "reflection_uncertainty": "无"
            },
            {
                "module": "protocol_builder",
                "reflection_confidence": 0.05,
                "reflection_reason": "协议生成成功，该模块无问题",
                "reflection_evidence": [
                    "日志行：'[ProtocolBuilder] template=\"move_forward\" found'",
                    "日志行：'✅ 协议生成成功'"
                ],
                "reflection_uncertainty": "无"
            }
        ]

    # ==================== 正常场景测试 ====================

    def test_global_reflect_upstream_root_cause(self):
        """场景1：上游误判导致下游症状，全局反思应识别最前端根因"""
        result = self.reflector.global_reflect(
            situation=self.situation,
            failed_log=self.failed_log,
            branch_results=self._create_branch_results(upstream_conf=0.92, downstream_conf=0.60),
        )

        print(f"\n场景1结果: {result}")
        self.assertIn(result["root_cause_module"], {"intent_classifier", "parameter_extractor"})
        self.assertGreater(result["confidence"], 0)
        self.assertIsInstance(result["diagnosis"], str)
        self.assertGreater(len(result["diagnosis"]), 0)

    def test_global_reflect_independent_downstream_error(self):
        """场景2：下游模块独立错误，上游正常"""
        branch_results = [
            {
                "module": "intent_classifier",
                "reflection_confidence": 0.15,
                "reflection_reason": "输出正确，无异常",
                "reflection_evidence": ["日志显示意图分类正确"],
                "reflection_uncertainty": "无"
            },
            {
                "module": "parameter_extractor",
                "reflection_confidence": 0.88,
                "reflection_reason": "正则未覆盖'往左走'语法，方向参数丢失",
                "reflection_evidence": [
                    "日志行：'[ParameterExtractor] regex=\"往<方向>走\" no match in \"往左走\"'"
                ],
                "reflection_uncertainty": "无"
            }
        ]

        result = self.reflector.global_reflect(
            situation="用户说往左走但机器人未转向",
            failed_log="[ParameterExtractor] regex='往<方向>走' no match in '往左走'",
            branch_results=branch_results,
        )

        print(f"\n场景2结果: {result}")
        self.assertIn(result["root_cause_module"], {"intent_classifier", "parameter_extractor"})
        self.assertGreater(result["confidence"], 0)
        self.assertIsInstance(result["diagnosis"], str)

    # ==================== 异常场景测试 ====================

    def test_global_reflect_empty_branch_results(self):
        """场景3：空分支结果"""
        result = self.reflector.global_reflect(
            situation=self.situation,
            failed_log=self.failed_log,
            branch_results=[],
        )

        print(f"\n场景3结果: {result}")
        self.assertIn(result["root_cause_module"], {"", "intent_classifier", "parameter_extractor"})
        self.assertIsInstance(result["diagnosis"], str)

    def test_global_reflect_prompt_and_response_recorded(self):
        """场景4：验证 llm_prompt 和 llm_response 被正确记录"""
        result = self.reflector.global_reflect(
            situation=self.situation,
            failed_log=self.failed_log,
            branch_results=self._create_branch_results(),
        )

        print(f"\n场景4结果: {result}")
        self.assertIn("llm_prompt", result)
        self.assertIn("你是全局诊断专家", result["llm_prompt"])
        self.assertIn("Pipeline 执行顺序", result["llm_prompt"])
        self.assertIn("llm_response", result)
        self.assertIsInstance(result["llm_response"], str)
        self.assertGreater(len(result["llm_response"]), 0)


if __name__ == "__main__":
    unittest.main()
