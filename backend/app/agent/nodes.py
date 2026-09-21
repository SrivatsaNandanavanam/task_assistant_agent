import logging
import re
import time
from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from langgraph.types import interrupt
from pydantic import ValidationError

from app.agent.prompts import (
    BULK_MSG,
    MODEL_UNAVAILABLE_MSG,
    SAVE_FAILED_MSG,
    SYSTEM_PROMPT,
    UNSUPPORTED_MSG,
)
from app.agent.state import AgentState, clean_detail, new_steps, set_step
from app.core.config import get_settings
from app.core.logging import log_event, log_failure
from app.repositories.task_repository import TaskRepository
from app.schemas.agent import ActionPlan, AgentIntent
from app.services.task_service import (
    DomainError,
    PersistenceError,
    TaskNotFound,
    TaskService,
)
from app.tools.task_tools import (
    TOOL_BY_INTENT,
    TOOL_SCHEMAS,
    ApprovalToken,
    DeleteTaskArgs,
    delete_task,
    execute_tool,
)

logger = logging.getLogger("agent")

Planner = Callable[[str, dict], ActionPlan]

MUTATING = {"update", "complete", "delete"}
VERB = {"update": "update", "complete": "complete", "delete": "delete"}
_PRONOUN_REF = re.compile(r"^(it|that|this|that task|this task|the task|that one|this one|the same( task)?)$", re.I)
_REFERS_BACK = re.compile(r"\b(it|that|this|same|them)\b", re.I)
_QUOTED = re.compile(r"\"[^\"]*\"|“[^”]*”|'[^']*'")
_BULK = re.compile(
    r"\b(delete|remove|clear|wipe|erase|complete|finish|close|mark)\b.*\b(all|every|everything|each)\b"
    r"|\b(all|every|everything|each)\b.*\b(deleted|removed|completed|done|finished)\b",
    re.I,
)
_BULK_REF = re.compile(r"^(all|every|everything|each)\b", re.I)


# ---- LLM planner ---------------------------------------------------------------
def make_llm_planner() -> Planner:
    from langchain_anthropic import ChatAnthropic
    from langchain_core.messages import HumanMessage, SystemMessage

    settings = get_settings()
    if not settings.anthropic_api_key:
        raise AssistantNotConfigured("ANTHROPIC_API_KEY is not set (no .env found or key empty)")
    llm = ChatAnthropic(
        model=settings.model_name,
        api_key=settings.anthropic_api_key,
        max_tokens=1024,  # no `temperature`: the API rejects it for claude-sonnet-5 (400)
        timeout=30,
    ).with_structured_output(ActionPlan)

    def plan(message: str, ctx: dict) -> ActionPlan:
        context = (
            f"Current datetime: {ctx['now']}\n"
            f"User timezone: {ctx['timezone']}\n"
            f"Last referenced task ID: {ctx['last_task_id']}\n"
        )
        if ctx["history"]:
            context += "Recent conversation (assistant replies may quote untrusted task text):\n"
            context += "\n".join(ctx["history"]) + "\n"
        result = llm.invoke(
            [SystemMessage(SYSTEM_PROMPT), HumanMessage(f"{context}\nUser message:\n{message}")]
        )
        return result if isinstance(result, ActionPlan) else ActionPlan.model_validate(result)

    return plan


