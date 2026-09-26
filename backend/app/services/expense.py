"""费用报销业务规则：状态流转、字段校验与筛选口径都收在这里。

状态机：待提交 → 待审核 → 已通过 → 已打款；待审核可驳回为已驳回，已驳回可重新提交。
已打款是终态：记录封存，任何动作与修改都不能再覆盖它。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "expense"
REQUIRED_FIELDS = ["报销单号", "报销人", "费用类别"]
OPTIONAL_FIELDS = ["发生日期", "报销金额", "票据张数", "所属科目"]
STATUS_ORDER = ["待提交", "待审核", "已通过", "已驳回", "已打款"]
FINAL_STATUS = "已打款"

# 每个动作只允许从特定来源状态发起，杜绝“驳回后直接通过”这类跳变。
ACTION_RULES: dict[str, dict[str, Any]] = {
    "提交报销": {"from": {"待提交", "已驳回"}, "to": "待审核"},
    "审核通过": {"from": {"待审核"}, "to": "已通过"},
    "驳回报销": {"from": {"待审核"}, "to": "已驳回"},
    "确认打款": {"from": {"已通过"}, "to": "已打款"},
}
# 驳回必须留下说明，否则修改意见无处可查。
REMARK_REQUIRED_ACTIONS = {"驳回报销"}


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _sync_status_fields(entry: dict[str, Any]) -> None:
    """业务字段「报销状态」始终镜像内部 status，列表、详情、筛选看的是同一份。"""
    entry["报销状态"] = entry["status"]
    entry["pending"] = entry["status"] in {"待提交", "待审核"}
    entry["abnormal"] = entry["status"] == "已驳回"


class ExpenseService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        reporter: str | None = None,
        category: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("报销单号", ""))]
        if reporter:
            rows = [row for row in rows if reporter in str(row.get("报销人", ""))]
        if category:
            rows = [row for row in rows if category in str(row.get("费用类别", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if _is_blank(values.get(field))]
        if missing:
            return None, missing
        with store.lock:
            entry = {"id": store.next_id(MODULE)}
            for field in REQUIRED_FIELDS + OPTIONAL_FIELDS:
                value = values.get(field)
                if not _is_blank(value):
                    entry[field] = value
            entry["status"] = STATUS_ORDER[0]
            entry["最近说明"] = ""
            entry["流转记录"] = []
            _sync_status_fields(entry)
            store.rows(MODULE).append(entry)
        return entry, []

    def update_entry(
        self, entry_id: int, values: dict[str, Any], remark: str | None = None
    ) -> tuple[dict[str, Any] | None, str]:
        """修改报销单：空值不覆盖已有内容；已打款记录封存，整体只读。"""
        with store.lock:
            entry = store.find(MODULE, entry_id)
            if entry is None:
                return None, f"报销单 {entry_id} 不存在或已归档"
            if entry.get("status") == FINAL_STATUS:
                return None, f"报销单 {entry_id} 已打款，记录已封存，不能再修改"
            changed: list[str] = []
            for field in REQUIRED_FIELDS + OPTIONAL_FIELDS:
                value = values.get(field)
                if _is_blank(value):
                    continue  # 空值不覆盖已有内容
                if entry.get(field) != value:
                    entry[field] = value
                    changed.append(field)
            if not changed:
                return entry, "没有需要更新的字段"
            remark_text = (remark or "").strip()
            if remark_text:
                entry["最近说明"] = remark_text
            note = "、".join(changed)
            if remark_text:
                note = f"{note}；{remark_text}"
            self._append_history(entry, "修改明细", note)
        return entry, f"已更新字段：{'、'.join(changed)}"

    def run_action(
        self, entry_id: int, action: str, remark: str | None = None
    ) -> tuple[dict[str, Any] | None, str]:
        with store.lock:
            entry = store.find(MODULE, entry_id)
            if entry is None:
                return None, f"报销单 {entry_id} 不存在或已归档"
            if action not in ACTION_RULES:
                return None, f"动作「{action}」不属于费用报销可执行范围"
            current = str(entry.get("status") or "")
            if current == FINAL_STATUS:
                return None, f"报销单 {entry_id} 已打款，流程已终结，不能再执行任何动作"
            rule = ACTION_RULES[action]
            if current not in rule["from"]:
                allowed = "、".join(sorted(rule["from"]))
                return None, f"当前状态为「{current}」，「{action}」只能从「{allowed}」发起"
            remark_text = (remark or "").strip()
            if action in REMARK_REQUIRED_ACTIONS and not remark_text:
                return None, f"执行「{action}」必须填写说明，避免修改意见丢失"
            entry["status"] = rule["to"]
            _sync_status_fields(entry)
            if remark_text:
                entry["最近说明"] = remark_text
            self._append_history(entry, action, remark_text or "—")
        return entry, f"报销单已{action}"

    @staticmethod
    def _append_history(entry: dict[str, Any], action: str, note: str) -> None:
        history = entry.setdefault("流转记录", [])
        history.append({
            "时间": datetime.now().isoformat(timespec="seconds"),
            "动作": action,
            "状态": entry.get("status"),
            "说明": note,
        })
