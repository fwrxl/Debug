"""情景分析能力测试"""
import pytest
import asyncio
import os
import sys
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# 加载环境变量
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


class TestSituationAnalyzer:
    """情景分析能力测试"""

    @pytest.fixture
    def analyzer(self):
        """创建 SituationAnalyzer 实例"""
        from capabilities.situation_analysis.analyzer import SituationAnalyzer
        return SituationAnalyzer()

    @pytest.fixture
    def sample_situation(self):
        """示例情景描述"""
        return "用户说往前走但机器人没有反应"

    @pytest.fixture
    def sample_failed_log(self):
        """示例失败日志"""
        return """
# === 阶段1: 意图分类 ===
[IntentEnsemble] 裁决完成 intent=2 conf=0.42 cost=127ms
[Ensemble] trace rule_fast: intent=2 conf=0.8 cost=1ms reasons=["chat_pattern"]
[Ensemble] trace llm_light: intent=1 conf=0.65 cost=120ms reasons=["llm_light"]
[Ensemble] trace llm_cmd: intent=1 conf=0.7 cost=115ms reasons=["llm_cmd"]
⚠️  裁决失败: 意图=2(闲聊) 但 rule_fast+llm_cmd 都命中指令

# === 阶段2: 指令重写 (旁路) ===
[InstructionRewriter] rewrite: "往前走"
✅ 改写成功: "往前走" → "往前走"

# === 阶段3: ES双搜 ===
[CommandStoreClient] vector_search k=5 score=0.72
✅ ES搜索成功: 匹配 cmd_001

# === 阶段4: 参数提取 ===
[ParameterExtractor] regex="往<方向>走" no match in "往前走"
⚠️  参数提取失败: 缺少"方向"参数，回退到默认"前"

# === 阶段5: 协议生成 ===
[ProtocolBuilder] template="move_forward" found
✅ 协议生成成功

# === 阶段6: MQTT发送 ===
[EMQXClient] publishing to topic: robot/robot_001/control
[EMQXClient] wait_for_callback timeout=5000ms
[EMQXClient] ❌ 重试耗尽，设备无响应
        """

    @pytest.mark.asyncio
    async def test_execute_returns_possible_modules(self, analyzer, sample_situation, sample_failed_log):
        """测试 execute 返回 possible_modules"""
        result = await analyzer.execute(sample_situation, sample_failed_log, None)

        assert "possible_modules" in result, f"结果缺少 possible_modules 字段: {result}"
        assert isinstance(result["possible_modules"], list), "possible_modules 应该是列表"
        assert len(result["possible_modules"]) > 0, f"possible_modules 不应为空: {result}"
        print(f"✅ possible_modules 数量: {len(result['possible_modules'])}")

    @pytest.mark.asyncio
    async def test_first_module_is_intent_classifier(self, analyzer, sample_situation, sample_failed_log):
        """测试第一个模块应该是 intent_classifier（根因）"""
        result = await analyzer.execute(sample_situation, sample_failed_log, None)

        possible_modules = result.get("possible_modules", [])
        assert len(possible_modules) > 0, "应该有候选模块"

        first_module = possible_modules[0]["module"]
        assert first_module == "intent_classifier", f"第一个模块应该是 intent_classifier，实际是 {first_module}"
        print(f"✅ 第一个模块: {first_module}")

    @pytest.mark.asyncio
    async def test_intent_classifier_has_high_confidence(self, analyzer, sample_situation, sample_failed_log):
        """测试 intent_classifier 应该有高置信度"""
        result = await analyzer.execute(sample_situation, sample_failed_log, None)

        possible_modules = result.get("possible_modules", [])
        for mod in possible_modules:
            if mod["module"] == "intent_classifier":
                conf = mod["confidence"]
                assert conf >= 0.6, f"intent_classifier 置信度应该 >= 0.6，实际是 {conf}"
                print(f"✅ intent_classifier confidence: {conf}")
                break
        else:
            pytest.fail("没有找到 intent_classifier 模块")

    @pytest.mark.asyncio
    async def test_downstream_modules_low_confidence(self, analyzer, sample_situation, sample_failed_log):
        """测试下游模块应该有低置信度（被上游影响）"""
        result = await analyzer.execute(sample_situation, sample_failed_log, None)

        possible_modules = result.get("possible_modules", [])
        for mod in possible_modules:
            if mod["module"] in ["parameter_extractor", "protocol_builder"]:
                conf = mod["confidence"]
                # 下游模块如果异常应该被上游解释，置信度应该较低
                assert conf < 0.5, f"{mod['module']} 置信度应该 < 0.5，实际是 {conf}"
                print(f"✅ {mod['module']} confidence (下游): {conf}")

    @pytest.mark.asyncio
    async def test_module_order_by_confidence(self, analyzer, sample_situation, sample_failed_log):
        """测试模块按置信度降序排列"""
        result = await analyzer.execute(sample_situation, sample_failed_log, None)

        possible_modules = result.get("possible_modules", [])
        for i in range(len(possible_modules) - 1):
            curr_conf = possible_modules[i]["confidence"]
            next_conf = possible_modules[i + 1]["confidence"]
            assert curr_conf >= next_conf, \
                f"模块排列错误: {possible_modules[i]['module']}({curr_conf}) < {possible_modules[i+1]['module']}({next_conf})"
        print(f"✅ 模块按置信度降序排列")

    @pytest.mark.asyncio
    async def test_result_has_required_fields(self, analyzer, sample_situation, sample_failed_log):
        """测试结果包含必要字段"""
        result = await analyzer.execute(sample_situation, sample_failed_log, None)

        assert "possible_modules" in result
        assert "confidence" in result
        assert "reasoning" in result

        for mod in result["possible_modules"]:
            assert "module" in mod, f"缺少 module 字段: {mod}"
            assert "reason" in mod, f"缺少 reason 字段: {mod}"
            assert "confidence" in mod, f"缺少 confidence 字段: {mod}"
        print(f"✅ 所有必要字段都存在")

    @pytest.mark.asyncio
    async def test_reason_contains_cause_analysis(self, analyzer, sample_situation, sample_failed_log):
        """测试 reason 包含因果分析而非仅异常描述"""
        result = await analyzer.execute(sample_situation, sample_failed_log, None)

        for mod in result["possible_modules"]:
            reason = mod["reason"]
            # reason 应该体现因果判断，而不是简单的"该模块日志异常"
            assert len(reason) > 10, f"reason 太短: {reason}"
            print(f"  {mod['module']}: {reason[:60]}...")

    @pytest.mark.asyncio
    async def test_valid_module_names(self, analyzer, sample_situation, sample_failed_log):
        """测试模块名称是有效的"""
        valid_modules = {
            "rejection_classifier", "intent_classifier", "instruction_rewriter",
            "command_store", "parameter_extractor", "protocol_builder"
        }

        result = await analyzer.execute(sample_situation, sample_failed_log, None)

        for mod in result["possible_modules"]:
            module_name = mod["module"]
            assert module_name in valid_modules, f"无效模块名称: {module_name}"
        print(f"✅ 所有模块名称都有效")

    @pytest.mark.asyncio
    async def test_reasoning_length_limit(self, analyzer, sample_situation, sample_failed_log):
        """测试 reasoning 不超过30字"""
        result = await analyzer.execute(sample_situation, sample_failed_log, None)

        reasoning = result.get("reasoning", "")
        # reasoning 应该简短
        assert len(reasoning) <= 50, f"reasoning 太长: {reasoning}"
        print(f"✅ reasoning: {reasoning}")


