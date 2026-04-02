"use client";

import { useEffect, useMemo, useState } from "react";

import type { BodyNode } from "../types/editable-model";
import {
  asNumber,
  buildPerforatedDiscLayout,
  extractDiscGeometry,
  inferDiscSelectedPart,
} from "../lib/perforated-disc-geometry";

type Props = {
  rootBody: BodyNode;
  selectedFeatureId: string | null;
  disabled?: boolean;
  onSelectFeature: (bodyId: string) => void;
  onParamChange: (featureId: string, key: string, value: string) => void;
};

type Point2D = [number, number];
type SelectedPart = "outer" | "pattern" | "center";

const circlePath = (center: Point2D, radius: number, segments = 48) => {
  const points = Array.from({ length: segments }, (_, index) => {
    const angle = (2 * Math.PI * index) / segments;
    return [center[0] + Math.cos(angle) * radius, center[1] + Math.sin(angle) * radius] as Point2D;
  });
  return `M ${points.map((point) => `${point[0]} ${point[1]}`).join(" L ")} Z`;
};


export default function PerforatedDiscDesigner({
  rootBody,
  selectedFeatureId,
  disabled,
  onSelectFeature,
  onParamChange,
}: Props) {
  const centerHoleBody = rootBody.children.find((child) => child.label === "Center hole" || child.kind === "hole");
  const patternBody = rootBody.children.find((child) => child.kind === "circular_pattern");
  const thicknessBody = rootBody.children.find((child) => child.kind === "thickness");

  const centerHoleId = centerHoleBody?.id ?? `${rootBody.id}:center_hole`;
  const patternId = patternBody?.id ?? `${rootBody.id}:pattern`;

  const [selectedPart, setSelectedPart] = useState<SelectedPart>(
    inferDiscSelectedPart(selectedFeatureId, rootBody.id, patternId, centerHoleId)
  );

  useEffect(() => {
    setSelectedPart(inferDiscSelectedPart(selectedFeatureId, rootBody.id, patternId, centerHoleId));
  }, [centerHoleId, patternId, rootBody.id, selectedFeatureId]);

  const geometry = useMemo(
    () => extractDiscGeometry(rootBody),
    [rootBody]
  );

  const layout = useMemo(() => {
    try {
      return buildPerforatedDiscLayout(geometry);
    } catch (error) {
      return {
        error: (error as Error).message,
      } as const;
    }
  }, [geometry]);

  const outerRadius = geometry.outerDiameter / 2;
  const viewPad = outerRadius * 0.18;
  const viewBox = `${-outerRadius - viewPad} ${-outerRadius - viewPad} ${(outerRadius + viewPad) * 2} ${(outerRadius + viewPad) * 2}`;

  const statusClass =
    "error" in layout
      ? "manufacturability-bad"
      : layout.status === "risk"
        ? "manufacturability-risk"
        : "manufacturability-safe";

  const selectPart = (part: SelectedPart) => {
    setSelectedPart(part);
    if (part === "center") {
      onSelectFeature(centerHoleId);
      return;
    }
    if (part === "pattern") {
      onSelectFeature(patternId);
      return;
    }
    onSelectFeature(rootBody.id);
  };

  const handleCanvasClick = (event: React.MouseEvent<SVGSVGElement>) => {
    if ("error" in layout) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const x = ((event.clientX - rect.left) / rect.width) * (outerRadius + viewPad) * 2 - (outerRadius + viewPad);
    const y = ((event.clientY - rect.top) / rect.height) * (outerRadius + viewPad) * 2 - (outerRadius + viewPad);
    const distance = Math.hypot(x, y);
    if (distance <= geometry.centerHoleDiameter / 2) {
      selectPart("center");
      return;
    }
    const hitHole = "error" in layout ? false : layout.holes.some((hole) => Math.hypot(x - hole.center[0], y - hole.center[1]) <= hole.radius * 1.4);
    if (hitHole) {
      selectPart("pattern");
      return;
    }
    if (distance <= outerRadius) {
      selectPart("outer");
    }
  };

  return (
    <div className="perforated-disc-designer">
      <div className="planar-editor-header">
        <div>
          <div className="status-label">Flagship designer</div>
          <div className="validation-headline">Perforated disc CAD workspace</div>
          <div className="muted">The 2D canvas edits the semantic model directly. Select the outer disc, the pattern, or the center hole.</div>
        </div>
        <div className={`manufacturability-pill ${statusClass}`}>
          {"error" in layout ? "Invalid" : layout.status === "risk" ? "Risk" : "Safe"}
        </div>
      </div>

      <div className="designer-part-switch">
        <button type="button" className={`mode-chip ${selectedPart === "outer" ? "active" : ""}`} onClick={() => selectPart("outer")}>
          Outer disc
        </button>
        <button type="button" className={`mode-chip ${selectedPart === "pattern" ? "active" : ""}`} onClick={() => selectPart("pattern")}>
          Hole pattern
        </button>
        <button type="button" className={`mode-chip ${selectedPart === "center" ? "active" : ""}`} onClick={() => selectPart("center")}>
          Center hole
        </button>
      </div>

      <div className="face-editor-stage">
        <svg className="face-editor-canvas perforated-canvas" viewBox={viewBox} onClick={handleCanvasClick} aria-label="Perforated disc 2D design canvas">
          <path d={circlePath([0, 0], outerRadius)} className={`disc-boundary ${selectedPart === "outer" ? "selected-part" : ""}`} />
          {"error" in layout ? null : (
            <>
              {layout.ringRadii.map((radius, index) => (
                <circle key={`guide-${index}`} cx={0} cy={0} r={radius} className="guide-ring" />
              ))}
              {layout.holes.map((hole, index) => (
                <path
                  key={`hole-${index}`}
                  d={circlePath(hole.center, hole.radius)}
                  className={`draft-shape ${statusClass} ${selectedPart === "pattern" ? "selected-part" : ""}`}
                />
              ))}
              {layout.centerHoleDiameter > 0 ? (
                <path
                  d={circlePath([0, 0], layout.centerHoleDiameter / 2)}
                  className={`center-hole-shape ${selectedPart === "center" ? "selected-part" : ""}`}
                />
              ) : null}
            </>
          )}
        </svg>
        {"error" in layout ? (
          <div className="warning-list">
            <span className="warning-chip">{layout.error}</span>
          </div>
        ) : (
          <>
            <div className="face-editor-legend">
              <span><i className="legend-swatch manufacturability-safe" /> Outer disc {geometry.outerDiameter.toFixed(1)} mm</span>
              <span><i className="legend-swatch manufacturability-risk" /> {layout.holes.length} holes</span>
              <span><i className="legend-swatch ghost" /> Thickness {geometry.thickness.toFixed(1)} mm</span>
            </div>
            <div className="warning-list">
              {layout.messages.map((message) => (
                <span key={message} className={`warning-chip ${layout.status === "safe" ? "subtle" : ""}`}>
                  {message}
                </span>
              ))}
            </div>
          </>
        )}
      </div>

      <div className="spec-grid">
        {selectedPart === "outer" ? (
          <>
            <label className="field-row compact-field">
              <span>Outer diameter mm</span>
              <input
                type="number"
                value={geometry.outerDiameter}
                onChange={(event) => onParamChange(rootBody.id, "outer_diameter", event.target.value)}
                disabled={disabled}
              />
            </label>
            <label className="field-row compact-field">
              <span>Thickness mm</span>
              <input
                type="number"
                value={geometry.thickness}
                onChange={(event) => onParamChange(thicknessBody?.id ?? rootBody.id, thicknessBody ? "thickness_mm" : "thickness", event.target.value)}
                disabled={disabled}
              />
            </label>
            <label className="field-row compact-field">
              <span>Edge margin mm</span>
              <input
                type="number"
                value={geometry.edgeMargin}
                onChange={(event) => onParamChange(patternId, "edge_margin_mm", event.target.value)}
                disabled={disabled}
              />
            </label>
          </>
        ) : null}

        {selectedPart === "pattern" ? (
          <>
            <label className="field-row compact-field">
              <span>Hole diameter mm</span>
              <input
                type="number"
                value={geometry.holeDiameter}
                onChange={(event) => onParamChange(patternId, "hole_diameter_mm", event.target.value)}
                disabled={disabled}
              />
            </label>
            <label className="field-row compact-field">
              <span>Ring count</span>
              <input
                type="number"
                value={geometry.ringCount}
                onChange={(event) => onParamChange(patternId, "ring_count", event.target.value)}
                disabled={disabled}
              />
            </label>
            <label className="field-row compact-field">
              <span>Radial spacing mm</span>
              <input
                type="number"
                value={geometry.radialSpacing}
                onChange={(event) => onParamChange(patternId, "radial_spacing_mm", event.target.value)}
                disabled={disabled}
              />
            </label>
            <label className="field-row compact-field">
              <span>Tangential spacing mm</span>
              <input
                type="number"
                value={geometry.tangentialSpacing}
                onChange={(event) => onParamChange(patternId, "tangential_spacing_mm", event.target.value)}
                disabled={disabled}
              />
            </label>
          </>
        ) : null}

        {selectedPart === "center" ? (
          <label className="field-row compact-field">
            <span>Center hole mm</span>
            <input
              type="number"
              value={geometry.centerHoleDiameter}
              onChange={(event) => onParamChange(centerHoleId, "diameter_mm", event.target.value)}
              disabled={disabled}
            />
          </label>
        ) : null}
      </div>
    </div>
  );
}
