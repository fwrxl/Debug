"""记忆模块 - 存储分析过程中的中间状态和迭代记录"""
from typing import Dict, Any, List, Optional
from datetime import datetime


class ConversationEntry:
    """LLM 对话记录 - 完整记录一次 LLM 输入输出"""

    def __init__(
        self,
        step: str,
        role: str,  # "user" or "assistant"
        content: str,
    ):
        self.step = step
        self.role = role
        self.content = content
        self.timestamp = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step": self.step,
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
        }


class CandidateModule:
    """可疑模块 - 记录候选模块及其累积置信度"""

    def __init__(
        self,
        module: str,
        reason: str,
        confidence: float,
    ):
        self.module = module
        self.reason = reason
        self.confidence = confidence

    def to_dict(self) -> Dict[str, Any]:
        return {
            "module": self.module,
            "reason": self.reason,
            "confidence": self.confidence,
        }


class Attempt:
    """一次迭代尝试记录"""

    def __init__(
        self,
        step: str,
        evidence: Optional[Any] = None,
        success: bool = False,
        target_module: str = None,
        confidence: float = 0.0,
    ):
        self.step = step
        self.evidence = evidence
        self.success = success
        self.target_module = target_module
        self.confidence = confidence
        self.timestamp = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step": self.step,
            "evidence": self.evidence,
            "success": self.success,
            "target_module": self.target_module,
            "confidence": self.confidence,
            "timestamp": self.timestamp,
        }


class ContextMemory:
    """
    上下文记忆 - 存储对话历史

    用途：记录 LLM 对话历史
    """

    def __init__(self):
        self.conversation: List[Dict[str, Any]] = []  # 完整 LLM 对话记录

    def add_conversation(self, step: str, role: str, content: str):
        """
        添加 LLM 对话记录

        Args:
            step: 当前步骤
            role: "user" 或 "assistant"
            content: 对话内容（完整输入或输出）
        """
        entry = ConversationEntry(step, role, content)
        self.conversation.append(entry.to_dict())

    def get_conversation(self) -> List[Dict[str, Any]]:
        """获取完整对话记录"""
        return self.conversation

    def clear(self):
        """清空上下文记忆"""
        self.conversation = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "conversation": self.conversation,
        }


class IterationMemory:
    """
    迭代记忆 - 存储历史尝试记录

    用途：让 Agent 知道"已试过什么"，避免重复
    """

    def __init__(self):
        self.attempts: List[Dict[str, Any]] = []

    def add_attempt(
        self,
        step: str,
        evidence: Optional[Any] = None,
        success: bool = False,
        target_module: str = None,
        confidence: float = 0.0,
    ) -> Attempt:
        """添加一次尝试记录"""
        attempt = Attempt(step, evidence, success, target_module, confidence)
        self.attempts.append(attempt.to_dict())
        return attempt

    def get_failed_attempts(self) -> List[Dict[str, Any]]:
        """获取所有失败的尝试"""
        return [a for a in self.attempts if not a.get("success", False)]

    def get_successful_attempts(self) -> List[Dict[str, Any]]:
        """获取所有成功的尝试"""
        return [a for a in self.attempts if a.get("success", False)]

    def get_attempts_by_step(self, step: str) -> List[Dict[str, Any]]:
        """获取某步骤的所有尝试"""
        return [a for a in self.attempts if a.get("step") == step]

    def clear(self):
        """清空迭代记忆"""
        self.attempts = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "attempts": self.attempts,
        }


