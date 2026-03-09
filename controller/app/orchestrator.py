from __future__ import annotations

from typing import Any

import httpx

from .approvals import ApprovalRequiredError
from .browser_manager import BrowserManager
from .models import AgentRunResult, AgentStepResult, BrowserActionDecision, ProviderName
from .provider_registry import ProviderRegistry
from .providers.base import ProviderAPIError, ProviderDecision


class BrowserOrchestrator:
    def __init__(self, manager: BrowserManager, registry: ProviderRegistry):
        self.manager = manager
        self.registry = registry

    def list_providers(self):
        return self.registry.list()

    async def step(
        self,
        *,
        session_id: str,
        provider_name: ProviderName,
        goal: str,
        observation_limit: int = 40,
        context_hints: str | None = None,
        upload_approved: bool = False,
        approval_id: str | None = None,
        provider_model: str | None = None,
        previous_steps: list[AgentStepResult] | None = None,
    ) -> AgentStepResult:
        adapter = self.registry.get(provider_name)
        model_name = provider_model or adapter.default_model
        observation = await self.manager.observe(session_id, limit=observation_limit)
        prompt_history = self._summarize_previous_steps(previous_steps or [])

        try:
            provider_decision = await adapter.decide(
                goal=goal,
                observation=observation,
                context_hints=context_hints,
                previous_steps=prompt_history,
                model_override=provider_model,
            )
            result = await self._execute_decision(
                session_id=session_id,
                goal=goal,
                observation=observation,
                provider_decision=provider_decision,
                upload_approved=upload_approved,
                approval_id=approval_id,
            )
        except ApprovalRequiredError as exc:
            result = AgentStepResult(
                provider=provider_name,
                model=model_name,
                goal=goal,
                status="approval_required",
                observation=observation,
                decision=provider_decision.decision.model_dump(),
                execution=exc.payload,
                usage=provider_decision.usage,
                raw_text=provider_decision.raw_text,
                error=None,
                error_code=None,
            )
        except ProviderAPIError as exc:
            result = AgentStepResult(
                provider=provider_name,
                model=model_name,
                goal=goal,
                status="error",
                observation=observation,
                decision={},
                execution=None,
                usage=None,
                raw_text=None,
                error=str(exc),
                error_code=exc.status_code or (503 if exc.retryable else 502),
            )
        except Exception as exc:
            error_code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            result = AgentStepResult(
                provider=provider_name,
                model=model_name,
                goal=goal,
                status="error",
                observation=observation,
                decision={},
                execution=None,
                usage=None,
                raw_text=None,
                error=str(exc),
                error_code=error_code,
            )

        await self._append_agent_log(session_id, "agent_steps.jsonl", result.model_dump())
        return result

    async def run(
        self,
        *,
        session_id: str,
        provider_name: ProviderName,
        goal: str,
        max_steps: int,
        observation_limit: int = 40,
        context_hints: str | None = None,
        upload_approved: bool = False,
        approval_id: str | None = None,
        provider_model: str | None = None,
    ) -> AgentRunResult:
        steps: list[AgentStepResult] = []
        final_status = "max_steps_reached"
        adapter = self.registry.get(provider_name)
        model_name = provider_model or adapter.default_model

        for index in range(max_steps):
            step_result = await self.step(
                session_id=session_id,
                provider_name=provider_name,
                goal=goal,
                observation_limit=observation_limit,
                context_hints=context_hints,
                upload_approved=upload_approved,
                approval_id=approval_id,
                provider_model=provider_model,
                previous_steps=steps,
            )
            steps.append(step_result)
            model_name = step_result.model
            if step_result.status in {"done", "takeover", "approval_required", "error"}:
                final_status = step_result.status
                break
            if index == max_steps - 1:
                final_status = "max_steps_reached"
        final_session = await self.manager._session_summary(await self.manager.get_session(session_id))
        payload = AgentRunResult(
            provider=provider_name,
            model=model_name,
            goal=goal,
            status=final_status,
            steps=steps,
            final_session=final_session,
        )
        await self._append_agent_log(session_id, "agent_runs.jsonl", payload.model_dump())
        return payload

    async def _execute_decision(
        self,
        *,
        session_id: str,
        goal: str,
        observation: dict[str, Any],
        provider_decision: ProviderDecision,
        upload_approved: bool,
        approval_id: str | None,
    ) -> AgentStepResult:
        decision = provider_decision.decision
        execution: dict[str, Any] | None = None
        status: str

        if decision.action == "done":
            status = "done"
        elif decision.action == "request_human_takeover":
            execution = await self.manager.request_human_takeover(session_id, reason=decision.reason)
            status = "takeover"
        elif decision.action in {"navigate", "click", "type", "press", "scroll", "upload"}:
            execution = await self.manager.execute_decision(
                session_id,
                decision,
                approval_id=approval_id,
            )
            status = "acted"
        else:  # pragma: no cover - guarded by schema
            raise ValueError(f"Unsupported action: {decision.action}")

        return AgentStepResult(
            provider=provider_decision.provider,
            model=provider_decision.model,
            goal=goal,
            status=status,  # type: ignore[arg-type]
            observation=observation,
            decision=decision.model_dump(),
            execution=execution,
            usage=provider_decision.usage,
            raw_text=provider_decision.raw_text,
            error=None,
            error_code=None,
        )

    @staticmethod
    def _summarize_previous_steps(steps: list[AgentStepResult]) -> list[dict[str, Any]]:
        summary: list[dict[str, Any]] = []
        for item in steps[-6:]:
            execution = item.execution or {}
            after = execution.get("after") if isinstance(execution, dict) else None
            summary.append(
                {
                    "status": item.status,
                    "action": item.decision.get("action"),
                    "reason": item.decision.get("reason"),
                    "url": (after or {}).get("url") or item.observation.get("url"),
                    "title": (after or {}).get("title") or item.observation.get("title"),
                    "error": item.error,
                }
            )
        return summary

    async def _append_agent_log(self, session_id: str, filename: str, payload: dict[str, Any]) -> None:
        session = await self.manager.get_session(session_id)
        await self.manager._append_jsonl(session.artifact_dir / filename, payload)
