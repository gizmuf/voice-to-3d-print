"use client";

import { useEffect } from "react";

export default function ModelViewer({
  src,
  label
}: {
  src?: string | null;
  label?: string;
}) {
  useEffect(() => {
    import("@google/model-viewer");
  }, []);

  if (!src) {
    return (
      <div className="model-placeholder">
        <div className="placeholder-title">No model yet</div>
        <div className="placeholder-body">
          Speak a design intent to generate a printable model.
        </div>
      </div>
    );
  }

  return (
    <div className="model-viewer-wrap">
      <model-viewer
        src={src}
        alt={label || "Generated 3D model"}
        ar
        camera-controls
        auto-rotate
        shadow-intensity="1"
        exposure="0.95"
        style={{ width: "100%", height: "100%" }}
      />
    </div>
  );
}
