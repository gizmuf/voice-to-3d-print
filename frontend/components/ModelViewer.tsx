"use client";

import { Suspense, createElement, useEffect, useMemo, useState } from "react";
import { Bounds, Html, OrbitControls, useGLTF } from "@react-three/drei";
import { Canvas, type ThreeEvent } from "@react-three/fiber";
import type { Material, Mesh } from "three";
import { Color, MOUSE } from "three";

export type SelectionPayload = {
  objectName: string;
  point: { x: number; y: number; z: number };
  normal: { x: number; y: number; z: number } | null;
};

export type ViewerSelectionMarker = {
  point: { x: number; y: number; z: number };
  label: string;
};

export type ViewerCameraNormal = {
  x: number;
  y: number;
  z: number;
};

type ModelViewerProps = {
  src?: string | null;
  ghostModelUrl?: string | null;
  label?: string;
  showChanges?: boolean;
  isUpdating?: boolean;
  defaultInteractionMode?: "orbit" | "pan";
  defaultCameraPreset?: "iso" | "front";
  defaultCameraNormal?: ViewerCameraNormal | null;
  resetViewSignal?: number;
  onSelect?: (payload: SelectionPayload) => void;
  selectionMarker?: ViewerSelectionMarker | null;
};

type LoadedModelProps = {
  src: string;
  ghost?: boolean;
  hoveredObjectId: string | null;
  selectedObjectId: string | null;
  onHover?: (objectId: string | null) => void;
  onSelect?: (payload: SelectionPayload, objectId: string) => void;
};

const GHOST_OPACITY = 0.25;
const HOVER_COLOR = new Color("#f59f3a");
const SELECTED_COLOR = new Color("#2b8c7a");
const BASE_EMISSIVE = new Color("#000000");

const isMesh = (value: unknown): value is Mesh => {
  return Boolean(value && typeof value === "object" && "isMesh" in (value as Mesh));
};

const hasEmissive = (
  material: Material
): material is Material & { emissive: Color; emissiveIntensity: number } => {
  return "emissive" in material && material.emissive instanceof Color;
};

const cloneMaterial = (material: Material) => {
  const cloned = material.clone();
  if ("toneMapped" in cloned) {
    cloned.toneMapped = true;
  }
  return cloned;
};

function LoadedModel({
  src,
  ghost = false,
  hoveredObjectId,
  selectedObjectId,
  onHover,
  onSelect,
}: LoadedModelProps) {
  const gltf = useGLTF(src);
  const scene = useMemo(() => gltf.scene.clone(true), [gltf.scene]);
  const meshes = useMemo(() => {
    const collected: Mesh[] = [];
    scene.traverse((child) => {
      if (isMesh(child)) {
        if (Array.isArray(child.material)) {
          child.material = child.material.map((material) => cloneMaterial(material));
        } else if (child.material) {
          child.material = cloneMaterial(child.material);
        }
        collected.push(child);
      }
    });
    return collected;
  }, [scene]);

  useEffect(() => {
    for (const mesh of meshes) {
      const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
      const isHovered = mesh.uuid === hoveredObjectId;
      const isSelected = mesh.uuid === selectedObjectId;
      const tint = isSelected ? SELECTED_COLOR : isHovered ? HOVER_COLOR : BASE_EMISSIVE;

      materials.forEach((material) => {
        if ("transparent" in material) {
          material.transparent = ghost;
        }
        if ("opacity" in material) {
          material.opacity = ghost ? GHOST_OPACITY : 1;
        }
        if ("depthWrite" in material) {
          material.depthWrite = !ghost;
        }
        if (hasEmissive(material)) {
          material.emissive.copy(tint);
          material.emissiveIntensity = ghost ? 0 : isSelected ? 0.5 : isHovered ? 0.35 : 0;
        }
      });
    }
  }, [ghost, hoveredObjectId, meshes, selectedObjectId]);

  const handlePointerMove = (event: ThreeEvent<PointerEvent>) => {
    if (ghost) return;
    event.stopPropagation();
    onHover?.(event.object.uuid);
  };

  const handlePointerOut = (event: ThreeEvent<PointerEvent>) => {
    if (ghost) return;
    event.stopPropagation();
    onHover?.(null);
  };

  const handleClick = (event: ThreeEvent<MouseEvent>) => {
    if (ghost) return;
    event.stopPropagation();
    onSelect?.(
      {
        objectName: event.object.name || "mesh",
        point: {
          x: Number(event.point.x.toFixed(3)),
          y: Number(event.point.y.toFixed(3)),
          z: Number(event.point.z.toFixed(3)),
        },
        normal: event.face?.normal
          ? {
              x: Number(event.face.normal.x.toFixed(3)),
              y: Number(event.face.normal.y.toFixed(3)),
              z: Number(event.face.normal.z.toFixed(3)),
            }
          : null,
      },
      event.object.uuid
    );
  };

  return createElement("primitive", {
    object: scene,
    onPointerMove: handlePointerMove,
    onPointerOut: handlePointerOut,
    onClick: handleClick,
  });
}

function SelectionMarker({ marker }: { marker: ViewerSelectionMarker }) {
  return createElement(
    "group",
    { position: [marker.point.x, marker.point.y, marker.point.z] },
    createElement(
      "mesh",
      null,
      createElement("sphereGeometry", { args: [2.2, 18, 18] }),
      createElement("meshStandardMaterial", {
        color: "#f59f3a",
        emissive: "#f59f3a",
        emissiveIntensity: 0.4,
      })
    ),
    createElement(
      Html,
      { center: true, distanceFactor: 14 },
      createElement("div", { className: "viewer-selection-badge" }, marker.label)
    )
  );
}

