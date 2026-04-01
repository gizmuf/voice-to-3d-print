"use client";

type Point2D = [number, number];

type PatternTarget = {
  id: string;
  type: "planar_pattern_face";
  label: string;
  summary: string;
  confidence: number;
  editable: boolean;
  topology: "rectangular" | "radial";
  feature_kind: "circular_hole" | "rectangular_cutout";
  face_polygon_2d: Point2D[];
  feature_geometry_2d: Array<{
    id: string;
    center: Point2D;
    outline?: Point2D[];
  }>;
  measured: {
    feature_size: number | { width: number; height: number };
    spacing_x?: number;
    spacing_y?: number;
    radial_spacing?: number;
    count_x?: number;
    count_y?: number;
    ring_count?: number;
    holes_per_ring?: number[];
    margin?: number;
    center_hole_diameter?: number | null;
  };
  fit?: {
    center_x?: number;
    center_y?: number;
    x_positions?: number[];
    y_positions?: number[];
    ring_radii?: number[];
    holes_per_ring?: number[];
  };
  warnings?: string[];
};

type SingleTarget = {
  id: string;
  type: "single_planar_feature";
  label: string;
  summary: string;
  confidence: number;
  editable: boolean;
  feature_kind: "circular_hole" | "slot" | "rectangular_cutout";
  face_polygon_2d: Point2D[];
  feature_outline_2d: Point2D[];
  measured: {
    diameter?: number;
    width?: number;
    height?: number;
  };
  warnings?: string[];
};

type ValidationStatus = "safe" | "risk" | "invalid";

type PlanarFaceEditorProps = {
  target: PatternTarget | SingleTarget;
  params: Record<string, string>;
  disabled?: boolean;
  onParamChange: (key: string, value: string) => void;
  onParamReset: (key: string) => void;
};

type DraftValidation = {
  status: ValidationStatus;
  messages: string[];
};

const readNumber = (value: string | undefined, fallback?: number | null) => {
  if (value == null || value === "") return fallback ?? 0;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback ?? 0;
};

const featureSizeForParams = (target: PatternTarget | SingleTarget, params: Record<string, string>) => {
  if (target.type === "single_planar_feature") {
    if (target.feature_kind === "circular_hole") {
      return { diameter: readNumber(params.hole_diameter, target.measured.diameter ?? 0) };
    }
    return {
      width: readNumber(params.width, target.measured.width ?? 0),
      height: readNumber(params.height, target.measured.height ?? 0),
    };
  }

  if (target.feature_kind === "circular_hole") {
    const measured = typeof target.measured.feature_size === "number" ? target.measured.feature_size : 0;
    return { diameter: readNumber(params.hole_diameter, measured) };
  }

  const measured =
    typeof target.measured.feature_size === "number"
      ? { width: target.measured.feature_size, height: target.measured.feature_size }
      : target.measured.feature_size;
  return {
    width: readNumber(params.width, measured.width),
    height: readNumber(params.height, measured.height),
  };
};

const polygonBounds = (polygon: Point2D[]) => {
  const xs = polygon.map((point) => point[0]);
  const ys = polygon.map((point) => point[1]);
  return {
    minX: Math.min(...xs),
    maxX: Math.max(...xs),
    minY: Math.min(...ys),
    maxY: Math.max(...ys),
  };
};

const circleOutline = (center: Point2D, radius: number, segments = 24): Point2D[] =>
  Array.from({ length: segments }, (_, index) => {
    const angle = (2 * Math.PI * index) / segments;
    return [center[0] + Math.cos(angle) * radius, center[1] + Math.sin(angle) * radius];
  });

const rectOutline = (center: Point2D, width: number, height: number): Point2D[] => {
  const halfWidth = width / 2;
  const halfHeight = height / 2;
  return [
    [center[0] - halfWidth, center[1] - halfHeight],
    [center[0] + halfWidth, center[1] - halfHeight],
    [center[0] + halfWidth, center[1] + halfHeight],
    [center[0] - halfWidth, center[1] + halfHeight],
  ];
};

