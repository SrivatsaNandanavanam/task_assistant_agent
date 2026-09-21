from typing import Any, TypedDict

STEP_LABELS = [
    ("understand", "Understand request"),
    ("decide", "Decide action"),
    ("tool", "Select tool"),
    ("validate", "Validate"),
    ("approval", "Confirmation"),
    ("execute", "Execute"),
    ("return", "Return result"),
]


class AgentState(TypedDict, total=False):
    # turn input
    thread_id: str
    request_id: str
    message: str
    timezone: str
    # bounded conversation context (persisted per thread by the checkpointer)
    last_task_id: int | None
    history: list[str]
    # per-turn working state
    plan: dict[str, Any] | None
    tool: str | None
    args: dict[str, Any] | None
    target_id: int | None
    approval: dict[str, Any] | None
    approved: bool | None
    result: dict[str, Any] | None
    steps: list[dict[str, Any]]
    # turn output
    reply: str | None
    status: str | None


def new_steps() -> list[dict[str, Any]]:
    return [
        {"key": k, "label": label, "status": "skipped" if k == "approval" else "pending", "detail": None}
        for k, label in STEP_LABELS
    ]


def set_step(steps: list[dict], key: str, status: str, detail: str | None = None) -> list[dict]:
    return [{**s, "status": status, "detail": detail} if s["key"] == key else s for s in steps]


def clean_detail(text: str | None, limit: int = 160) -> str | None:
    if not text:
        return None
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
