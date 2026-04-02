"use client";

import { useState } from "react";

type Props = {
  disabled?: boolean;
  onSubmit: (prompt: string) => Promise<void> | void;
};

export default function ElementAiInput({ disabled, onSubmit }: Props) {
  const [value, setValue] = useState("");
  const [status, setStatus] = useState<"idle" | "thinking" | "error" | "applied">("idle");
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    const prompt = value.trim();
    if (!prompt || disabled) return;
    setStatus("thinking");
    setError(null);
    try {
      await onSubmit(prompt);
      setValue("");
      setStatus("applied");
    } catch (submitError) {
      setStatus("error");
      setError((submitError as Error).message || "AI edit failed.");
    }
  };

  return (
    <div className="element-ai-input">
      <label className="field-row compact-field">
        <span>AI edit</span>
        <input
          type="text"
          value={value}
          placeholder="make this 20% bigger"
          disabled={disabled}
          onChange={(event) => {
            setValue(event.target.value);
            if (status !== "idle") {
              setStatus("idle");
              setError(null);
            }
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              void submit();
            }
          }}
        />
      </label>
      <div className="hint">
        {status === "thinking"
          ? "Applying AI edit…"
          : status === "applied"
            ? "AI edit applied."
            : "Supported: exact values, percentages, and simple proportional edits."}
      </div>
      {error ? <div className="warning-chip">{error}</div> : null}
    </div>
  );
}