export default function ModelViewer({
  src,
  ghostModelUrl,
  label,
  showChanges = false,
  isUpdating = false,
  defaultInteractionMode = "orbit",
  defaultCameraPreset = "iso",
  defaultCameraNormal = null,
  resetViewSignal = 0,
  onSelect,
  selectionMarker,
}: ModelViewerProps) {
  const [hoveredObjectId, setHoveredObjectId] = useState<string | null>(null);
  const [selectedObjectId, setSelectedObjectId] = useState<string | null>(null);
  const [selectedLabel, setSelectedLabel] = useState<string | null>(null);
  const [interactionMode, setInteractionMode] = useState<"orbit" | "pan">(defaultInteractionMode);

  useEffect(() => {
    setHoveredObjectId(null);
    setSelectedObjectId(null);
    setSelectedLabel(selectionMarker?.label || null);
  }, [src, ghostModelUrl]);

  useEffect(() => {
    setInteractionMode(defaultInteractionMode);
  }, [defaultInteractionMode, src, ghostModelUrl]);

  useEffect(() => {
    setSelectedLabel(selectionMarker?.label || null);
  }, [selectionMarker]);

  const hasGhost = Boolean(showChanges && ghostModelUrl);
  const normalizedCamera = useMemo(() => {
    if (defaultCameraPreset !== "front" || !defaultCameraNormal) return null;
    const length = Math.hypot(defaultCameraNormal.x, defaultCameraNormal.y, defaultCameraNormal.z) || 1;
    return {
      x: defaultCameraNormal.x / length,
      y: defaultCameraNormal.y / length,
      z: defaultCameraNormal.z / length,
    };
  }, [defaultCameraNormal, defaultCameraPreset]);
  const cameraPosition =
    defaultCameraPreset === "front"
      ? (normalizedCamera
          ? ([normalizedCamera.x * 3.6, normalizedCamera.y * 3.6, normalizedCamera.z * 3.6] as const)
          : ([0, 0, 3.6] as const))
      : ([2.8, 2.2, 2.8] as const);
  const viewerKey = `${src || "empty"}:${ghostModelUrl || "noghost"}:${defaultCameraPreset}:${normalizedCamera?.x || 0}:${normalizedCamera?.y || 0}:${normalizedCamera?.z || 0}:${resetViewSignal}`;

  if (!src) {
    return (
      <div className="model-placeholder">
        <div className="placeholder-title">No model yet</div>
        <div className="placeholder-body">
          Describe a design or import an STL to start the workspace.
        </div>
      </div>
    );
  }

  return (
    <div className="model-viewer-wrap">
      <Canvas
        key={viewerKey}
        camera={{ position: cameraPosition, fov: 40 }}
        dpr={[1, 1.5]}
        frameloop="demand"
        onPointerMissed={() => setHoveredObjectId(null)}
      >
        {createElement("color", { attach: "background", args: ["#fff8ef"] })}
        {createElement("ambientLight", { intensity: 0.9 })}
        {createElement("directionalLight", { position: [5, 8, 4], intensity: 1.25 })}
        {createElement("directionalLight", { position: [-4, 3, -5], intensity: 0.4 })}
        <Suspense fallback={null}>
          <Bounds fit clip margin={1.2}>
            <>
              {hasGhost && ghostModelUrl ? (
                <LoadedModel
                  src={ghostModelUrl}
                  ghost
                  hoveredObjectId={hoveredObjectId}
                  selectedObjectId={selectedObjectId}
                />
              ) : null}
              <LoadedModel
                src={src}
                hoveredObjectId={hoveredObjectId}
                selectedObjectId={selectedObjectId}
                onHover={setHoveredObjectId}
                onSelect={(payload, objectId) => {
                  setSelectedObjectId(objectId);
                  setSelectedLabel(selectionMarker?.label || payload.objectName);
                  onSelect?.(payload);
                }}
              />
              {selectionMarker ? <SelectionMarker marker={selectionMarker} /> : null}
            </>
          </Bounds>
        </Suspense>
        <OrbitControls
          enableDamping
          dampingFactor={0.12}
          enablePan
          rotateSpeed={0.6}
          zoomSpeed={0.85}
          panSpeed={0.85}
          mouseButtons={{
            LEFT: interactionMode === "pan" ? MOUSE.PAN : MOUSE.ROTATE,
            MIDDLE: MOUSE.DOLLY,
            RIGHT: interactionMode === "pan" ? MOUSE.ROTATE : MOUSE.PAN,
          }}
        />
      </Canvas>

      <div className="model-overlay">
        {label ? <div className="model-overlay-chip">{label}</div> : null}
        {hasGhost ? <div className="model-overlay-chip subtle">Showing changes</div> : null}
        <button
          type="button"
          className="model-overlay-chip model-overlay-button subtle"
          onClick={() => setInteractionMode((mode) => (mode === "orbit" ? "pan" : "orbit"))}
        >
          {interactionMode === "orbit" ? "Mode: orbit" : "Mode: pan"}
        </button>
        <div className="model-overlay-chip subtle">
          {interactionMode === "orbit"
            ? "Left drag orbit · right drag pan · scroll zoom"
            : "Left drag pan · right drag orbit · scroll zoom"}
        </div>
        {selectedLabel ? (
          <div className="model-overlay-chip accent">Selected {selectedLabel}</div>
        ) : null}
      </div>

      {isUpdating ? (
        <div className="model-loading">
          <div className="model-loading-spinner" />
          <span>Updating preview…</span>
        </div>
      ) : null}
    </div>
  );
}