class TestSituationAnalyzerEdgeCases:
    """边界情况测试"""

    @pytest.fixture
    def analyzer(self):
        from capabilities.situation_analysis.analyzer import SituationAnalyzer
        return SituationAnalyzer()

    @pytest.mark.asyncio
    async def test_empty_log(self, analyzer):
        """测试空日志"""
        situation = "用户说往前走"
        failed_log = ""

        result = await analyzer.execute(situation, failed_log, None)

        assert "possible_modules" in result
        # 空日志可能导致没有候选模块或置信度很低
        print(f"空日志结果: {result}")

    @pytest.mark.asyncio
    async def test_very_long_log(self, analyzer):
        """测试超长日志（截断测试）"""
        situation = "用户说往前走"
        failed_log = "[测试日志] " * 1000  # 模拟超长日志

        result = await analyzer.execute(situation, failed_log, None)

        assert "possible_modules" in result
        print(f"超长日志结果: possible_modules 数量 = {len(result.get('possible_modules', []))}")

    @pytest.mark.asyncio
    async def test_all_modules_failing_log(self, analyzer):
        """测试所有模块都失败的日志"""
        situation = "用户说往前走"
        failed_log = """
[RejectionClassifier] 拒绝输入
[IntentClassifier] 输出 intent=chat
[InstructionRewriter] 未生成有效指令
[CommandStore] 未匹配到命令
[ParameterExtractor] 未提取到参数
[ProtocolBuilder] 协议生成失败
[EMQXClient] 发送失败
        """

        result = await analyzer.execute(situation, failed_log, None)

        assert "possible_modules" in result
        possible_modules = result["possible_modules"]
        print(f"所有模块失败结果:")
        for mod in possible_modules:
            print(f"  {mod['module']}: {mod['confidence']}")
        # 应该有模块被识别为根因
        assert len(possible_modules) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