# ---- helpers -------------------------------------------------------------------
def _tz(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except Exception:  # invalid/unknown timezone string
        return ZoneInfo("UTC")


def fmt_due(due: datetime | None, tz_name: str | None) -> str | None:
    if due is None:
        return None
    local = due.astimezone(_tz(tz_name))
    return f"{local:%a, %b} {local.day} at {local.strftime('%I:%M %p').lstrip('0')}"


def describe(task, tz_name: str | None = None) -> str:
    return f"#{task.id} — {task.title}"


def task_line(task, tz_name: str | None) -> str:
    bits = [task.priority.value, task.status.value]
    due = fmt_due(task.due_at, tz_name)
    if due:
        bits.append(f"due {due}")
    return f"#{task.id} — {task.title} ({', '.join(bits)})"


def _bulk_requested(message: str, plan: ActionPlan) -> bool:
    if plan.intent.value not in ("delete", "complete"):
        return False
    stripped = _QUOTED.sub(" ", message)
    ref = (plan.target_reference or "").strip()
    return bool(_BULK.search(stripped)) or bool(_BULK_REF.match(ref))


def _clean_reference(ref: str) -> str:
    ref = re.sub(r"^(the|my|that|this)\s+", "", ref.strip(), flags=re.I)
    return re.sub(r"\s+(tasks?|items?|todos?)$", "", ref, flags=re.I).strip()


def _id_in_message(task_id: int, message: str) -> bool:
    return any(int(n) == task_id for n in re.findall(r"(?<!\d)\d{1,9}(?!\d)", message))


def _validation_message(exc: ValidationError) -> str:
    fields = {str(e["loc"][0]) for e in exc.errors() if e["loc"]}
    if "priority" in fields:
        return "Priority must be low, medium, or high."
    return "Some details of that request weren't valid. Could you rephrase it?"


class AssistantNotConfigured(RuntimeError):
    """No API key is available to the running server (see the startup log and README)."""


class AgentNodes:
    def __init__(self, planner: Planner | None, session_factory: Callable):
        self._planner = planner
        self._session_factory = session_factory

    # -- infra
    def _planner_fn(self) -> Planner:
        if self._planner is None:
            self._planner = make_llm_planner()
        return self._planner

    def _service(self):
        session = self._session_factory()
        return TaskService(TaskRepository(session)), session

    def _finish(self, state: AgentState, reply: str, status: str, steps: list[dict], **extra) -> dict:
        ok = status in ("success", "cancelled", "clarify", "unsupported")
        steps = set_step(steps, "return", "done" if ok else "failed", None)
        log_event(
            logger,
            request_id=state.get("request_id"),
            thread_id=state.get("thread_id"),
            operation="agent_result",
            status=status,
        )
        return {"reply": reply, "status": status, "steps": steps, **extra}

    # -- 1. understand
    def understand(self, state: AgentState) -> dict:
        settings = get_settings()
        steps = new_steps()
        tz = state.get("timezone") or "UTC"
        started = time.perf_counter()
        ctx = {
            "now": datetime.now(_tz(tz)).strftime("%A, %Y-%m-%d %H:%M:%S %Z (UTC%z)"),
            "timezone": tz,
            "last_task_id": state.get("last_task_id"),
            "history": (state.get("history") or [])[-6:],
        }
        log_event(logger, request_id=state.get("request_id"), thread_id=state.get("thread_id"),
                  operation="agent_invocation")
        message = state["message"]
        if len(message) > settings.max_message_length:
            return self._finish(
                state, f"Please keep messages under {settings.max_message_length} characters.", "error",
                set_step(steps, "understand", "failed"),
            )
        try:
            plan = self._planner_fn()(message, ctx)
            plan = ActionPlan.model_validate(plan.model_dump())  # re-validate at the boundary
        except Exception as exc:  # provider outage, invalid structured output, missing key...
            log_failure(logger, exc, request_id=state.get("request_id"), thread_id=state.get("thread_id"),
                        operation="understand", status="failure")
            return self._finish(state, MODEL_UNAVAILABLE_MSG, "error", set_step(steps, "understand", "failed"))
        log_event(logger, request_id=state.get("request_id"), operation="understand", status="success",
                  intent=plan.intent.value, duration_ms=int((time.perf_counter() - started) * 1000))
        steps = set_step(steps, "understand", "done", clean_detail(plan.interpretation))
        return {"plan": plan.model_dump(mode="json"), "steps": steps}

    # -- 2. decide (guardrails on the plan)
    def decide(self, state: AgentState) -> dict:
        plan = ActionPlan.model_validate(state["plan"])
        steps = state["steps"]
        intent = plan.intent

        if intent == AgentIntent.UNSUPPORTED:
            steps = set_step(steps, "decide", "done", "UNSUPPORTED")
            steps = set_step(steps, "tool", "skipped", "No tool")
            return self._finish(state, UNSUPPORTED_MSG, "unsupported", steps)
        if _bulk_requested(state["message"], plan):
            steps = set_step(steps, "decide", "failed", "Bulk action")
            return self._finish(state, BULK_MSG, "unsupported", steps)

        question = None
        if plan.needs_clarification:
            question = clean_detail(plan.clarification_question, 300) or "Could you give me more detail?"
        elif intent == AgentIntent.CREATE and not (plan.title or "").strip():
            question = "What should the task be called?"
        elif intent == AgentIntent.UPDATE and not any(
            v is not None for v in (plan.title, plan.description, plan.priority, plan.due_at)
        ):
            question = "What would you like to change on that task?"
        if question:
            steps = set_step(steps, "decide", "done", f"{intent.value.upper()} — needs detail")
            return self._finish(state, question, "clarify", steps)

        if intent == AgentIntent.SEARCH and not (plan.search_query or "").strip():
            plan = plan.model_copy(update={"intent": AgentIntent.LIST})  # filter-only search == list
        # Naive datetimes from the model are interpreted in the user's timezone.
        if plan.due_at is not None and plan.due_at.tzinfo is None:
            plan = plan.model_copy(update={"due_at": plan.due_at.replace(tzinfo=_tz(state.get("timezone")))})
        steps = set_step(steps, "decide", "done", plan.intent.value.upper())
        return {"plan": plan.model_dump(mode="json"), "steps": steps}

    # -- 3. resolve target (read-only)
    def resolve(self, state: AgentState) -> dict:
        plan = ActionPlan.model_validate(state["plan"])
        if plan.intent.value not in MUTATING:
            return {}
        steps = state["steps"]
        verb = VERB[plan.intent.value]
        message = state["message"]
        last_id = state.get("last_task_id")
        service, session = self._service()
        try:
            task_id: int | None = None
            # 1. explicit ID -- only if the user actually wrote it (never trust an invented ID)
            if plan.target_task_id is not None and (
                _id_in_message(plan.target_task_id, message) or plan.target_task_id == last_id
            ):
                task_id = plan.target_task_id
            elif plan.target_reference and not _PRONOUN_REF.match(plan.target_reference.strip()):
                # 3-5. title / partial title / text search
                ref = plan.target_reference
                res = service.resolve_reference(ref)
                if not res.matches and _clean_reference(ref) != ref.strip():
                    res = service.resolve_reference(_clean_reference(ref))
                if not res.matches:
                    steps = set_step(steps, "decide", "done", plan.intent.value.upper())
                    return self._finish(
                        state, f'I couldn\'t find a task matching "{clean_detail(ref, 80)}".', "error",
                        set_step(steps, "tool", "skipped", "No matching task"),
                    )
                if res.task is None:
                    lines = "\n".join(describe(t) for t in res.matches[:10])
                    return self._finish(
                        state, f"I found multiple matching tasks:\n\n{lines}\n\nWhich task should I {verb}?",
                        "clarify", set_step(steps, "tool", "skipped", "Needs a specific task"),
                    )
                task_id = res.task.id
            elif last_id is not None and (
                (plan.target_reference and _PRONOUN_REF.match(plan.target_reference.strip()))
                or (not plan.target_reference and plan.target_task_id is None and _REFERS_BACK.search(message))
            ):
                task_id = last_id  # 2. conversational reference ("it") -- only if the user referred back
            if task_id is None:
                return self._finish(state, f"Which task should I {verb}? Give me its number or name.",
                                    "clarify", set_step(steps, "tool", "skipped", "Needs a specific task"))
            try:
                task = service.get_task(task_id)
            except TaskNotFound as exc:
                return self._finish(state, str(exc), "error", set_step(steps, "tool", "skipped", "Task not found"))
            return {"target_id": task.id}
        finally:
            session.close()

    # -- 4. select tool (allowlist)
    def select_tool(self, state: AgentState) -> dict:
        plan = ActionPlan.model_validate(state["plan"])
        steps = state["steps"]
        tool = TOOL_BY_INTENT.get(plan.intent.value)
        if tool is None or tool not in TOOL_SCHEMAS:
            return self._finish(state, UNSUPPORTED_MSG, "unsupported", set_step(steps, "tool", "skipped"))
        due = plan.due_at.isoformat() if plan.due_at else None
        target = state.get("target_id")
        args = {
            "create": {"title": plan.title, "description": plan.description, "priority": plan.priority, "due_at": due},
            "list": {"status": plan.status_filter, "priority": plan.priority, "overdue": plan.overdue},
            "search": {"query": plan.search_query, "status": plan.status_filter, "priority": plan.priority,
                       "overdue": plan.overdue},
            "update": {"task_id": target, "title": plan.title, "description": plan.description,
                       "priority": plan.priority, "due_at": due},
            "complete": {"task_id": target},
            "delete": {"task_id": target},
        }[plan.intent.value]
        log_event(logger, request_id=state.get("request_id"), operation="select_tool", tool_name=tool)
        return {"tool": tool, "args": args, "steps": set_step(steps, "tool", "done", tool)}

    # -- 5. validate (schema + business rules)
    def validate(self, state: AgentState) -> dict:
        steps = state["steps"]
        tool = state["tool"]
        try:
            parsed = TOOL_SCHEMAS[tool].model_validate(state["args"])
        except ValidationError as exc:
            log_event(logger, request_id=state.get("request_id"), operation="validate", status="failure",
                      tool_name=tool)
            return self._finish(state, _validation_message(exc), "error", set_step(steps, "validate", "failed"))
        args = parsed.model_dump(mode="json")
        settings = get_settings()
        title = args.get("title")
        if tool == "create_task" and not (title or "").strip():
            return self._finish(state, "What should the task be called?", "clarify",
                                set_step(steps, "validate", "failed", "Title missing"))
        if title and len(title) > settings.max_title_length:
            return self._finish(state, f"Titles can be at most {settings.max_title_length} characters.", "error",
                                set_step(steps, "validate", "failed", "Title too long"))
        return {"args": args, "steps": set_step(steps, "validate", "done", "Arguments valid")}

    # -- 6a. prepare approval (read-only) and 6b. interrupt
    def prepare_approval(self, state: AgentState) -> dict:
        service, session = self._service()
        try:
            task = service.get_task(state["args"]["task_id"])
            snapshot = {
                "id": task.id,
                "title": task.title,
                "priority": task.priority.value,
                "updated_at": task.updated_at.isoformat(),
            }
        except TaskNotFound as exc:
            return self._finish(state, str(exc), "error", set_step(state["steps"], "tool", "failed"))
        finally:
            session.close()
        steps = set_step(state["steps"], "approval", "waiting", "Waiting for confirmation")
        return {"approval": snapshot, "steps": steps}

    def approve(self, state: AgentState) -> dict:
        snap = state["approval"]
        decision = interrupt({
            "action": "delete_task",
            "task": {"id": snap["id"], "title": snap["title"], "priority": snap["priority"]},
            "message": "This action cannot be undone.",
        })
        approved = decision is True
        detail = "Approved" if approved else "Cancelled"
        return {"approved": approved, "steps": set_step(state["steps"], "approval", "done", detail)}

    def cancel(self, state: AgentState) -> dict:
        steps = set_step(state["steps"], "execute", "skipped", "Cancelled")
        return self._finish(state, "Deletion cancelled.", "cancelled", steps)

    # -- 7. execute
    def _failure(self, state: AgentState, exc: Exception, steps: list[dict]) -> dict:
        ctx = dict(request_id=state.get("request_id"), thread_id=state.get("thread_id"),
                   operation="tool_execution", tool_name=state.get("tool"), status="failure")
        if isinstance(exc, DomainError) and not isinstance(exc, PersistenceError):
            log_event(logger, error_type=type(exc).__name__, **ctx)  # expected, user-level error
        else:
            log_failure(logger, exc, **ctx)  # database/unexpected failure: keep the traceback
        steps = set_step(steps, "execute", "failed")
        if isinstance(exc, PersistenceError):
            return self._finish(state, SAVE_FAILED_MSG, "error", steps)
        if isinstance(exc, DomainError):
            return self._finish(state, str(exc), "error", steps)
        return self._finish(state, SAVE_FAILED_MSG, "error", steps)  # never leak internals

    def execute(self, state: AgentState) -> dict:
        service, session = self._service()
        started = time.perf_counter()
        try:
            result = execute_tool(state["tool"], state["args"], service)
            ids = [t.id for t in result.tasks]  # read while the session is still open
            detail = _exec_detail(result)
            already = result.already_completed
        except Exception as exc:  # deliberate catch-all: logged privately, never shown
            return self._failure(state, exc, state["steps"])
        finally:
            session.close()
        log_event(logger, request_id=state.get("request_id"), operation=result.tool, status="success",
                  result_count=len(ids), duration_ms=int((time.perf_counter() - started) * 1000))
        return {"result": {"ids": ids, "already": already},
                "steps": set_step(state["steps"], "execute", "done", clean_detail(detail))}

    def delete_exec(self, state: AgentState) -> dict:
        """Only reachable from the approved branch of the graph."""
        args = DeleteTaskArgs.model_validate(state["args"])
        snap = state["approval"]
        service, session = self._service()
        try:
            current = service.get_task(args.task_id)
            if current.updated_at.isoformat() != snap["updated_at"]:
                steps = set_step(state["steps"], "execute", "skipped", "Task changed")
                return self._finish(
                    state, "That task changed while waiting for confirmation, so nothing was deleted. "
                           "Please ask again.", "error", steps)
            token = ApprovalToken.issue(state["thread_id"], args.task_id)
            result = delete_task(service, args, token)
            deleted_id, deleted_title = result.tasks[0].id, result.tasks[0].title
        except Exception as exc:
            return self._failure(state, exc, state["steps"])
        finally:
            session.close()
        log_event(logger, request_id=state.get("request_id"), operation="delete_task", status="success",
                  result_count=1)
        return {"result": {"ids": [deleted_id], "title": deleted_title, "already": False},
                "steps": set_step(state["steps"], "execute", "done", f"Task #{args.task_id} deleted")}

    # -- 8. verify against the database, then respond
    def verify(self, state: AgentState) -> dict:
        tool, args, steps = state["tool"], state["args"], state["steps"]
        tz = state.get("timezone")
        ids = state["result"]["ids"]
        service, session = self._service()
        try:
            tasks = []
            if tool in ("create_task", "update_task", "complete_task", "delete_task", "list_tasks", "search_tasks"):
                for i in ids:
                    try:
                        tasks.append(service.get_task(i))
                    except TaskNotFound:
                        if tool != "delete_task":
                            raise
                if tool == "delete_task" and tasks:
                    raise PersistenceError("row still present")
                if tool == "create_task" and (not tasks or tasks[0].title != args["title"].strip()):
                    raise PersistenceError("create not confirmed")
                if tool == "complete_task" and tasks[0].status.value != "completed":
                    raise PersistenceError("completion not confirmed")
                if tool == "update_task":
                    t = tasks[0]
                    if args.get("priority") and t.priority.value != args["priority"]:
                        raise PersistenceError("update not confirmed")
                    if args.get("title") and t.title != args["title"].strip():
                        raise PersistenceError("update not confirmed")
            reply, last_id = self._render(state, tasks, tz)
        except Exception as exc:
            return self._failure(state, exc, steps)
        finally:
            session.close()
        history = (state.get("history") or []) + [f"User: {state['message']}", f"Assistant: {reply}"]
        out = self._finish(state, reply, "success", steps, history=history[-8:])
        out["last_task_id"] = last_id
        return out

    def _render(self, state: AgentState, tasks: list, tz: str | None) -> tuple[str, int | None]:
        tool = state["tool"]
        last = state.get("last_task_id")
        args = state["args"]
        if tool == "create_task":
            t = tasks[0]
            extra = f" (due {fmt_due(t.due_at, tz)})" if t.due_at else ""
            return f"Created task #{t.id} — {t.title}{extra}.", t.id
        if tool == "update_task":
            t = tasks[0]
            changes = [k for k in ("title", "description", "priority", "due_at") if args.get(k) is not None]
            names = ", ".join(c.replace("due_at", "due date") for c in changes)
            return f"Updated task #{t.id} — {t.title} ({names}).", t.id
        if tool == "complete_task":
            t = tasks[0]
            if state["result"]["already"]:
                return f"Task #{t.id} — {t.title} is already completed.", t.id
            return f"Marked task #{t.id} — {t.title} as completed.", t.id
        if tool == "delete_task":
            return f"Deleted task #{state['result']['ids'][0]} — {state['result']['title']}.", None
        if not tasks:
            return "No tasks found.", last
        head = "Here's what I found" if tool == "search_tasks" else "Here are your tasks"
        lines = "\n".join(task_line(t, tz) for t in tasks)
        return f"{head} ({len(tasks)}):\n\n{lines}", (tasks[0].id if len(tasks) == 1 else last)


def _exec_detail(result) -> str:
    if result.tool in ("list_tasks", "search_tasks"):
        return f"{len(result.tasks)} task(s) found"
    t = result.tasks[0]
    verb = {"create_task": "created", "update_task": "updated", "complete_task": "completed"}[result.tool]
    return f"Task #{t.id} {verb}"
