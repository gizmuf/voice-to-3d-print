"use client";

import type { BodyNode, EditableModel } from "../types/editable-model";
import { formatParamLabel, getEditableParamEntries } from "../lib/param-editor-utils";

type Props = {
  model: EditableModel;
  selectedFeatureId: string | null;
  onSelect: (featureId: string) => void;
  onParamChange: (featureId: string, key: string, value: string) => void;
  disabled?: boolean;
};

function BodyTreeNode({
  body,
  depth,
  selectedFeatureId,
  onSelect,
}: {
  body: BodyNode;
  depth: number;
  selectedFeatureId: string | null;
  onSelect: (featureId: string) => void;
}) {
  return (
    <div className="body-tree-node">
      <button
        type="button"
        className={`body-tree-button ${selectedFeatureId === body.id ? "active" : ""}`}
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
          selectedFeatureId={selectedFeatureId}
          onSelect={onSelect}
        />
      ))}
    </div>
  );
}

export default function BodyTreeInspector({
  model,
  selectedFeatureId,
  onSelect,
  onParamChange,
  disabled,
}: Props) {
  const allBodies = flattenBodies(model.bodies);
  const selectedBody = allBodies.find((body) => body.id === selectedFeatureId) ?? null;

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
            selectedFeatureId={selectedFeatureId}
            onSelect={onSelect}
          />
        ))}
      </div>

      {selectedBody ? (
        <div className="spec-grid">
          {getEditableParamEntries(selectedBody)
            .map(({ key, value, type }) => (
              <label key={key} className="field-row compact-field">
                <span>{formatParamLabel(key)}</span>
                {type === "boolean" ? (
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
                    type={type === "number" ? "number" : "text"}
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
      ) : (
        <div className="project-summary">
          <div className="status-label">No feature selected</div>
          <div className="muted">Choose a semantic feature from the tree or the 3D preview to edit exact values.</div>
        </div>
      )}
    </div>
  );
}

function flattenBodies(bodies: BodyNode[]): BodyNode[] {
  return bodies.flatMap((body) => [body, ...flattenBodies(body.children)]);
}
