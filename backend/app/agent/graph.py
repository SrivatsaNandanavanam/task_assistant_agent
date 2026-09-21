from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.agent.nodes import AgentNodes, Planner
from app.agent.state import AgentState
from app.db.session import get_session_factory


def _continue_to(next_node: str):
    """Stop as soon as any node has produced a final reply; otherwise continue."""

    def route(state: AgentState) -> str:
        return END if state.get("reply") else next_node

    return route


def _after_validate(state: AgentState) -> str:
    if state.get("reply"):
        return END
    # The ONLY path to delete_task is through the approval branch.
    return "prepare_approval" if state["tool"] == "delete_task" else "execute"


def _after_approval(state: AgentState) -> str:
    return "delete_exec" if state.get("approved") is True else "cancel"


def build_graph(planner: Planner | None = None, session_factory=None, checkpointer=None):
    """Understand -> Decide -> Resolve -> Select tool -> Validate -> [Approve] -> Execute -> Verify."""
    nodes = AgentNodes(planner, session_factory or (lambda: get_session_factory()()))
    g = StateGraph(AgentState)

    g.add_node("understand", nodes.understand)
    g.add_node("decide", nodes.decide)
    g.add_node("resolve", nodes.resolve)
    g.add_node("select_tool", nodes.select_tool)
    g.add_node("validate", nodes.validate)
    g.add_node("prepare_approval", nodes.prepare_approval)
    g.add_node("approve", nodes.approve)
    g.add_node("cancel", nodes.cancel)
    g.add_node("execute", nodes.execute)
    g.add_node("delete_exec", nodes.delete_exec)
    g.add_node("verify", nodes.verify)

    g.add_edge(START, "understand")
    g.add_conditional_edges("understand", _continue_to("decide"), ["decide", END])
    g.add_conditional_edges("decide", _continue_to("resolve"), ["resolve", END])
    g.add_conditional_edges("resolve", _continue_to("select_tool"), ["select_tool", END])
    g.add_conditional_edges("select_tool", _continue_to("validate"), ["validate", END])
    g.add_conditional_edges("validate", _after_validate, ["prepare_approval", "execute", END])
    g.add_conditional_edges("prepare_approval", _continue_to("approve"), ["approve", END])
    g.add_conditional_edges("approve", _after_approval, ["delete_exec", "cancel"])
    g.add_conditional_edges("execute", _continue_to("verify"), ["verify", END])
    g.add_conditional_edges("delete_exec", _continue_to("verify"), ["verify", END])
    g.add_edge("cancel", END)
    g.add_edge("verify", END)

    return g.compile(checkpointer=checkpointer or InMemorySaver())
