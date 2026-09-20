"""Client for Elastic Agent Builder (Kibana API).

Bootstrap is idempotent (GET -> POST or PUT) and lazy: it runs on the first
research request, never at startup, so a Kibana outage cannot break the API.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import httpx

from backend.config import Settings
from backend.research.tools import agent_spec, tool_specs

_API = "/api/agent_builder"
# Read-only fields Kibana returns that it refuses on create/update.
_RESPONSE_ONLY = ("readonly", "experimental", "confirmation", "schema", "type_label")


class AgentBuilderUnavailable(Exception):
    """Agent Builder cannot be used (disabled, forbidden, unreachable or timed out)."""


@dataclass
class ToolCall:
    tool_id: str
    params: dict[str, Any]
    results: list[Any]


@dataclass
class ConverseResult:
    message: str
    conversation_id: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    token_usage: dict[str, Any] = field(default_factory=dict)
    raw_steps: list[dict[str, Any]] = field(default_factory=list)


class AgentBuilderClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._base = settings.resolved_kibana_url
        self._http: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()
        self._bootstrapped = False
        self._unavailable_reason: str | None = None

    @property
    def available(self) -> bool:
        return self._settings.agent_builder_enabled and self._unavailable_reason is None

    @property
    def unavailable_reason(self) -> str | None:
        if not self._settings.agent_builder_enabled:
            return "AGENT_BUILDER_ENABLED is false"
        return self._unavailable_reason

    def _client(self) -> httpx.AsyncClient:
        if not self._base or not self._settings.elasticsearch_api_key:
            raise AgentBuilderUnavailable("Kibana URL or API key is not set")
        if self._http is None:
            self._http = httpx.AsyncClient(
                base_url=self._base,
                headers={
                    "Authorization": f"ApiKey {self._settings.elasticsearch_api_key}",
                    "kbn-xsrf": "true",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(connect=10, read=60, write=30, pool=10),
            )
        return self._http

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        timeout: float | None = None,
        allow_404: bool = False,
    ) -> dict[str, Any] | None:
        try:
            response = await self._client().request(
                method,
                f"{_API}{path}",
                json=json,
                timeout=timeout if timeout is not None else httpx.USE_CLIENT_DEFAULT,
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise AgentBuilderUnavailable(f"Agent Builder {method} {path} failed: {exc!r}") from exc
        if response.status_code == 404 and allow_404:
            return None
        if response.status_code in (401, 403):
            self._unavailable_reason = f"Kibana returned {response.status_code} for {path}"
            raise AgentBuilderUnavailable(self._unavailable_reason)
        if response.status_code >= 400:
            raise AgentBuilderUnavailable(
                f"Agent Builder {method} {path} -> HTTP {response.status_code}: {response.text[:400]}"
            )
        return response.json()

    async def _upsert(self, kind: str, spec: dict[str, Any]) -> None:
        existing = await self._request("GET", f"/{kind}/{spec['id']}", allow_404=True)
        if existing is None:
            await self._request("POST", f"/{kind}", json=spec)
            return
        body = {key: value for key, value in spec.items() if key not in ("id", "type", *_RESPONSE_ONLY)}
        await self._request("PUT", f"/{kind}/{spec['id']}", json=body)

    async def bootstrap(self, *, force: bool = False) -> list[str]:
        """Create or update the Peel tools and agent. Indices must already exist:
        ES|QL tools are validated against real mappings."""
        if not self._settings.agent_builder_enabled:
            raise AgentBuilderUnavailable("AGENT_BUILDER_ENABLED is false")
        async with self._lock:
            if self._bootstrapped and not force:
                return []
            specs = tool_specs(self._settings.semantic_score_threshold)
            for spec in specs:
                await self._upsert("tools", spec)
            tool_ids = [spec["id"] for spec in specs]
            connector = self._settings.agent_builder_firecrawl_connector_id
            await self._upsert(
                "agents",
                agent_spec(
                    self._settings.agent_builder_agent_id,
                    tool_ids,
                    [connector] if connector else None,
                ),
            )
            self._bootstrapped = True
            self._unavailable_reason = None
            return tool_ids

    async def execute_tool(self, tool_id: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        data = await self._request(
            "POST", "/tools/_execute", json={"tool_id": tool_id, "tool_params": params}
        )
        return list((data or {}).get("results") or [])

    async def converse(self, prompt: str, *, conversation_id: str | None = None) -> ConverseResult:
        await self.bootstrap()
        body: dict[str, Any] = {"input": prompt, "agent_id": self._settings.agent_builder_agent_id}
        if conversation_id:
            body["conversation_id"] = conversation_id
        if self._settings.agent_builder_connector_id:
            body["connector_id"] = self._settings.agent_builder_connector_id
        data = await self._request(
            "POST", "/converse", json=body, timeout=self._settings.agent_builder_timeout_s
        )
        return parse_converse(data or {})


def parse_converse(data: dict[str, Any]) -> ConverseResult:
    """Docs disagree on the response shape, so read both variants."""
    response = data.get("response")
    message = (response.get("message") if isinstance(response, dict) else None) or data.get("message") or ""
    steps = [step for step in data.get("steps") or [] if isinstance(step, dict)]
    calls = [
        ToolCall(
            tool_id=str(step.get("tool_id") or ""),
            params=dict(step.get("params") or {}),
            results=list(step.get("results") or step.get("result") or []),
        )
        for step in steps
        if step.get("type") == "tool_call"
    ]
    usage = data.get("model_usage") or data.get("token_usage") or {}
    return ConverseResult(
        message=str(message),
        conversation_id=data.get("conversation_id"),
        tool_calls=calls,
        token_usage=dict(usage) if isinstance(usage, dict) else {},
        raw_steps=steps,
    )


def esql_rows(results: list[Any]) -> list[dict[str, Any]]:
    """Flatten Agent Builder tool results into row dicts (columns zipped with values)."""
    rows: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        data = item.get("data")
        if not isinstance(data, dict):
            continue
        columns = [column.get("name") for column in data.get("columns") or []]
        for values in data.get("values") or []:
            rows.append(dict(zip(columns, values, strict=False)))
    return rows


_client: AgentBuilderClient | None = None


def get_agent_builder(settings: Settings) -> AgentBuilderClient:
    global _client
    if _client is None:
        _client = AgentBuilderClient(settings)
    return _client


async def close_agent_builder() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
