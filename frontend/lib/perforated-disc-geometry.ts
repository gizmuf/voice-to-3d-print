"use client";

import type { BodyNode } from "../types/editable-model";

export type Point2D = [number, number];

export type Point3D = {
  x: number;
  y: number;
  z: number;
};

export type DiscSelectedPart = "outer" | "pattern" | "center";

export type DiscGeometry = {
  outerDiameter: number;
  thickness: number;
  holeDiameter: number;
  centerHoleDiameter: number;
  ringCount: number;
  radialSpacing: number;
  tangentialSpacing: number;
  edgeMargin: number;
};

export type DiscLayout = {
  outerRadius: number;
  thickness: number;
  holeDiameter: number;
  centerHoleDiameter: number;
  ringCount: number;
  radialSpacing: number;
  tangentialSpacing: number;
  edgeMargin: number;
  ringRadii: number[];
  holesPerRing: number[];
  holes: Array<{ center: Point2D; radius: number }>;
  status: "safe" | "risk" | "invalid";
  messages: string[];
};

export type DiscSelectionHit = {
  featureId: string;
  label: string;
  confidence: number;
  fallbackToOuter: boolean;
  anchorPoint: Point3D;
  focusDistance: number;
};

export type SemanticAnnotation = {
  id: string;
  label: string;
  point: Point3D;
};

const MIN_WALL_MM = 0.8;
export const DISC_PICK_CONFIDENCE = {
  center: 0.96,
  pattern: 0.9,
  outer: 0.8,
  minNarrowFeature: 0.88,
} as const;

export const asNumber = (value: string | number | boolean | undefined, fallback: number) => {
  if (typeof value === "number") return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return fallback;
};

export function extractDiscGeometry(rootBody: BodyNode): DiscGeometry {
  const centerHoleBody = rootBody.children.find((child) => child.label === "Center hole" || child.kind === "hole");
  const patternBody = rootBody.children.find((child) => child.kind === "circular_pattern");
  const thicknessBody = rootBody.children.find((child) => child.kind === "thickness");

  return {
    outerDiameter: asNumber(rootBody.params.outer_diameter, 340),
    thickness: asNumber(thicknessBody?.params.thickness_mm, asNumber(rootBody.params.thickness, 15)),
    holeDiameter: asNumber(patternBody?.params.hole_diameter_mm, 7.08),
    centerHoleDiameter: asNumber(centerHoleBody?.params.diameter_mm, 32.93),
    ringCount: Math.max(1, Math.round(asNumber(patternBody?.params.ring_count, 12))),
    radialSpacing: asNumber(patternBody?.params.radial_spacing_mm, 9.387),
    tangentialSpacing: asNumber(patternBody?.params.tangential_spacing_mm, 7),
    edgeMargin: asNumber(patternBody?.params.edge_margin_mm, 12.421),
  };
}

export function buildPerforatedDiscLayout({
  outerDiameter,
  thickness,
  holeDiameter,
  centerHoleDiameter,
  ringCount,
  radialSpacing,
  tangentialSpacing,
  edgeMargin,
}: DiscGeometry): DiscLayout {
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
}

export function inferDiscSelectedPart(
  selectedFeatureId: string | null,
  rootId: string,
  patternId: string,
  centerHoleId: string
): DiscSelectedPart {
  if (selectedFeatureId === centerHoleId) return "center";
  if (selectedFeatureId === patternId) return "pattern";
  if (!selectedFeatureId || selectedFeatureId === rootId) return "outer";
  return "outer";
}