const toPath = (points: Point2D[]) =>
  points.length ? `M ${points.map((point) => `${point[0]} ${point[1]}`).join(" L ")} Z` : "";

const deriveSingleCenter = (outline: Point2D[]): Point2D => {
  const bounds = polygonBounds(outline);
  return [(bounds.minX + bounds.maxX) / 2, (bounds.minY + bounds.maxY) / 2];
};

const buildRectangularDraft = (target: PatternTarget, params: Record<string, string>) => {
  const fit = target.fit || {};
  const bounds = polygonBounds(target.face_polygon_2d);
  const size = featureSizeForParams(target, params);
  const countX = Math.max(1, Math.round(readNumber(params.count_x, target.measured.count_x ?? fit.x_positions?.length ?? 1)));
  const countY = Math.max(1, Math.round(readNumber(params.count_y, target.measured.count_y ?? fit.y_positions?.length ?? 1)));
  const spacingX = Math.max(0.1, readNumber(params.spacing_x, target.measured.spacing_x ?? 1));
  const spacingY = Math.max(0.1, readNumber(params.spacing_y, target.measured.spacing_y ?? 1));
  const centerX = fit.center_x ?? (bounds.minX + bounds.maxX) / 2;
  const centerY = fit.center_y ?? (bounds.minY + bounds.maxY) / 2;

  const xPositions = Array.from({ length: countX }, (_, index) => centerX + (index - (countX - 1) / 2) * spacingX);
  const yPositions = Array.from({ length: countY }, (_, index) => centerY + (index - (countY - 1) / 2) * spacingY);

  const guides = [
    ...xPositions.map((x) => ({ kind: "line" as const, points: [[x, bounds.minY], [x, bounds.maxY]] as Point2D[] })),
    ...yPositions.map((y) => ({ kind: "line" as const, points: [[bounds.minX, y], [bounds.maxX, y]] as Point2D[] })),
  ];

  const shapes = xPositions.flatMap((x) =>
    yPositions.map((y) => ({
      center: [x, y] as Point2D,
      outline:
        "diameter" in size
          ? circleOutline([x, y], (size.diameter ?? 0) / 2)
          : rectOutline([x, y], size.width ?? 0, size.height ?? 0),
    }))
  );

  return { guides, shapes };
};

const buildRadialDraft = (target: PatternTarget, params: Record<string, string>) => {
  const fit = target.fit || {};
  const bounds = polygonBounds(target.face_polygon_2d);
  const size = featureSizeForParams(target, params);
  const baseRingRadii = fit.ring_radii || [];
  const baseSpacing =
    target.measured.radial_spacing ??
    (baseRingRadii.length > 1 ? baseRingRadii[1] - baseRingRadii[0] : 12);
  const ringCount = Math.max(1, Math.round(readNumber(params.ring_count, target.measured.ring_count ?? baseRingRadii.length ?? 1)));
  const radialSpacing = Math.max(0.1, readNumber(params.radial_spacing, baseSpacing));
  const centerX = fit.center_x ?? (bounds.minX + bounds.maxX) / 2;
  const centerY = fit.center_y ?? (bounds.minY + bounds.maxY) / 2;
  const firstRadius = baseRingRadii[0] ?? radialSpacing;
  const holesPerRing = target.measured.holes_per_ring || fit.holes_per_ring || [];
  const radii = Array.from({ length: ringCount }, (_, index) => firstRadius + index * radialSpacing);

  const guides = radii.map((radius) => ({ kind: "ring" as const, center: [centerX, centerY] as Point2D, radius }));
  const shapes = radii.flatMap((radius, ringIndex) => {
    const holeCount = Math.max(1, holesPerRing[ringIndex] ?? holesPerRing[holesPerRing.length - 1] ?? 6);
    return Array.from({ length: holeCount }, (_, holeIndex) => {
      const angle = (2 * Math.PI * holeIndex) / holeCount;
      const center: Point2D = [centerX + Math.cos(angle) * radius, centerY + Math.sin(angle) * radius];
      return {
        center,
        outline:
          "diameter" in size
            ? circleOutline(center, (size.diameter ?? 0) / 2)
            : rectOutline(center, size.width ?? 0, size.height ?? 0),
      };
    });
  });

  return { guides, shapes };
};

