"""本地 Excel 模块负责人映射表读取"""
import os
from typing import Dict, List, Optional
from pathlib import Path

from openpyxl import load_workbook

from integrations.config_manager import get_config


class ModuleOwnerTable:
    """模块负责人映射表"""

    def __init__(self, file_path: Optional[str] = None):
        if file_path is None:
            config = get_config()
            file_path = config.feishu.module_owner_table or "data/module_owner_mapping.xlsx"

        self.file_path = file_path
        self._data: List[Dict[str, str]] = []
        self._load()

    def _load(self):
        """加载 Excel 数据"""
        if not os.path.exists(self.file_path):
            self._data = []
            return

        wb = load_workbook(self.file_path, read_only=True)
        ws = wb.active

        # 读取表头
        headers = [cell.value for cell in ws[1]]
        if not headers:
            wb.close()
            self._data = []
            return

        # 读取数据行
        self._data = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            if row[0] is None:  # 跳过空行
                continue
            record = dict(zip(headers, row))
            self._data.append(record)

        wb.close()

    def get_owner(self, module_id: str) -> Optional[Dict[str, str]]:
        """
        根据模块ID获取负责人信息

        Args:
            module_id: 模块ID，如 "intent_classifier"

        Returns:
            负责人信息字典，包含 name, open_id, email 等
        """
        for record in self._data:
            if record.get("模块ID") == module_id:
                return {
                    "name": record.get("负责人姓名"),
                    "open_id": record.get("飞书Open ID"),
                    "email": record.get("邮箱"),
                    "phone": record.get("手机号"),
                    "department": record.get("部门"),
                    "level": record.get("级别"),
                    "status": record.get("状态"),
                    "remark": record.get("备注"),
                }
        return None

    def get_all_modules(self) -> List[Dict[str, str]]:
        """获取所有模块信息"""
        return self._data.copy()

    def reload(self):
        """重新加载数据"""
        self._load()


def create_default_table(file_path: str = "data/module_owner_mapping.xlsx"):
    """
    创建默认的模块负责人映射表

    Args:
        file_path: 文件路径
    """
    from openpyxl import Workbook

    # 确保目录存在
    Path(file_path).parent.mkdir(parents=True, exist_ok=True)

    wb = Workbook()
    ws = wb.active
    ws.title = "模块负责人映射"

    # 写入表头
    headers = ["模块ID", "模块名称", "负责人姓名", "飞书Open ID", "邮箱", "手机号", "部门", "级别", "状态", "备注"]
    ws.append(headers)

    # 写入示例数据
    sample_data = [
        ["rejection_classifier", "拒绝分类器", "张三", "ou_xxx1", "zhangsan@example.com", "138xxxx", "AI平台部", 1, "正常", ""],
        ["intent_classifier", "意图分类器", "李四", "ou_xxx2", "lisi@example.com", "139xxxx", "AI平台部", 1, "正常", ""],
        ["instruction_rewriter", "指令改写器", "王五", "ou_xxx3", "wangwu@example.com", "137xxxx", "AI平台部", 2, "正常", ""],
        ["command_store", "命令存储", "赵六", "ou_xxx4", "zhaoliu@example.com", "136xxxx", "AI平台部", 1, "正常", ""],
        ["parameter_extractor", "参数提取器", "孙七", "ou_xxx5", "sunqi@example.com", "135xxxx", "AI平台部", 2, "正常", ""],
        ["protocol_builder", "协议构建器", "周八", "ou_xxx6", "zhouba@example.com", "134xxxx", "AI平台部", 2, "正常", ""],
    ]

    for row in sample_data:
        ws.append(row)

    wb.save(file_path)
    print(f"✓ 模块负责人映射表已创建: {file_path}")


if __name__ == "__main__":
    # 创建默认表格
    create_default_table("data/module_owner_mapping.xlsx")

    # 测试读取
    table = ModuleOwnerTable("data/module_owner_mapping.xlsx")

    print("\n所有模块:")
    for module in table.get_all_modules():
        print(f"  - {module['模块ID']}: {module['负责人姓名']}")

    print("\n查询 'intent_classifier':")
    owner = table.get_owner("intent_classifier")
    print(f"  {owner}")