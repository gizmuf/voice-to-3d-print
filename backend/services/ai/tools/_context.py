from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from services.editable_model import BodyNode, EditableModel
from services.printer_profiles import PrinterProfile


@dataclass
class AgentContext:
    workspace_id: str
    model: EditableModel
    output_dir: Path
    printer_profile: PrinterProfile
    artifact_url_prefix: str = "/artifacts"
    last_preview: dict | None = field(default=None)

    def reload(self, model: EditableModel) -> None:
        """Replace the in-context model after a successful mutation."""
        self.model = model

    def find_node(self, node_id: str) -> tuple[BodyNode | None, BodyNode | None]:
        """Walk the tree; return (node, parent) or (None, None)."""
        return _find(self.model.bodies, node_id, parent=None)

    def workspace_artifact_url(self, path: Path) -> str:
        return f"{self.artifact_url_prefix}/workspaces/{self.workspace_id}/{path.name}"


def _find(
    bodies: list[BodyNode],
    node_id: str,
    parent: BodyNode | None,
) -> tuple[BodyNode | None, BodyNode | None]:
    for body in bodies:
        if body.id == node_id:
            return body, parent
        found, found_parent = _find(body.children, node_id, body)
        if found is not None:
            return found, found_parent
    return None, None