const buildSingleDraft = (target: SingleTarget, params: Record<string, string>) => {
  const center = deriveSingleCenter(target.feature_outline_2d);
  const size = featureSizeForParams(target, params);
  const outline =
    target.feature_kind === "circular_hole"
      ? circleOutline(center, (size.diameter ?? 0) / 2)
      : rectOutline(center, size.width ?? 0, size.height ?? 0);
  return { guides: [], shapes: [{ center, outline }] };
};

const validateDraft = (target: PatternTarget | SingleTarget, draftShapes: Array<{ center: Point2D; outline: Point2D[] }>, params: Record<string, string>): DraftValidation => {
  const messages: string[] = [];
  const faceBounds = polygonBounds(target.face_polygon_2d);
  const margin = Math.max(0, readNumber(params.margin, "measured" in target ? (target as PatternTarget).measured.margin ?? 0 : 0));

  for (const shape of draftShapes) {
    const bounds = polygonBounds(shape.outline);
    if (bounds.minX < faceBounds.minX + margin || bounds.maxX > faceBounds.maxX - margin || bounds.minY < faceBounds.minY + margin || bounds.maxY > faceBounds.maxY - margin) {
      messages.push("Feature extends beyond the safe face boundary.");
      return { status: "invalid", messages };
    }
  }

  if (draftShapes.length > 1) {
    let nearestCenterDistance = Number.POSITIVE_INFINITY;
    for (let index = 0; index < draftShapes.length; index += 1) {
      for (let compareIndex = index + 1; compareIndex < draftShapes.length; compareIndex += 1) {
        const a = draftShapes[index].center;
        const b = draftShapes[compareIndex].center;
        const distance = Math.hypot(a[0] - b[0], a[1] - b[1]);
        if (distance < nearestCenterDistance) nearestCenterDistance = distance;
      }
    }
    const firstBounds = polygonBounds(draftShapes[0].outline);
    const featureMajor = Math.max(firstBounds.maxX - firstBounds.minX, firstBounds.maxY - firstBounds.minY);
    if (nearestCenterDistance <= featureMajor) {
      return { status: "invalid", messages: ["Repeated features overlap at the current spacing."] };
    }
    if (nearestCenterDistance <= featureMajor + 1.2) {
      messages.push("Wall thickness is getting tight between repeated features.");
    }
  }

  if (margin < 1) {
    messages.push("Margin is very small near the face boundary.");
  }

  return {
    status: messages.length ? "risk" : "safe",
    messages: messages.length ? messages : ["Geometry fits within the current planar target."],
  };
};

const resetButton = (
  key: string,
  disabled: boolean | undefined,
  onParamReset: (key: string) => void
) => (
  <button type="button" className="mini-reset" onClick={() => onParamReset(key)} disabled={disabled}>
    Reset
  </button>
);

