"use client";

import type { BodyNode, EditableModel } from "../types/editable-model";

type Props = {
  model: EditableModel;
  selectedBodyId: string | null;
  onSelect: (bodyId: string) => void;
  onParamChange: (bodyId: string, key: string, value: string) => void;
  disabled?: boolean;
};

const formatLabel = (key: string) => key.replace(/^_/, "").replace(/_/g, " ");

function BodyTreeNode({
  body,
  depth,
  selectedBodyId,
  onSelect,
}: {
  body: BodyNode;
  depth: number;
  selectedBodyId: string | null;
  onSelect: (bodyId: string) => void;
}) {
  return (
    <div className="body-tree-node">
      <button
        type="button"
        className={`body-tree-button ${selectedBodyId === body.id ? "active" : ""}`}
        style={{ paddingLeft: `${depth * 16 + 12}px` }}
        onClick={() => onSelect(body.id)}
      >
        <span>{body.label}</span>
        {!body.editable ? <span className="chip chip-warm">Locked</span> : null}
      </button>
      {body.children.map((child) => (
        <BodyTreeNode
          key={child.id}
          body={child}
          depth={depth + 1}
          selectedBodyId={selectedBodyId}
          onSelect={onSelect}
        />
      ))}
    </div>
  );
}

export default function BodyTreeInspector({
  model,
  selectedBodyId,
  onSelect,
  onParamChange,
  disabled,
}: Props) {
  const allBodies = flattenBodies(model.bodies);
  const selectedBody = allBodies.find((body) => body.id === selectedBodyId) ?? model.bodies[0] ?? null;

  return (
    <div className="body-tree-inspector">
      <div className="project-summary">
        <div className="status-label">Feature tree</div>
        <div className="muted">Select a semantic feature, then edit only the properties that belong to it.</div>
      </div>

      <div className="body-tree-list">
        {model.bodies.map((body) => (
          <BodyTreeNode
            key={body.id}
            body={body}
            depth={0}
            selectedBodyId={selectedBody?.id ?? null}
            onSelect={onSelect}
          />
        ))}
      </div>

      {selectedBody ? (
        <div className="spec-grid">
          {Object.entries(selectedBody.params)
            .filter(([key]) => !key.startsWith("_"))
            .map(([key, value]) => (
              <label key={key} className="field-row compact-field">
                <span>{formatLabel(key)}</span>
                {typeof value === "boolean" ? (
                  <select
                    value={value ? "true" : "false"}
                    onChange={(event) => onParamChange(selectedBody.id, key, event.target.value)}
                    disabled={disabled || !selectedBody.editable}
                  >
                    <option value="true">True</option>
                    <option value="false">False</option>
                  </select>
                ) : (
                  <input
                    type={typeof value === "number" ? "number" : "text"}
                    value={String(value)}
                    onChange={(event) => onParamChange(selectedBody.id, key, event.target.value)}
                    disabled={disabled || !selectedBody.editable}
                  />
                )}
              </label>
            ))}
          {selectedBody.unsupported_reason ? (
            <div className="warning-chip">{selectedBody.unsupported_reason}</div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function flattenBodies(bodies: BodyNode[]): BodyNode[] {
  return bodies.flatMap((body) => [body, ...flattenBodies(body.children)]);
}

