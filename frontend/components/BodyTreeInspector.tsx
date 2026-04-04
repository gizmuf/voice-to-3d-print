"use client";

import type { KeyboardEvent } from "react";

import type { BodyNode, EditableModel } from "../types/editable-model";
import {
  formatParamDisplayValue,
  formatParamLabel,
  getEditableParamEntries,
  getParamInputStep,
} from "../lib/param-editor-utils";

type Props = {
  model: EditableModel;
  selectedFeatureId: string | null;
  onSelect: (featureId: string) => void;
  onParamChange: (featureId: string, key: string, value: string) => void;
  disabled?: boolean;
  showParamEditor?: boolean;
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
  const handleKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    const buttons = Array.from(
      document.querySelectorAll<HTMLButtonElement>("[data-body-tree-button='true']")
    );
    const currentIndex = buttons.indexOf(event.currentTarget);
    if (currentIndex < 0) return;
    event.preventDefault();
    const nextIndex =
      event.key === "ArrowDown"
        ? Math.min(buttons.length - 1, currentIndex + 1)
        : Math.max(0, currentIndex - 1);
    buttons[nextIndex]?.focus();
  };

  return (
    <div className="body-tree-node">
      <button
        type="button"
        data-body-tree-button="true"
        className={`body-tree-button ${selectedFeatureId === body.id ? "active" : ""}`}
        style={{ paddingLeft: `${depth * 16 + 12}px` }}
        onClick={() => onSelect(body.id)}
        onKeyDown={handleKeyDown}
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
  showParamEditor = true,
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

      {selectedBody && showParamEditor ? (
        <div className="spec-grid inspector-spec-grid">
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
                    step={getParamInputStep(key, value)}
                    onChange={(event) => onParamChange(selectedBody.id, key, event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        event.currentTarget.blur();
                      }
                    }}
                    disabled={disabled || !selectedBody.editable}
                  />
                )}
                <span className="field-value-hint">{formatParamDisplayValue(key, value)}</span>
              </label>
            ))}
          {selectedBody.unsupported_reason ? (
            <div className="warning-chip">{selectedBody.unsupported_reason}</div>
          ) : null}
        </div>
      ) : (
        <div className="project-summary">
          <div className="status-label">{selectedBody ? "Feature selected" : "No feature selected"}</div>
          <div className="muted">
            {selectedBody
              ? "This mode is inspect-only. Select a different feature in the tree or canvas to inspect it."
              : "Choose a semantic feature from the tree or the canvas to inspect it."}
          </div>
        </div>
      )}
    </div>
  );
}

function flattenBodies(bodies: BodyNode[]): BodyNode[] {
  return bodies.flatMap((body) => [body, ...flattenBodies(body.children)]);
}
