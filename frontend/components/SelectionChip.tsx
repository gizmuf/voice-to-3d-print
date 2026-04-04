"use client";

import { useEffect, useRef } from "react";

type Props = {
  eyebrow?: string;
  title: string;
  value?: string | null;
  actionLabel?: string;
  onAction?: () => void;
  onDismiss: () => void;
};

export default function SelectionChip({
  eyebrow = "Selection",
  title,
  value,
  actionLabel = "Edit",
  onAction,
  onDismiss,
}: Props) {
  const chipRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const handlePointerDown = (event: MouseEvent) => {
      if (!chipRef.current) return;
      if (chipRef.current.contains(event.target as Node)) return;
      onDismiss();
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onDismiss();
      }
    };

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [onDismiss]);

  return (
    <div ref={chipRef} className="selection-chip" role="dialog" aria-label={`${title} selection`}>
      <div className="selection-chip-copy">
        <div className="selection-chip-eyebrow">{eyebrow}</div>
        <strong>{title}</strong>
        {value ? <span>{value}</span> : null}
      </div>
      <div className="selection-chip-actions">
        {onAction ? (
          <button type="button" className="mode-chip" onClick={onAction}>
            {actionLabel}
          </button>
        ) : null}
        <button type="button" className="selection-chip-close" onClick={onDismiss} aria-label="Dismiss selection chip">
          Close
        </button>
      </div>
    </div>
  );
}
