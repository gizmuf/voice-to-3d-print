"use client";

import { useRef, type ReactNode } from "react";

import { getEditableParamEntries, formatParamLabel } from "../lib/param-editor-utils";
import type { BodyNode } from "../types/editable-model";

type Props = {
  body: BodyNode;
  disabled?: boolean;
  mode: "floating" | "docked";
  onParamChange: (featureId: string, key: string, value: string) => void;
  onDismiss: () => void;
  aiInput?: ReactNode;
};

export default function FloatingQuickEditor({
  body,
  disabled,
  mode,
  onParamChange,
  onDismiss,
  aiInput,
}: Props) {
  const pointerStartRef = useRef<{ x: number; y: number } | null>(null);
  const params = getEditableParamEntries(body, 5);

  return (
    <div className={`floating-quick-editor-wrap ${mode}`}>
      <div
        className="floating-quick-editor"
        onPointerDown={(event) => {
          pointerStartRef.current = { x: event.clientX, y: event.clientY };
          event.stopPropagation();
        }}
        onPointerMove={(event) => {
          if (!pointerStartRef.current) return;
          const moved =
            Math.hypot(
              event.clientX - pointerStartRef.current.x,
              event.clientY - pointerStartRef.current.y
            ) > 5;
          if (!moved) {
            event.stopPropagation();
          }
        }}
        onPointerUp={(event) => {
          pointerStartRef.current = null;
          event.stopPropagation();
        }}
      >
        <div className="floating-quick-editor-header">
          <div>
            <div className="status-label">Quick edit</div>
            <strong>{body.label}</strong>
          </div>
          <button type="button" className="mode-chip subtle-chip" onClick={onDismiss}>
            Close
          </button>
        </div>

        <div className="floating-quick-editor-fields">
          {params.map((entry) => (
            <label key={entry.key} className="field-row compact-field">
              <span>{formatParamLabel(entry.key)}</span>
              {entry.type === "boolean" ? (
                <select
                  value={entry.value ? "true" : "false"}
                  disabled={disabled || !body.editable}
                  onChange={(event) => onParamChange(body.id, entry.key, event.target.value)}
                >
                  <option value="true">True</option>
                  <option value="false">False</option>
                </select>
              ) : (
                <input
                  type={entry.type === "number" ? "number" : "text"}
                  value={String(entry.value)}
                  disabled={disabled || !body.editable}
                  onChange={(event) => onParamChange(body.id, entry.key, event.target.value)}
                />
              )}
            </label>
          ))}
        </div>

        {body.unsupported_reason ? (
          <div className="warning-chip">{body.unsupported_reason}</div>
        ) : null}

        {aiInput}
      </div>
    </div>
  );
}
