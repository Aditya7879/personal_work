"""Normalize the NEO Companion generations contract used by the Excel pipeline.

Only the final AI message is an answer. Tool output is kept as bounded private
diagnostics, not passed off as an answer or inferred document provenance.
"""
from __future__ import annotations

import re

from .agent_errors import AgentInvocationError


MAX_ANSWER_LENGTH = 50000
_SECRET_KEYS = {"authorization", "accesstoken", "refreshtoken", "idtoken", "apikey", "clientsecret", "password", "credentials"}
_BEARER = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)


def answer_text(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n\n".join(block["text"] for block in value
                            if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str))
    return ""


def validate_answer(value) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AgentInvocationError("incomplete")
    if len(value) > MAX_ANSWER_LENGTH:
        raise AgentInvocationError("answer_length")
    return value


def private_trace(messages: list, tool_calls: list, tool_results: list) -> dict:
    """Keep diagnostics bounded and redact credential-shaped structured fields."""
    remaining, truncated = 200000, False

    def bounded(value, depth=0):
        nonlocal remaining, truncated
        if depth > 10 or remaining <= 0:
            truncated = True
            return "[truncated]"
        if isinstance(value, str):
            value = _BEARER.sub("Bearer [redacted]", value)
            limit = min(40000, remaining)
            remaining -= min(len(value), limit)
            if len(value) > limit:
                truncated = True
                return value[:limit] + "\n[truncated]"
            return value
        if isinstance(value, dict):
            result = {}
            for index, (key, item) in enumerate(value.items()):
                if index >= 60 or remaining <= 0:
                    truncated = True
                    break
                name = str(key)[:200]
                normalized = re.sub(r"[^a-z]", "", name.casefold())
                remaining -= len(name)
                result[name] = "[redacted]" if normalized in _SECRET_KEYS else bounded(item, depth + 1)
            return result
        if isinstance(value, list):
            result = []
            for index, item in enumerate(value):
                if index >= 80 or remaining <= 0:
                    truncated = True
                    break
                result.append(bounded(item, depth + 1))
            return result
        if value is None or isinstance(value, (bool, int, float)):
            remaining -= 16
            return value
        return bounded(str(value), depth + 1)

    # Prioritize tool diagnostics over a duplicate serialized message history.
    result = bounded({"toolCalls": tool_calls, "toolResults": tool_results, "messages": messages})
    return {**result, "messageCount": len(messages), "toolCallCount": len(tool_calls),
            "toolResultCount": len(tool_results), "truncated": truncated}


def parse_companion_response(data: dict) -> dict:
    messages = data.get("messages")
    if not isinstance(messages, list):
        raise AgentInvocationError("response")
    final_answer = ""
    tool_calls, tool_results = [], []
    for message in messages:
        if not isinstance(message, dict) or not isinstance(message.get("data"), dict):
            raise AgentInvocationError("response")
        details = message["data"]
        kind = message.get("type")
        if kind == "ai":
            calls = details.get("tool_calls") or []
            if not isinstance(calls, list):
                raise AgentInvocationError("response")
            tool_calls.extend(call for call in calls if isinstance(call, dict))
            # Never return the preliminary "let me search" message of a tool turn.
            final_answer = "" if calls or details.get("invalid_tool_calls") else answer_text(details.get("content"))
        elif kind == "tool":
            final_answer = ""
            tool_results.append({key: details.get(key) for key in ("name", "content", "tool_call_id", "status")})
        elif kind in {"human", "system"}:
            final_answer = ""

    return {"answer": validate_answer(final_answer),
            "conversationId": data.get("conversation_id") if isinstance(data.get("conversation_id"), str) else None,
            "runId": data.get("run_id") if isinstance(data.get("run_id"), str) else None,
            "agentVersion": data.get("agent_version") if isinstance(data.get("agent_version"), str) else None,
            "modelVersion": data.get("model_version") if isinstance(data.get("model_version"), str) else None,
            "corpusVersion": data.get("corpus_version") if isinstance(data.get("corpus_version"), str) else None,
            "sources": data.get("sources") if isinstance(data.get("sources"), list) else [],
            "privateTrace": private_trace(messages, tool_calls, tool_results)}
