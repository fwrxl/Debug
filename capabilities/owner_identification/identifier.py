"""责任人识别能力 - 识别问题模块的负责人"""
from typing import Dict, Any, Optional, List

from integrations.module_owner_table import ModuleOwnerTable
from integrations.llm_client import get_llm_client


class OwnerIdentifier:
    """
    责任人识别能力
    负责根据问题模块识别对应的负责人
    """

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self._table = ModuleOwnerTable()
        self.llm_client = get_llm_client()

    async def execute(
        self,
        situation: str,
        failed_log: str,
        memory: Any,
    ) -> Dict[str, Any]:
        """
        执行责任人识别

        Args:
            situation: 情景描述
            failed_log: 失败日志
            memory: 记忆模块

        Returns:
            识别结果
        """
        # 首先检查 memory 是否已经设置了 bug_module（由 Finalization 阶段设置）
        bug_module = memory.get_bug_module() if hasattr(memory, 'get_bug_module') else None

        # 如果 memory 中没有 bug_module，尝试从 attempts 中获取
        if not bug_module:
            sit_attempts = memory.iteration.get_attempts_by_step("situation_analysis") if hasattr(memory, 'iteration') else []
            log_attempts = memory.iteration.get_attempts_by_step("log_localization") if hasattr(memory, 'iteration') else []

            # 获取 situation_analysis 和 log_localization 的结果
            situation_result = sit_attempts[-1]["evidence"] if sit_attempts else {}
            log_result = log_attempts[-1]["evidence"] if log_attempts else {}

            # 从结果中提取可能的模块
            possible_modules = situation_result.get("possible_modules", [])
            failed_module = log_result.get("failed_module")

            # 综合分析确定问题模块
            if failed_module and failed_module not in ("unknown", ""):
                bug_module = failed_module
            if not bug_module and possible_modules:
                first_module = possible_modules[0] if possible_modules else None
                if first_module:
                    bug_module = first_module.get("module") if isinstance(first_module, dict) else first_module

            # 如果还是没有，使用 LLM 从日志中提取
            if not bug_module:
                bug_module = self._extract_module_from_log(situation, failed_log, possible_modules, failed_module)

        # 获取负责人信息
        owner_info = self._get_owner(bug_module) if bug_module else None

        result = {
            "bug_module": bug_module,
            "owner_info": owner_info,
            "has_owner": owner_info is not None,
        }

        # 将结果写入 memory
        if owner_info and owner_info.get('open_id') and hasattr(memory, 'set_owner_open_id'):
            memory.set_owner_open_id(owner_info['open_id'])

        return result

    def _extract_module_from_log(
        self,
        situation: str,
        failed_log: str,
        possible_modules: List[str] = None,
        failed_module: str = None,
    ) -> Optional[str]:
        """使用 LLM 从日志中提取问题模块（必须返回 xlsx 中存在的模块）"""
        # 获取 xlsx 中的所有模块
        all_modules = self._table.get_all_modules()
        valid_module_ids = [m.get("模块ID") for m in all_modules if m.get("模块ID")]

        if not valid_module_ids:
            return None

        modules_str = ", ".join(valid_module_ids)

        prompt = f"""## 任务

综合分析以下信息，识别出最可能出问题的模块名称。

## 输入信息

情景描述: {situation}
测试目标: 无

## 情景分析给出的可能模块

{possible_modules if possible_modules else "无"}

## 日志分析给出的失败模块

{failed_module if failed_module else "无"}

## 失败日志摘要

{failed_log[:2000]}

## 有效模块列表（必须从中选择，禁止输出列表之外的模块）

{modules_str}

## 输出要求

1. 综合情景分析和日志分析的结果，从有效模块列表中选择最可能出问题的模块
2. 如果 failed_module 在有效列表中，优先使用
3. 如果 failed_module 不在列表中但 possible_modules 在列表中，使用 possible_modules
4. 如果都不在，从日志中分析最可能的模块（只从有效列表中选择）
5. 只返回一个模块名称（小写），不要其他内容
6. 如果无法确定，返回 none（不是 unknown）

**严格禁止**：输出任何不在有效模块列表中的模块名称"""

        try:
            messages = [
                {"role": "system", "content": "你是模块识别专家，只返回有效模块列表中的模块。"},
                {"role": "user", "content": prompt}
            ]
            response = self.llm_client.chat(messages, max_tokens=50)
            module_name = response.strip().lower()

            # 验证模块名称是否在有效列表中
            if module_name and module_name in valid_module_ids:
                return module_name

            # 如果 LLM 返回的不是有效模块，尝试使用 situation_analysis 的 possible_modules
            if possible_modules:
                for pm in possible_modules:
                    pm_lower = pm.lower()
                    if pm_lower in valid_module_ids:
                        return pm_lower
                    # 处理可能的变体（如 intent_classifier vs intent-classifier）
                    for vm in valid_module_ids:
                        if vm.replace("_", "-") == pm_lower.replace("_", "-"):
                            return vm

            # 如果都不行，尝试日志字符串匹配（针对日志中出现的模块名）
            log_lower = failed_log.lower()
            for vm in valid_module_ids:
                if vm in log_lower:
                    return vm

        except Exception as e:
            print(f"LLM 提取模块失败: {e}")

        return None

    def _get_owner(self, module_name: str) -> Optional[Dict[str, Any]]:
        """获取模块负责人"""
        if not module_name:
            return None
        return self._table.get_owner(module_name)

    def reload_table(self):
        """重新加载表格数据"""
        self._table.reload()