class MemoryModule:
    """
    统一记忆模块

    设计原则：
    - context: 存储对话历史
    - iteration: 存储历史尝试记录
    - possible_modules: 共享的可疑模块列表，实时更新累积置信度
    - 每个新输入重置
    """

    def __init__(self):
        self.context = ContextMemory()
        self.iteration = IterationMemory()
        self.possible_modules: List[CandidateModule] = []
        self.created_at = datetime.now().isoformat()
        # 存储 bug_module 和 owner_open_id（方便跨步骤访问）
        self._bug_module: Optional[str] = None
        self._owner_open_id: Optional[str] = None
        # 分支记忆：key 是模块名，value 包含该分支的 context 和 iteration
        self.branch_memories: Dict[str, Dict[str, Any]] = {}

    def reset(self):
        """重置记忆（新输入开始时调用）"""
        self.context.clear()
        self.iteration.clear()
        self.possible_modules = []
        self.created_at = datetime.now().isoformat()
        self._bug_module = None
        self._owner_open_id = None

    # ========== 上下文记忆接口 ==========

    def add_conversation(self, step: str, role: str, content: str):
        """
        添加 LLM 对话记录

        Args:
            step: 当前步骤
            role: "user" 或 "assistant"
            content: 对话内容（完整输入或输出）
        """
        self.context.add_conversation(step, role, content)

    # ========== 候选模块接口 ==========

    def initialize_candidates(self, candidates: List[Dict[str, Any]]):
        """
        初始化候选模块（情景分析后调用一次）

        Args:
            candidates: 情景分析返回的 possible_modules 列表
            格式: [{"module": "xxx", "reason": "...", "confidence": 0.9}, ...]
        """
        for c in candidates:
            module = c.get("module", "")
            reason = c.get("reason", "")
            confidence = c.get("confidence", 0.0)
            self.possible_modules.append(CandidateModule(module, reason, confidence))

    def update_module_confidence(self, target_module: str, delta: float):
        """
        更新模块置信度（能力执行后调用）

        Args:
            target_module: 目标模块 ID
            delta: 置信度增量
        """
        for candidate in self.possible_modules:
            if candidate.module == target_module:
                candidate.confidence += delta
                break

    def get_candidate_modules(self) -> List[CandidateModule]:
        """获取可疑模块列表"""
        return self.possible_modules

    def get_sorted_modules(self) -> List[CandidateModule]:
        """获取按置信度排序的可疑模块列表"""
        return sorted(self.possible_modules, key=lambda x: x.confidence, reverse=True)

    # ========== 迭代记忆接口 ==========

    def add_attempt(
        self,
        step: str,
        evidence: Optional[Any] = None,
        success: bool = False,
        target_module: str = None,
        confidence: float = 0.0,
    ) -> Attempt:
        """
        添加一次迭代尝试

        Args:
            step: 哪一步（如 log_localization）
            evidence: 实际证据（能力返回的结果）
            success: 是否达到目的
            target_module: 本次验证的模块
            confidence: 本次能力返回的置信度
        """
        return self.iteration.add_attempt(step, evidence, success, target_module, confidence)

    # ========== 查询接口 ==========

    def get_conversation(self) -> List[Dict[str, Any]]:
        """获取完整对话记录"""
        return self.context.get_conversation()

    def get_failed_attempts(self) -> List[Dict[str, Any]]:
        """获取失败的尝试记录"""
        return self.iteration.get_failed_attempts()

    def get_attempts_by_step(self, step: str) -> List[Dict[str, Any]]:
        """获取某步骤的尝试记录"""
        return self.iteration.get_attempts_by_step(step)

    def get_latest_attempt(self, step_name: str) -> Optional[Dict[str, Any]]:
        """获取某步骤的最新尝试记录"""
        attempts = self.iteration.get_attempts_by_step(step_name)
        return attempts[-1] if attempts else None

    # ========== Bug Module 接口 ==========

    def set_bug_module(self, module_name: str):
        """设置 bug_module（供其他步骤使用）"""
        self._bug_module = module_name

    def get_bug_module(self) -> Optional[str]:
        """获取 bug_module"""
        return self._bug_module

    # ========== Owner Open ID 接口 ==========

    def set_owner_open_id(self, open_id: str):
        """设置 owner_open_id（供飞书通知使用）"""
        self._owner_open_id = open_id

    def get_owner_open_id(self) -> Optional[str]:
        """获取 owner_open_id"""
        return self._owner_open_id

    def to_dict(self) -> Dict[str, Any]:
        """导出完整记忆"""
        return {
            "created_at": self.created_at,
            "context": self.context.to_dict(),
            "iteration": self.iteration.to_dict(),
            "possible_modules": [c.to_dict() for c in self.possible_modules],
        }