export default function PlanarFaceEditor({
  target,
  params,
  disabled,
  onParamChange,
  onParamReset,
}: PlanarFaceEditorProps) {
  const draft =
    target.type === "planar_pattern_face"
      ? target.topology === "rectangular"
        ? buildRectangularDraft(target, params)
        : buildRadialDraft(target, params)
      : buildSingleDraft(target, params);
  const validation = validateDraft(target, draft.shapes, params);
  const bounds = polygonBounds(target.face_polygon_2d);
  const width = Math.max(bounds.maxX - bounds.minX, 1);
  const height = Math.max(bounds.maxY - bounds.minY, 1);
  const viewBox = `${bounds.minX - width * 0.08} ${bounds.minY - height * 0.08} ${width * 1.16} ${height * 1.16}`;
  const originalShapes =
    target.type === "planar_pattern_face"
      ? target.feature_geometry_2d.map((feature) => ({ center: feature.center, outline: feature.outline || [] }))
      : [{ center: deriveSingleCenter(target.feature_outline_2d), outline: target.feature_outline_2d }];

  const statusClass =
    validation.status === "invalid" ? "manufacturability-bad" : validation.status === "risk" ? "manufacturability-risk" : "manufacturability-safe";

  return (
    <div className="planar-editor">
      <div className="planar-editor-header">
        <div>
          <div className="status-label">2D face editor</div>
          <div className="validation-headline">{target.label}</div>
          <div className="muted">{target.summary}</div>
        </div>
        <div className={`manufacturability-pill ${statusClass}`}>
          {validation.status === "invalid" ? "Invalid" : validation.status === "risk" ? "Risk" : "Safe"}
        </div>
      </div>

      <div className="face-editor-stage">
        <svg className="face-editor-canvas" viewBox={viewBox} role="img" aria-label={`${target.label} 2D editor`}>
          <path d={toPath(target.face_polygon_2d)} className="face-boundary" />

          {draft.guides.map((guide, index) =>
            guide.kind === "line" ? (
              <path
                key={`guide-${index}`}
                d={`M ${guide.points[0][0]} ${guide.points[0][1]} L ${guide.points[1][0]} ${guide.points[1][1]}`}
                className="guide-line"
              />
            ) : (
              <circle
                key={`guide-${index}`}
                cx={guide.center[0]}
                cy={guide.center[1]}
                r={guide.radius}
                className="guide-ring"
              />
            )
          )}

          {originalShapes.map((shape, index) => (
            <path key={`ghost-${index}`} d={toPath(shape.outline)} className="ghost-shape" />
          ))}

          {draft.shapes.map((shape, index) => (
            <path key={`draft-${index}`} d={toPath(shape.outline)} className={`draft-shape ${statusClass}`} />
          ))}
        </svg>
        <div className="face-editor-legend">
          <span><i className="legend-swatch ghost" /> Previous</span>
          <span><i className={`legend-swatch ${statusClass}`} /> Current draft</span>
        </div>
      </div>

      <div className="warning-list">
        {validation.messages.map((message) => (
          <span key={message} className={`warning-chip ${validation.status === "safe" ? "subtle" : ""}`}>
            {message}
          </span>
        ))}
      </div>

      <div className="planar-controls">
        {target.type === "planar_pattern_face" && target.feature_kind === "circular_hole" ? (
          <label className="field-row compact-field">
            <span>Feature size mm</span>
            <div className="field-inline">
              <input type="number" inputMode="decimal" step="any" value={params.hole_diameter || ""} onChange={(event) => onParamChange("hole_diameter", event.target.value)} disabled={disabled} />
              {resetButton("hole_diameter", disabled, onParamReset)}
            </div>
          </label>
        ) : null}

        {target.type === "planar_pattern_face" && target.feature_kind === "rectangular_cutout" ? (
          <>
            <label className="field-row compact-field">
              <span>Width mm</span>
              <div className="field-inline">
                <input type="number" inputMode="decimal" step="any" value={params.width || ""} onChange={(event) => onParamChange("width", event.target.value)} disabled={disabled} />
                {resetButton("width", disabled, onParamReset)}
              </div>
            </label>
            <label className="field-row compact-field">
              <span>Height mm</span>
              <div className="field-inline">
                <input type="number" inputMode="decimal" step="any" value={params.height || ""} onChange={(event) => onParamChange("height", event.target.value)} disabled={disabled} />
                {resetButton("height", disabled, onParamReset)}
              </div>
            </label>
          </>
        ) : null}

        {target.type === "planar_pattern_face" && target.topology === "rectangular" ? (
          <>
            <label className="field-row compact-field">
              <span>Spacing X mm</span>
              <div className="field-inline">
                <input type="number" inputMode="decimal" step="any" value={params.spacing_x || ""} onChange={(event) => onParamChange("spacing_x", event.target.value)} disabled={disabled} />
                {resetButton("spacing_x", disabled, onParamReset)}
              </div>
            </label>
            <label className="field-row compact-field">
              <span>Spacing Y mm</span>
              <div className="field-inline">
                <input type="number" inputMode="decimal" step="any" value={params.spacing_y || ""} onChange={(event) => onParamChange("spacing_y", event.target.value)} disabled={disabled} />
                {resetButton("spacing_y", disabled, onParamReset)}
              </div>
            </label>
            <label className="field-row compact-field">
              <span>Count X</span>
              <div className="field-inline">
                <input type="number" inputMode="numeric" min="1" step="1" value={params.count_x || ""} onChange={(event) => onParamChange("count_x", event.target.value)} disabled={disabled} />
                {resetButton("count_x", disabled, onParamReset)}
              </div>
            </label>
            <label className="field-row compact-field">
              <span>Count Y</span>
              <div className="field-inline">
                <input type="number" inputMode="numeric" min="1" step="1" value={params.count_y || ""} onChange={(event) => onParamChange("count_y", event.target.value)} disabled={disabled} />
                {resetButton("count_y", disabled, onParamReset)}
              </div>
            </label>
          </>
        ) : null}

        {target.type === "planar_pattern_face" && target.topology === "radial" ? (
          <>
            <label className="field-row compact-field">
              <span>Radial spacing mm</span>
              <div className="field-inline">
                <input type="number" inputMode="decimal" step="any" value={params.radial_spacing || ""} onChange={(event) => onParamChange("radial_spacing", event.target.value)} disabled={disabled} />
                {resetButton("radial_spacing", disabled, onParamReset)}
              </div>
            </label>
            <label className="field-row compact-field">
              <span>Ring count</span>
              <div className="field-inline">
                <input type="number" inputMode="numeric" min="1" step="1" value={params.ring_count || ""} onChange={(event) => onParamChange("ring_count", event.target.value)} disabled={disabled} />
                {resetButton("ring_count", disabled, onParamReset)}
              </div>
            </label>
          </>
        ) : null}

        {target.type === "planar_pattern_face" ? (
          <>
            <label className="field-row compact-field">
              <span>Margin mm</span>
              <div className="field-inline">
                <input type="number" inputMode="decimal" step="any" value={params.margin || ""} onChange={(event) => onParamChange("margin", event.target.value)} disabled={disabled} />
                {resetButton("margin", disabled, onParamReset)}
              </div>
            </label>
            {target.measured.center_hole_diameter != null ? (
              <label className="field-row compact-field">
                <span>Center hole mm</span>
                <div className="field-inline">
                  <input type="number" inputMode="decimal" step="any" value={params.center_hole_diameter || ""} onChange={(event) => onParamChange("center_hole_diameter", event.target.value)} disabled={disabled} />
                  {resetButton("center_hole_diameter", disabled, onParamReset)}
                </div>
              </label>
            ) : null}
          </>
        ) : null}

        {target.type === "single_planar_feature" && target.feature_kind === "circular_hole" ? (
          <label className="field-row compact-field">
            <span>Diameter mm</span>
            <div className="field-inline">
              <input type="number" inputMode="decimal" step="any" value={params.hole_diameter || ""} onChange={(event) => onParamChange("hole_diameter", event.target.value)} disabled={disabled} />
              {resetButton("hole_diameter", disabled, onParamReset)}
            </div>
          </label>
        ) : null}

        {target.type === "single_planar_feature" && target.feature_kind !== "circular_hole" ? (
          <>
            <label className="field-row compact-field">
              <span>Width mm</span>
              <div className="field-inline">
                <input type="number" inputMode="decimal" step="any" value={params.width || ""} onChange={(event) => onParamChange("width", event.target.value)} disabled={disabled} />
                {resetButton("width", disabled, onParamReset)}
              </div>
            </label>
            <label className="field-row compact-field">
              <span>Height mm</span>
              <div className="field-inline">
                <input type="number" inputMode="decimal" step="any" value={params.height || ""} onChange={(event) => onParamChange("height", event.target.value)} disabled={disabled} />
                {resetButton("height", disabled, onParamReset)}
              </div>
            </label>
          </>
        ) : null}
      </div>
    </div>
  );
}
