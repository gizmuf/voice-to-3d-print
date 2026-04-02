"use client";

import { useEffect, useMemo, useState } from "react";

import type { BodyNode } from "../types/editable-model";

type Props = {
  rootBody: BodyNode;
  selectedBodyId: string | null;
  disabled?: boolean;
  onSelectBody: (bodyId: string) => void;
  onParamChange: (bodyId: string, key: string, value: string) => void;
};

type Point2D = [number, number];
type SelectedPart = "outer" | "pattern" | "center";

const MIN_WALL_MM = 0.8;

const asNumber = (value: string | number | boolean | undefined, fallback: number) => {
  if (typeof value === "number") return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return fallback;
};

const circlePath = (center: Point2D, radius: number, segments = 48) => {
  const points = Array.from({ length: segments }, (_, index) => {
    const angle = (2 * Math.PI * index) / segments;
    return [center[0] + Math.cos(angle) * radius, center[1] + Math.sin(angle) * radius] as Point2D;
  });
  return `M ${points.map((point) => `${point[0]} ${point[1]}`).join(" L ")} Z`;
};

const buildLayout = ({
  outerDiameter,
  thickness,
  holeDiameter,
  centerHoleDiameter,
  ringCount,
  radialSpacing,
  tangentialSpacing,
  edgeMargin,
}: {
  outerDiameter: number;
  thickness: number;
  holeDiameter: number;
  centerHoleDiameter: number;
  ringCount: number;
  radialSpacing: number;
  tangentialSpacing: number;
  edgeMargin: number;
}) => {
  const outerRadius = outerDiameter / 2;
  const holeRadius = holeDiameter / 2;
  const centerHoleRadius = centerHoleDiameter / 2;
  const minCenterRadius = centerHoleRadius + edgeMargin + holeRadius;
  const maxCenterRadius = outerRadius - edgeMargin - holeRadius;

  if (outerDiameter <= 0 || thickness <= 0 || holeDiameter <= 0) {
    throw new Error("All primary dimensions must be greater than zero.");
  }
  if (maxCenterRadius <= minCenterRadius) {
    throw new Error("Center hole and edge margin leave no room for the perforation pattern.");
  }
  if (ringCount > 1 && radialSpacing < holeDiameter + MIN_WALL_MM) {
    throw new Error("Radial spacing is too small for the selected hole diameter.");
  }

  const ringRadii =
    ringCount === 1
      ? [(minCenterRadius + maxCenterRadius) / 2]
      : Array.from({ length: ringCount }, (_, index) => minCenterRadius + index * radialSpacing);

  if (ringRadii[ringRadii.length - 1] > maxCenterRadius + 1e-6) {
    throw new Error("Ring count and radial spacing push the pattern beyond the disc boundary.");
  }

  const pitch = holeDiameter + tangentialSpacing;
  const holes: Array<{ center: Point2D; radius: number }> = [];
  const holesPerRing: number[] = [];

  for (const radius of ringRadii) {
    const circumference = 2 * Math.PI * radius;
    const count = Math.max(4, Math.floor(circumference / Math.max(pitch, 0.1)));
    const arcPitch = circumference / count;
    if (arcPitch < holeDiameter + MIN_WALL_MM) {
      throw new Error("Tangential spacing is too small for the selected hole diameter.");
    }
    holesPerRing.push(count);
    for (let index = 0; index < count; index += 1) {
      const angle = (2 * Math.PI * index) / count;
      holes.push({
        center: [Math.cos(angle) * radius, Math.sin(angle) * radius],
        radius: holeRadius,
      });
    }
  }

  const messages: string[] = [];
  let status: "safe" | "risk" | "invalid" = "safe";
  if (edgeMargin < 4) {
    status = "risk";
    messages.push("Edge margin is tight near the outer boundary.");
  }
  if (ringCount > 1 && radialSpacing < holeDiameter + 1.4) {
    status = "risk";
    messages.push("Wall thickness between rings is getting tight.");
  }
  if (pitch < holeDiameter + 1.4) {
    status = "risk";
    messages.push("Tangential spacing is getting tight around the rings.");
  }
  if (!messages.length) {
    messages.push("Geometry is within the current manufacturable range.");
  }

  return {
    outerRadius,
    thickness,
    holeDiameter,
    centerHoleDiameter,
    ringCount,
    radialSpacing,
    tangentialSpacing,
    edgeMargin,
    ringRadii,
    holesPerRing,
    holes,
    status,
    messages,
  };
};

const partForBody = (
  selectedBodyId: string | null,
  rootId: string,
  patternId: string,
  centerHoleId: string
): SelectedPart => {
  if (selectedBodyId === centerHoleId) return "center";
  if (selectedBodyId === patternId) return "pattern";
  if (!selectedBodyId || selectedBodyId === rootId) return "outer";
  return "outer";
};

export default function PerforatedDiscDesigner({
  rootBody,
  selectedBodyId,
  disabled,
  onSelectBody,
  onParamChange,
}: Props) {
  const centerHoleBody = rootBody.children.find((child) => child.label === "Center hole" || child.kind === "hole");
  const patternBody = rootBody.children.find((child) => child.kind === "circular_pattern");
  const thicknessBody = rootBody.children.find((child) => child.kind === "thickness");

  const centerHoleId = centerHoleBody?.id ?? `${rootBody.id}:center_hole`;
  const patternId = patternBody?.id ?? `${rootBody.id}:pattern`;

  const [selectedPart, setSelectedPart] = useState<SelectedPart>(
    partForBody(selectedBodyId, rootBody.id, patternId, centerHoleId)
  );

  useEffect(() => {
    setSelectedPart(partForBody(selectedBodyId, rootBody.id, patternId, centerHoleId));
  }, [centerHoleId, patternId, rootBody.id, selectedBodyId]);

  const geometry = useMemo(
    () => ({
      outerDiameter: asNumber(rootBody.params.outer_diameter, 340),
      thickness: asNumber(thicknessBody?.params.thickness_mm, asNumber(rootBody.params.thickness, 15)),
      holeDiameter: asNumber(patternBody?.params.hole_diameter_mm, 7.08),
      centerHoleDiameter: asNumber(centerHoleBody?.params.diameter_mm, 32.93),
      ringCount: Math.max(1, Math.round(asNumber(patternBody?.params.ring_count, 12))),
      radialSpacing: asNumber(patternBody?.params.radial_spacing_mm, 9.387),
      tangentialSpacing: asNumber(patternBody?.params.tangential_spacing_mm, 7),
      edgeMargin: asNumber(patternBody?.params.edge_margin_mm, 12.421),
    }),
    [centerHoleBody?.params.diameter_mm, patternBody?.params.edge_margin_mm, patternBody?.params.hole_diameter_mm, patternBody?.params.radial_spacing_mm, patternBody?.params.ring_count, patternBody?.params.tangential_spacing_mm, rootBody.params.outer_diameter, rootBody.params.thickness, thicknessBody?.params.thickness_mm]
  );

  const layout = useMemo(() => {
    try {
      return buildLayout(geometry);
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
      onSelectBody(centerHoleId);
      return;
    }
    if (part === "pattern") {
      onSelectBody(patternId);
      return;
    }
    onSelectBody(rootBody.id);
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
