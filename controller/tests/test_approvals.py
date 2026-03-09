from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

from app.approvals import ApprovalRequiredError
from app.browser_manager import BrowserManager, BrowserSession
from app.config import Settings
from app.models import BrowserActionDecision


class FakePage:
    def __init__(self, url: str = "https://example.com"):
        self.url = url

    async def title(self) -> str:
        return "Example Domain"


class ApprovalQueueTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.settings = Settings(_env_file=None)
        self.settings.artifact_root = str(root / "artifacts")
        self.settings.upload_root = str(root / "uploads")
        self.settings.auth_root = str(root / "auth")
        self.settings.approval_root = str(root / "approvals")
        self.manager = BrowserManager(self.settings)

        artifact_dir = Path(self.settings.artifact_root) / "session-1"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        self.session = BrowserSession(
            id="session-1",
            name="session-1",
            created_at=datetime.now(UTC),
            context=object(),  # type: ignore[arg-type]
            page=FakePage(),  # type: ignore[arg-type]
            artifact_dir=artifact_dir,
            takeover_url="http://127.0.0.1:6080/vnc.html",
            trace_path=artifact_dir / "trace.zip",
        )
        self.manager.sessions[self.session.id] = self.session

    async def asyncTearDown(self) -> None:
        self.tempdir.cleanup()

    async def test_upload_requires_pending_approval_then_executes(self) -> None:
        upload_path = Path(self.settings.upload_root) / "demo.txt"
        upload_path.parent.mkdir(parents=True, exist_ok=True)
        upload_path.write_text("demo", encoding="utf-8")

        self.manager._run_action = AsyncMock(return_value={"action": "upload"})  # type: ignore[method-assign]

        with self.assertRaises(ApprovalRequiredError) as ctx:
            await self.manager.upload(
                self.session.id,
                selector='input[type="file"]',
                file_path="demo.txt",
                approved=False,
            )

        approval = ctx.exception.approval
        self.assertEqual(approval.kind, "upload")
        self.assertEqual(approval.status, "pending")

        await self.manager.approve(approval.id, comment="looks good")
        result = await self.manager.upload(
            self.session.id,
            selector='input[type="file"]',
            file_path="demo.txt",
            approved=False,
            approval_id=approval.id,
        )

        self.assertEqual(result["action"], "upload")
        stored = await self.manager.get_approval(approval.id)
        self.assertEqual(stored["status"], "executed")

    async def test_sensitive_decision_creates_queue_item_and_execute_approval_runs_action(self) -> None:
        self.manager.click = AsyncMock(return_value={"action": "click"})  # type: ignore[method-assign]

        decision = BrowserActionDecision(
            action="click",
            reason="This button submits a payment",
            element_id="op-pay",
            risk_category="payment",
        )

        with self.assertRaises(ApprovalRequiredError) as ctx:
            await self.manager.execute_decision(self.session.id, decision)

        approval = ctx.exception.approval
        self.assertEqual(approval.kind, "payment")
        await self.manager.approve(approval.id, comment="approved")

        result = await self.manager.execute_approval(approval.id)

        self.assertEqual(result["approval"]["status"], "executed")
        self.manager.click.assert_awaited_once_with(
            self.session.id,
            selector=None,
            element_id="op-pay",
            x=None,
            y=None,
        )
