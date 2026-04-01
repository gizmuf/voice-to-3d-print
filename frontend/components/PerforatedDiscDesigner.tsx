"use client";

import { useMemo, useState } from "react";

type StructuredSpec = {
  template_id: string;
  object_label: string;
  dimensions_mm: Record<string, number>;
  constraints: Record<string, string | number | boolean>;
};

type Props = {
  spec: StructuredSpec;
  disabled?: boolean;
  onDimensionChange: (key: string, value: string) => void;
  onConstraintChange: (key: string, value: string) => void;
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

const buildLayout = (spec: StructuredSpec) => {
  const outerDiameter = asNumber(spec.dimensions_mm.outer_diameter, 340);
  const thickness = asNumber(spec.dimensions_mm.thickness, 15);
  const holeDiameter = asNumber(spec.constraints.hole_diameter_mm, 7.08);
  const centerHoleDiameter = asNumber(spec.constraints.center_hole_diameter_mm, 32.93);
  const ringCount = Math.max(1, Math.round(asNumber(spec.constraints.ring_count, 12)));
  const radialSpacing = asNumber(spec.constraints.radial_spacing_mm, 9.387);
  const tangentialSpacing = asNumber(spec.constraints.tangential_spacing_mm, 7);
  const edgeMargin = asNumber(spec.constraints.edge_margin_mm, 12.421);

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

export default function PerforatedDiscDesigner({
  spec,
  disabled,
  onDimensionChange,
  onConstraintChange,
}: Props) {
  const [selectedPart, setSelectedPart] = useState<SelectedPart>("pattern");

  const layout = useMemo(() => {
    try {
      return buildLayout(spec);
    } catch (error) {
      return {
        error: (error as Error).message,
      } as const;
    }
  }, [spec]);

  const outerDiameter = asNumber(spec.dimensions_mm.outer_diameter, 340);
  const outerRadius = outerDiameter / 2;
  const viewPad = outerRadius * 0.18;
  const viewBox = `${-outerRadius - viewPad} ${-outerRadius - viewPad} ${(outerRadius + viewPad) * 2} ${(outerRadius + viewPad) * 2}`;

  const statusClass =
    "error" in layout
      ? "manufacturability-bad"
      : layout.status === "risk"
        ? "manufacturability-risk"
        : "manufacturability-safe";

  const handleCanvasClick = (event: React.MouseEvent<SVGSVGElement>) => {
    if ("error" in layout) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const x = ((event.clientX - rect.left) / rect.width) * (outerRadius + viewPad) * 2 - (outerRadius + viewPad);
    const y = ((event.clientY - rect.top) / rect.height) * (outerRadius + viewPad) * 2 - (outerRadius + viewPad);
    const distance = Math.hypot(x, y);
    if (distance <= layout.centerHoleDiameter / 2) {
      setSelectedPart("center");
      return;
    }
    const hitHole = layout.holes.some((hole) => Math.hypot(x - hole.center[0], y - hole.center[1]) <= hole.radius * 1.4);
    if (hitHole) {
      setSelectedPart("pattern");
      return;
    }
    if (distance <= layout.outerRadius) {
      setSelectedPart("outer");
    }
  };

  return (
    <div className="perforated-disc-designer">
      <div className="planar-editor-header">
        <div>
          <div className="status-label">Flagship designer</div>
          <div className="validation-headline">Perforated disc CAD workspace</div>
          <div className="muted">Click the outer disc, center hole, or perforation field to focus the relevant controls.</div>
        </div>
        <div className={`manufacturability-pill ${statusClass}`}>
          {"error" in layout ? "Invalid" : layout.status === "risk" ? "Risk" : "Safe"}
        </div>
      </div>

      <div className="designer-part-switch">
        <button type="button" className={`mode-chip ${selectedPart === "outer" ? "active" : ""}`} onClick={() => setSelectedPart("outer")}>
          Outer disc
        </button>
        <button type="button" className={`mode-chip ${selectedPart === "pattern" ? "active" : ""}`} onClick={() => setSelectedPart("pattern")}>
          Hole pattern
        </button>
        <button type="button" className={`mode-chip ${selectedPart === "center" ? "active" : ""}`} onClick={() => setSelectedPart("center")}>
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
              <span><i className="legend-swatch manufacturability-safe" /> Outer disc {outerDiameter.toFixed(1)} mm</span>
              <span><i className="legend-swatch manufacturability-risk" /> {layout.holes.length} holes</span>
              <span><i className="legend-swatch ghost" /> Thickness {layout.thickness.toFixed(1)} mm</span>
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
                value={spec.dimensions_mm.outer_diameter}
                onChange={(event) => onDimensionChange("outer_diameter", event.target.value)}
                disabled={disabled}
              />
            </label>
            <label className="field-row compact-field">
              <span>Thickness mm</span>
              <input
                type="number"
                value={spec.dimensions_mm.thickness}
                onChange={(event) => onDimensionChange("thickness", event.target.value)}
                disabled={disabled}
              />
            </label>
            <label className="field-row compact-field">
              <span>Edge margin mm</span>
              <input
                type="number"
                value={String(spec.constraints.edge_margin_mm ?? "")}
                onChange={(event) => onConstraintChange("edge_margin_mm", event.target.value)}
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
                value={String(spec.constraints.hole_diameter_mm ?? "")}
                onChange={(event) => onConstraintChange("hole_diameter_mm", event.target.value)}
                disabled={disabled}
              />
            </label>
            <label className="field-row compact-field">
              <span>Ring count</span>
              <input
                type="number"
                value={String(spec.constraints.ring_count ?? "")}
                onChange={(event) => onConstraintChange("ring_count", event.target.value)}
                disabled={disabled}
              />
            </label>
            <label className="field-row compact-field">
              <span>Radial spacing mm</span>
              <input
                type="number"
                value={String(spec.constraints.radial_spacing_mm ?? "")}
                onChange={(event) => onConstraintChange("radial_spacing_mm", event.target.value)}
                disabled={disabled}
              />
            </label>
            <label className="field-row compact-field">
              <span>Tangential spacing mm</span>
              <input
                type="number"
                value={String(spec.constraints.tangential_spacing_mm ?? "")}
                onChange={(event) => onConstraintChange("tangential_spacing_mm", event.target.value)}
                disabled={disabled}
              />
            </label>
          </>
        ) : null}

        {selectedPart === "center" ? (
          <label className="field-row compact-field">
            <span>Center hole diameter mm</span>
            <input
              type="number"
              value={String(spec.constraints.center_hole_diameter_mm ?? "")}
              onChange={(event) => onConstraintChange("center_hole_diameter_mm", event.target.value)}
              disabled={disabled}
            />
          </label>
        ) : null}
      </div>

      {"error" in layout ? null : (
        <div className="project-summary">
          <div className="status-label">Derived pattern</div>
          <div className="analysis-grid">
            <span>{layout.holes.length} total holes</span>
            <span>{layout.ringCount} rings</span>
            <span>{layout.holesPerRing.join(" / ")} per ring</span>
          </div>
        </div>
      )}
    </div>
  );
}

