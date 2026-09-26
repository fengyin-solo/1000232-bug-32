"""费用报销业务规则：状态流转、字段校验与筛选口径都收在这里。

报销单的完整环节：登记(待提交) → 提交报销(待审核) → 审核通过(已通过)
→ 确认打款(已打款，终态)；待审核时也可驳回报销(已驳回)，修改后重新提交。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "expense"
REQUIRED_FIELDS = ["报销单号", "报销人", "费用类别"]
EDITABLE_FIELDS = ["报销单号", "报销人", "费用类别", "发生日期", "报销金额", "票据张数", "所属科目"]
STATUS_ORDER = ["待提交", "待审核", "已通过", "已驳回", "已打款"]
STATUS_FIELD = "报销状态"
TERMINAL_STATUS = "已打款"

# 状态机：动作 -> (允许发起的当前状态, 目标状态)。不在表里的流转一律拒绝，
# 例如「已驳回」不能直接「审核通过」，必须先重新提交回到「待审核」。
TRANSITIONS: dict[str, tuple[frozenset[str], str]] = {
    "提交报销": (frozenset({"待提交", "已驳回"}), "待审核"),
    "审核通过": (frozenset({"待审核"}), "已通过"),
    "驳回报销": (frozenset({"待审核"}), "已驳回"),
    "确认打款": (frozenset({"已通过"}), "已打款"),
}
# 这些动作必须填写修改说明，说明会写进审核记录随单据保留。
REMARK_REQUIRED = {"驳回报销"}


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _present(row: dict[str, Any]) -> dict[str, Any]:
    """对外投影：列表、详情、导出共用同一份口径。

    工作流状态只存在 status 里，展示列「报销状态」在这里同步，
    保证列表页、详情接口看到的永远是同一个状态。
    """
    item = dict(row)
    item[STATUS_FIELD] = row.get("status")
    item.setdefault("审核记录", [])
    return item


class ExpenseService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("报销单号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [_present(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        return _present(row) if row is not None else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if _is_blank(values.get(field))]
        if missing:
            return None, missing
        with store.lock:
            rows = store.rows(MODULE)
            entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
            # 空值不落地：只登记确实填了的字段，避免把 None 写进单据
            for field in EDITABLE_FIELDS:
                value = values.get(field)
                if not _is_blank(value):
                    entry[field] = value
            entry["status"] = STATUS_ORDER[0]
            entry["pending"] = True
            entry["abnormal"] = False
            entry["审核记录"] = []
            rows.append(entry)
        return _present(entry), []

    def run_action(
        self,
        entry_id: int,
        action: str,
        *,
        remark: str | None = None,
        changes: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str, int]:
        """执行状态流转；返回 (单据, 提示语, HTTP 状态码)。

        整段「读取-校验-写入」都在锁内完成：并发提交时只有第一个请求能
        通过校验，后到的请求会看到已经流转过的状态并被拦下，已打款记录
        因此不会被并发或空值覆盖。
        """
        with store.lock:
            entry = store.find(MODULE, entry_id)
            if entry is None:
                return None, f"报销单 {entry_id} 不存在或已归档", 404
            if action not in TRANSITIONS:
                return None, f"动作「{action}」不属于费用报销可执行范围", 400
            current = str(entry.get("status") or "")
            if current == TERMINAL_STATUS:
                return None, f"报销单 {entry_id} 已打款归档，任何动作和修改都不会生效", 409
            allowed_from, target = TRANSITIONS[action]
            if current not in allowed_from:
                return None, f"当前状态「{current}」不能执行「{action}」，请按流程逐级流转", 409
            note = (remark or "").strip()
            if action in REMARK_REQUIRED and not note:
                return None, f"执行「{action}」必须填写修改说明，说明会随单据保留", 400
            # 空值不覆盖：只合并确实填了内容的字段，且此时单据一定未打款
            if changes:
                for field in EDITABLE_FIELDS:
                    value = changes.get(field)
                    if not _is_blank(value):
                        entry[field] = value
            entry["status"] = target
            entry["pending"] = target != TERMINAL_STATUS
            entry["abnormal"] = target == "已驳回"
            entry.setdefault("审核记录", []).append({
                "时间": datetime.now().isoformat(timespec="seconds"),
                "动作": action,
                "操作前状态": current,
                "操作后状态": target,
                "修改说明": note,
            })
            return _present(entry), f"报销单已{action}", 200
