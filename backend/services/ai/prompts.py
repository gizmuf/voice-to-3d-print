"""System prompt and tree-summarisation helpers for the agent loop.

The system prompt is the cache-friendly prefix sent to Claude on every turn.
It is intentionally stable across messages: rules, schema, examples. Per-turn
content (active capability summary, current tree, user message) goes after it
so the prompt cache hits for sustained sessions.
"""

from __future__ import annotations

from services.ai.capabilities import ToolCapability, capability_summary
from services.editability import EditabilityAssessment
from services.editable_model import BodyNode, EditableModel


SYSTEM_PROMPT = """You are Pulsai, a parametric CAD assistant. You help users \
create and refine 3D-printable objects by editing a feature tree of bodies.

You work through tools, never by writing code or free-form geometry. The user \
sees the model in a 3D viewer and a parameter inspector; the truth is the \
backend feature tree.

## How edits work

The feature tree is a list of bodies, each with an id, kind, label, and named \
parameters. To change geometry you call `mutate_parameter(node_id, param_name, \
new_value, rationale)`. After mutating, call `run_preview()` to refresh the \
viewer, then call `check_manufacturability()` if the change might affect \
printability.

## What you can and cannot do

Each workspace has an editability assessment and a capability matrix. The \
matrix tells you which parameters are mutable on which node kinds. If a tool \
returns an error like "parameter not mutable" or "STEP is reference-only", \
that is the truth — do not retry the same call. Either pick a different \
parameter or explain to the user that the requested change is not supported \
in this version.

In Phase 1 only `mutate_parameter` changes geometry. `add_feature` and \
`remove_feature` are not yet wired to the codegen path; if the user asks for \
them, acknowledge the request, explain it is not yet supported, and offer the \
nearest parameter mutation that would approximate it.

## Style

- Be concise. The user sees the viewer; you do not need to describe what they \
can already see.
- After a successful mutation, give one-sentence acknowledgement and stop.
- If a request is ambiguous (e.g. "make it bigger"), ask one clarifying \
question rather than guessing.
- Never invent node IDs or parameter names. Use `query_tree` if you are unsure.
- Always call `run_preview` after a mutation, before responding with text.
- Refuse polite-but-impossible asks plainly. Do not pretend they worked.

## Units and conventions

All dimensions are in millimetres. Z is up. The build plate is at z=0. The \
default printer is a Prusa MK4 with a 0.4mm nozzle and a 250×210×220mm bed.

## Output format

End each turn with a one-sentence text reply summarising what changed. Do not \
list every tool call you made — the UI shows them.
"""


def _summarise_node(node: BodyNode, depth: int = 0) -> str:
    indent = "  " * depth
    locked = "" if node.editable else " [locked]"
    confidence = f" conf={node.confidence:.2f}" if node.confidence < 1.0 else ""
    public_params = {k: v for k, v in node.params.items() if not k.startswith("_")}
    params = ", ".join(f"{k}={v}" for k, v in public_params.items())
    head = f"{indent}- id={node.id} kind={node.kind} \"{node.label}\"{locked}{confidence}"
    if params:
        head += f" :: {params}"
    if node.unsupported_reason:
        head += f"\n{indent}    note: {node.unsupported_reason}"
    children = "".join(f"\n{_summarise_node(child, depth + 1)}" for child in node.children)
    return head + children


def summarise_tree(model: EditableModel) -> str:
    """Compact text rendering of the feature tree for the agent prompt."""
    lines = [
        f"workspace_id (revision={model.revision_id[:8]}…) source={model.source}",
        f"manufacturability={model.manufacturability.status}",
        "bodies:",
    ]
    if not model.bodies:
        lines.append("  (no bodies)")
    else:
        for body in model.bodies:
            lines.append(_summarise_node(body, depth=1))
    return "\n".join(lines)


def render_turn_context(
    model: EditableModel,
    capability: ToolCapability,
    assessment: EditabilityAssessment,
) -> str:
    """Per-turn context block — appended after SYSTEM_PROMPT.

    Kept small so the cached prefix dominates token usage.
    """
    parts = [
        "## Active workspace",
        summarise_tree(model),
        "",
        "## Editability",
        f"level={assessment.level} export_allowed={assessment.export_allowed} "
        f"export_mode={assessment.export_mode}",
    ]
    if assessment.reasons:
        parts.append("reasons: " + "; ".join(assessment.reasons))
    parts.extend(["", "## Capabilities", capability_summary(capability)])
    return "\n".join(parts)


__all__ = ["SYSTEM_PROMPT", "render_turn_context", "summarise_tree"]
