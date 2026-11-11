"""Safe invocation errors; never expose an upstream body or credential to users."""
from __future__ import annotations


AGENT_ERROR_MESSAGES = {
    "outcome_unknown": "The agent call outcome is unknown after an interruption. No automatic generation replay was made.",
    "authentication": "Agent authentication failed. Refresh the backend Google credentials and retry; your original answer is unchanged.",
    "permission": "The backend identity does not have access to this agent. Check the Companion API permissions before retrying.",
    "timeout": "The agent request timed out. It may have run upstream; no automatic replay was made. Retry deliberately if needed.",
    "rate_limit": "The agent is rate-limiting requests. Wait before starting another retest.",
    "unavailable": "The agent service is temporarily unavailable. No answer was saved; retry when the service recovers.",
    "network": "The backend could not reach the agent. Check the network or company connection before retrying.",
    "redirect": "The agent returned a redirect, which was not followed. Check the backend invocation URL.",
    "request": "The agent rejected the request. Check the backend target configuration and response contract.",
    "response": "The agent returned an invalid response. No answer was saved; check the Companion response contract.",
    "incomplete": "The agent did not return a completed, non-empty answer. Tool output was not substituted for an answer.",
    "answer_length": "The agent answer exceeded the supported length. It was not silently truncated or published.",
}


class AgentInvocationError(RuntimeError):
    def __init__(self, code: str, *, http_status: int | None = None):
        self.code = code
        self.http_status = http_status
        self.public_message = AGENT_ERROR_MESSAGES[code]
        super().__init__(self.public_message)


def safe_workflow_error(error: str | None) -> str:
    if error in AGENT_ERROR_MESSAGES.values():
        return error
    return "This check could not be completed. The review team can retry it."
