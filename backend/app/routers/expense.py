"""费用报销接口：维护报销单，覆盖提交报销、审核通过、驳回报销、确认打款等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.expense import ExpenseService

router = APIRouter(prefix="/api/expense", tags=["费用报销"])

service = ExpenseService()

LIST_FIELDS = ["报销单号", "报销人", "费用类别", "发生日期", "报销金额", "票据张数", "所属科目", "报销状态"]
STATUSES = ["待提交", "待审核", "已通过", "已驳回", "已打款"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按报销单号检索"),
    status: str | None = Query(default=None, description="待提交、待审核、已通过、已驳回、已打款"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按报销单号与状态过滤费用报销列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出费用报销清单：返回当前过滤条件下的全量数据。

    注意必须注册在 /{entry_id} 之前，否则 "export" 会被当成单据编号解析。
    """
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "expense", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条报销单明细（含审核记录）；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"报销单 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条报销单，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        raise HTTPException(status_code=400, detail=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="报销单已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条报销单执行状态流转；不合法的动作按 400/404/409 返回并说明原因。

    请求体：values.action 为动作名，values 里其余非空字段视为随动作一起
    保存的修改（空值不会覆盖已有内容），remark 为修改说明，驳回时必填。
    """
    action = str(payload.values.get("action") or "").strip()
    changes = {key: value for key, value in payload.values.items() if key != "action"}
    entry, message, code = service.run_action(
        entry_id, action, remark=payload.remark, changes=changes,
    )
    if entry is None:
        raise HTTPException(status_code=code, detail=message)
    return ActionResult(ok=True, message=message, entry=entry)
