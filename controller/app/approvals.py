from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import uuid4

from .models import ApprovalKind, ApprovalRecord, ApprovalStatus, BrowserActionDecision


class ApprovalRequiredError(RuntimeError):
    def __init__(self, approval: ApprovalRecord, message: str | None = None):
        self.approval = approval
        self.payload = {
            "status": "approval_required",
            "message": message or f"{approval.kind} actions require human approval",
            "approval": approval.model_dump(),
        }
        super().__init__(self.payload["message"])


class ApprovalStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    async def list(
        self,
        *,
        status: ApprovalStatus | None = None,
        session_id: str | None = None,
    ) -> list[ApprovalRecord]:
        return await asyncio.to_thread(self._list_sync, status, session_id)

    async def get(self, approval_id: str) -> ApprovalRecord:
        return await asyncio.to_thread(self._read_sync, approval_id)

    async def create_or_reuse_pending(
        self,
        *,
        session_id: str,
        kind: ApprovalKind,
        reason: str,
        action: BrowserActionDecision,
        observation: dict | None = None,
    ) -> ApprovalRecord:
        async with self._lock:
            existing = await asyncio.to_thread(
                self._find_matching_pending_sync,
                session_id,
                kind,
                action,
            )
            if existing is not None:
                return existing

            now = self._timestamp()
            approval = ApprovalRecord(
                id=uuid4().hex[:12],
                session_id=session_id,
                kind=kind,
                status="pending",
                created_at=now,
                updated_at=now,
                reason=reason,
                action=action,
                observation=observation,
            )
            await asyncio.to_thread(self._write_sync, approval)
            return approval

    async def approve(self, approval_id: str, comment: str | None = None) -> ApprovalRecord:
        return await self._transition(approval_id, status="approved", comment=comment)

    async def reject(self, approval_id: str, comment: str | None = None) -> ApprovalRecord:
        return await self._transition(approval_id, status="rejected", comment=comment)

    async def mark_executed(self, approval_id: str) -> ApprovalRecord:
        async with self._lock:
            approval = await asyncio.to_thread(self._read_sync, approval_id)
            if approval.status != "approved":
                raise PermissionError(f"approval {approval_id} is not approved")
            now = self._timestamp()
            approval.status = "executed"
            approval.updated_at = now
            approval.executed_at = now
            await asyncio.to_thread(self._write_sync, approval)
            return approval

    async def require_approved(
        self,
        *,
        approval_id: str,
        session_id: str,
        kind: ApprovalKind,
        action: BrowserActionDecision,
    ) -> ApprovalRecord:
        approval = await self.get(approval_id)
        if approval.session_id != session_id:
            raise PermissionError(f"approval {approval_id} does not belong to session {session_id}")
        if approval.kind != kind:
            raise PermissionError(f"approval {approval_id} does not cover {kind}")
        if approval.status != "approved":
            raise PermissionError(f"approval {approval_id} is not approved")
        if not self._actions_match(approval.action, action):
            raise PermissionError(f"approval {approval_id} does not match the requested action")
        return approval

    async def _transition(
        self,
        approval_id: str,
        *,
        status: ApprovalStatus,
        comment: str | None,
    ) -> ApprovalRecord:
        async with self._lock:
            approval = await asyncio.to_thread(self._read_sync, approval_id)
            if approval.status == "executed":
                raise PermissionError(f"approval {approval_id} has already been executed")
            now = self._timestamp()
            approval.status = status
            approval.updated_at = now
            approval.decided_at = now
            approval.decision_comment = comment
            await asyncio.to_thread(self._write_sync, approval)
            return approval

    def _list_sync(
        self,
        status: ApprovalStatus | None,
        session_id: str | None,
    ) -> list[ApprovalRecord]:
        approvals: list[ApprovalRecord] = []
        for path in sorted(self.root.glob("*.json"), reverse=True):
            try:
                approval = ApprovalRecord.model_validate_json(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if status is not None and approval.status != status:
                continue
            if session_id is not None and approval.session_id != session_id:
                continue
            approvals.append(approval)
        approvals.sort(key=lambda item: (item.created_at, item.id), reverse=True)
        return approvals

    def _find_matching_pending_sync(
        self,
        session_id: str,
        kind: ApprovalKind,
        action: BrowserActionDecision,
    ) -> ApprovalRecord | None:
        for approval in self._list_sync(status="pending", session_id=session_id):
            if approval.kind == kind and self._actions_match(approval.action, action):
                return approval
        return None

    def _read_sync(self, approval_id: str) -> ApprovalRecord:
        path = self._path(approval_id)
        if not path.exists():
            raise KeyError(approval_id)
        return ApprovalRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def _write_sync(self, approval: ApprovalRecord) -> None:
        path = self._path(approval.id)
        tmp_path = path.with_suffix(".json.tmp")
        tmp_path.write_text(
            approval.model_dump_json(indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(path)

    def _path(self, approval_id: str) -> Path:
        return self.root / f"{approval_id}.json"

    @staticmethod
    def _actions_match(left: BrowserActionDecision, right: BrowserActionDecision) -> bool:
        excluded = {"reason", "confidence"}
        return left.model_dump(exclude=excluded) == right.model_dump(exclude=excluded)

    @staticmethod
    def _timestamp() -> str:
        from datetime import UTC, datetime

        return datetime.now(UTC).isoformat().replace("+00:00", "Z")