export function classifyPerforatedDiscClick(
  point: Point3D,
  rootBody: BodyNode
): DiscSelectionHit | null {
  const patternBody = rootBody.children.find((child) => child.kind === "circular_pattern");
  const centerHoleBody = rootBody.children.find((child) => child.label === "Center hole" || child.kind === "hole");
  const layout = buildPerforatedDiscLayout(extractDiscGeometry(rootBody));
  const distance = Math.hypot(point.x, point.y);

  if (centerHoleBody && distance <= layout.centerHoleDiameter / 2) {
    return {
      featureId: centerHoleBody.id,
      label: centerHoleBody.label,
      confidence: DISC_PICK_CONFIDENCE.center,
      fallbackToOuter: false,
      anchorPoint: { x: 0, y: 0, z: 0 },
      focusDistance: Math.max(layout.centerHoleDiameter * 2.8, 28),
    };
  }

  if (patternBody) {
    const hitHole = layout.holes.find(
      (hole) => Math.hypot(point.x - hole.center[0], point.y - hole.center[1]) <= hole.radius * 1.4
    );
    if (hitHole) {
      return {
        featureId: patternBody.id,
        label: patternBody.label,
        confidence: DISC_PICK_CONFIDENCE.pattern,
        fallbackToOuter: false,
        anchorPoint: { x: hitHole.center[0], y: hitHole.center[1], z: 0 },
        focusDistance: Math.max(layout.radialSpacing * 4, 42),
      };
    }
  }

  if (distance <= layout.outerRadius) {
    return {
      featureId: rootBody.id,
      label: rootBody.label,
      confidence: DISC_PICK_CONFIDENCE.outer,
      fallbackToOuter: true,
      anchorPoint: { x: 0, y: 0, z: 0 },
      focusDistance: layout.outerRadius * 2.4,
    };
  }

  return null;
}

export function getPerforatedDiscFocusTarget(rootBody: BodyNode, selectedFeatureId: string): DiscSelectionHit | null {
  const patternBody = rootBody.children.find((child) => child.kind === "circular_pattern");
  const centerHoleBody = rootBody.children.find((child) => child.label === "Center hole" || child.kind === "hole");
  const layout = buildPerforatedDiscLayout(extractDiscGeometry(rootBody));

  if (selectedFeatureId === centerHoleBody?.id) {
    return {
      featureId: centerHoleBody.id,
      label: centerHoleBody.label,
      confidence: 1,
      fallbackToOuter: false,
      anchorPoint: { x: 0, y: 0, z: 0 },
      focusDistance: Math.max(layout.centerHoleDiameter * 2.8, 28),
    };
  }

  if (selectedFeatureId === patternBody?.id) {
    const outerRingRadius = layout.ringRadii[layout.ringRadii.length - 1] ?? layout.outerRadius * 0.6;
    return {
      featureId: patternBody.id,
      label: patternBody.label,
      confidence: 1,
      fallbackToOuter: false,
      anchorPoint: { x: outerRingRadius * 0.55, y: outerRingRadius * 0.2, z: 0 },
      focusDistance: Math.max(layout.radialSpacing * 4, 42),
    };
  }

  return {
    featureId: rootBody.id,
    label: rootBody.label,
    confidence: 1,
    fallbackToOuter: true,
    anchorPoint: { x: 0, y: 0, z: 0 },
    focusDistance: layout.outerRadius * 2.4,
  };
}

export function getPerforatedDiscAnnotations(rootBody: BodyNode, selectedFeatureId: string | null): SemanticAnnotation[] {
  const patternBody = rootBody.children.find((child) => child.kind === "circular_pattern");
  const centerHoleBody = rootBody.children.find((child) => child.label === "Center hole" || child.kind === "hole");
  const geometry = extractDiscGeometry(rootBody);
  const layout = buildPerforatedDiscLayout(geometry);

  if (selectedFeatureId === centerHoleBody?.id) {
    return [
      {
        id: "center-hole-diameter",
        label: `⌀ ${geometry.centerHoleDiameter.toFixed(2)} mm`,
        point: { x: geometry.centerHoleDiameter * 0.55, y: 0, z: 0 },
      },
    ];
  }

  if (selectedFeatureId === patternBody?.id) {
    const targetRadius = layout.ringRadii[Math.max(0, layout.ringRadii.length - 2)] ?? layout.ringRadii[0] ?? 0;
    return [
      {
        id: "pattern-hole-diameter",
        label: `⌀ ${geometry.holeDiameter.toFixed(2)} mm`,
        point: { x: targetRadius, y: 0, z: 0 },
      },
      {
        id: "pattern-radial-spacing",
        label: `${geometry.radialSpacing.toFixed(2)} mm radial spacing`,
        point: { x: targetRadius + geometry.radialSpacing * 0.5, y: geometry.radialSpacing * 0.45, z: 0 },
      },
    ];
  }

  return [
    {
      id: "outer-diameter",
      label: `${geometry.outerDiameter.toFixed(0)} mm outer diameter`,
      point: { x: layout.outerRadius * 0.72, y: -layout.outerRadius * 0.72, z: 0 },
    },
    {
      id: "disc-thickness",
      label: `${geometry.thickness.toFixed(1)} mm thick`,
      point: { x: 0, y: layout.outerRadius * 0.82, z: 0 },
    },
  ];
}
