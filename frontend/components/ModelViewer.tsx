"use client";

import { Suspense, createElement, useEffect, useMemo, useRef, useState, type MutableRefObject, type ReactNode } from "react";
import { Html, OrbitControls, useGLTF } from "@react-three/drei";
import { Canvas, type ThreeEvent, useFrame, useThree } from "@react-three/fiber";
import type { Material, Mesh, PerspectiveCamera } from "three";
import { Box3, Color, MOUSE, MathUtils, Sphere, Vector3 } from "three";

export type SelectionPayload = {
  objectName: string;
  topologyRef: string;
  triangleIndex: number | null;
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

export type ViewerFocusTarget = {
  point: { x: number; y: number; z: number };
  distance?: number;
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
  onClearSelection?: () => void;
  selectionMarker?: ViewerSelectionMarker | null;
  focusTarget?: ViewerFocusTarget | null;
  selectionChip?: ReactNode;
  annotations?: ReactNode;
};

type LoadedModelProps = {
  src: string;
  ghost?: boolean;
  viewerTheme?: "workbench" | "light";
  hoveredObjectId: string | null;
  selectedObjectId: string | null;
  onHover?: (objectId: string | null) => void;
  onSelect?: (payload: SelectionPayload, objectId: string) => void;
  controlsRef?: MutableRefObject<{ target: Vector3; update: () => void } | null>;
  fitDirection?: readonly [number, number, number];
  fitView?: boolean;
  motionRunning?: boolean;
  onMotionAvailable?: (available: boolean) => void;
};

type ModelLoadState =
  | { status: "idle" | "checking" | "ready"; message?: undefined }
  | { status: "error"; message: string };

type ViewerCommand = {
  id: number;
  type: "zoom-in" | "zoom-out";
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
  viewerTheme = "workbench",
  hoveredObjectId,
  selectedObjectId,
  onHover,
  onSelect,
  controlsRef,
  fitDirection = [1, 0.75, 1],
  fitView = false,
  motionRunning = false,
  onMotionAvailable,
}: LoadedModelProps) {
  const gltf = useGLTF(src);
  const { camera, size, invalidate } = useThree();
  const scene = useMemo(() => gltf.scene.clone(true), [gltf.scene]);
  const motionNode = useMemo(() => {
    let match = scene.getObjectByName("wheel") ?? null;
    if (!match) {
      scene.traverse((child) => {
        if (!match && child.name.toLowerCase() === "wheel") match = child;
      });
    }
    return match;
  }, [scene]);
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
    if (!ghost) onMotionAvailable?.(Boolean(motionNode));
    return () => {
      if (!ghost) onMotionAvailable?.(false);
    };
  }, [ghost, motionNode, onMotionAvailable]);

  useFrame((_, delta) => {
    if (!motionRunning || !motionNode) return;
    motionNode.rotation.z += delta * 1.8;
    invalidate();
  });

  useEffect(() => {
    if (!fitView) return;
    let innerFrame = 0;
    const outerFrame = requestAnimationFrame(() => {
      innerFrame = requestAnimationFrame(() => {
      scene.updateWorldMatrix(true, true);
        const box = new Box3().setFromObject(scene);
        if (box.isEmpty()) return;
        const center = box.getCenter(new Vector3());
        const radius = Math.max(box.getBoundingSphere(new Sphere()).radius, 0.001);
        const perspective = camera as PerspectiveCamera;
        const verticalFov = MathUtils.degToRad(perspective.fov || 40);
        const horizontalFov = 2 * Math.atan(Math.tan(verticalFov / 2) * Math.max(size.width / Math.max(size.height, 1), 0.01));
        const limitingFov = Math.max(Math.min(verticalFov, horizontalFov), MathUtils.degToRad(10));
        const distance = radius / Math.sin(limitingFov / 2);
        const direction = new Vector3(...fitDirection).normalize();

        camera.position.copy(center.clone().add(direction.multiplyScalar(distance)));
        perspective.near = Math.max(distance / 1000, 0.01);
        perspective.far = Math.max(distance * 10, 2000);
        perspective.updateProjectionMatrix();
        camera.lookAt(center);
        if (controlsRef?.current) {
          controlsRef.current.target.copy(center);
          controlsRef.current.update();
        }
        invalidate();
      });
    });
    return () => {
      cancelAnimationFrame(outerFrame);
      if (innerFrame) cancelAnimationFrame(innerFrame);
    };
  }, [camera, controlsRef, fitDirection, fitView, invalidate, scene, size.height, size.width, src]);

  // We `cloneMaterial` per mesh so hover/select tints don't leak into the
  // upstream cached gltf. Those cloned materials are owned by this component
  // and must be released on unmount or src change, otherwise the GPU
  // accumulates one set per design rebuild. Geometries are NOT disposed —
  // they're shared by reference with the cached gltf scene (Three's
  // Object3D.clone is shallow on geometry refs), so disposing them would
  // break the next consumer of the same source.
  useEffect(() => {
    return () => {
      for (const mesh of meshes) {
        const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
        for (const material of mats) {
          if (material) material.dispose();
        }
      }
    };
  }, [meshes]);

  useEffect(() => {
    for (const mesh of meshes) {
      const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
      const isHovered = mesh.uuid === hoveredObjectId;
      const isSelected = mesh.uuid === selectedObjectId;
      const tint = isSelected ? SELECTED_COLOR : isHovered ? HOVER_COLOR : BASE_EMISSIVE;

      materials.forEach((material) => {
        if (
          "color" in material &&
          material.color instanceof Color &&
          (!material.name || material.name === "DefaultMaterial")
        ) {
          material.color.set(viewerTheme === "workbench" ? "#9aa6b4" : "#777777");
        }
        if ("roughness" in material && typeof material.roughness === "number") {
          material.roughness = viewerTheme === "workbench" ? 0.72 : 0.82;
        }
        if ("metalness" in material && typeof material.metalness === "number") {
          material.metalness = 0.04;
        }
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
  }, [ghost, hoveredObjectId, meshes, selectedObjectId, viewerTheme]);

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
        topologyRef: `${event.object.name || "mesh"}#triangle:${event.faceIndex ?? "unknown"}`,
        triangleIndex: event.faceIndex ?? null,
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
      {
        center: true,
        distanceFactor: 18,
        position: [0, 3.2, 0],
        style: {
          pointerEvents: "none",
          whiteSpace: "nowrap",
          background: "rgba(255,255,255,0.86)",
          border: "1px solid rgba(245,159,58,0.45)",
          borderRadius: 999,
          color: "rgba(90,58,0,0.95)",
          fontSize: 11,
          fontWeight: 700,
          padding: "3px 8px",
        },
      },
      marker.label
    )
  );
}

function CameraTargetController({
  focusTarget,
  controlsRef,
}: {
  focusTarget: ViewerFocusTarget | null;
  controlsRef: MutableRefObject<{ target: Vector3; update: () => void } | null>;
}) {
  const { camera, invalidate } = useThree();
  const desiredTargetRef = useRef<Vector3 | null>(null);
  const desiredCameraRef = useRef<Vector3 | null>(null);

  useEffect(() => {
    if (!focusTarget) return;
    const nextTarget = new Vector3(focusTarget.point.x, focusTarget.point.y, focusTarget.point.z);
    const currentTarget = controlsRef.current?.target?.clone() ?? new Vector3(0, 0, 0);
    const direction = camera.position.clone().sub(currentTarget);
    if (direction.lengthSq() < 0.0001) {
      direction.set(0, 0, 1);
    }
    direction.normalize();
    const distance = Math.max(focusTarget.distance ?? camera.position.distanceTo(currentTarget), 12);
    desiredTargetRef.current = nextTarget;
    desiredCameraRef.current = nextTarget.clone().add(direction.multiplyScalar(distance));
    invalidate();
  }, [camera.position, controlsRef, focusTarget, invalidate]);

  useFrame(() => {
    if (!desiredTargetRef.current || !desiredCameraRef.current) return;
    camera.position.lerp(desiredCameraRef.current, 0.16);
    if (controlsRef.current) {
      controlsRef.current.target.lerp(desiredTargetRef.current, 0.16);
      controlsRef.current.update();
      if (
        camera.position.distanceTo(desiredCameraRef.current) < 0.05 &&
        controlsRef.current.target.distanceTo(desiredTargetRef.current) < 0.05
      ) {
        desiredTargetRef.current = null;
        desiredCameraRef.current = null;
      }
      invalidate();
    }
  });

  return null;
}

function CameraCommandController({
  command,
  controlsRef,
}: {
  command: ViewerCommand | null;
  controlsRef: MutableRefObject<{ target: Vector3; update: () => void } | null>;
}) {
  const { camera, invalidate } = useThree();

  useEffect(() => {
    if (!command) return;
    const target = controlsRef.current?.target?.clone() ?? new Vector3(0, 0, 0);
    const offset = camera.position.clone().sub(target);
    const currentDistance = Math.max(offset.length(), 0.001);
    const factor = command.type === "zoom-in" ? 0.72 : 1.4;
    const nextDistance = Math.min(Math.max(currentDistance * factor, 6), 2400);
    camera.position.copy(target.clone().add(offset.normalize().multiplyScalar(nextDistance)));
    camera.updateProjectionMatrix();
    controlsRef.current?.update();
    invalidate();
  }, [camera, command, controlsRef, invalidate]);

  return null;
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
  onClearSelection,
  selectionMarker,
  focusTarget = null,
  selectionChip,
  annotations,
}: ModelViewerProps) {
  const [hoveredObjectId, setHoveredObjectId] = useState<string | null>(null);
  const [selectedObjectId, setSelectedObjectId] = useState<string | null>(null);
  const [interactionMode, setInteractionMode] = useState<"orbit" | "pan">(defaultInteractionMode);
  const [viewerTheme, setViewerTheme] = useState<"workbench" | "light">("workbench");
  const [showGrid, setShowGrid] = useState(true);
  const [appearanceOpen, setAppearanceOpen] = useState(false);
  const [loadState, setLoadState] = useState<ModelLoadState>({ status: "idle" });
  const [internalResetSignal, setInternalResetSignal] = useState(0);
  const [viewerCommand, setViewerCommand] = useState<ViewerCommand | null>(null);
  const [motionAvailable, setMotionAvailable] = useState(false);
  const [motionRunning, setMotionRunning] = useState(false);
  const controlsRef = useRef<{ target: Vector3; update: () => void } | null>(null);
  const appearanceRef = useRef<HTMLDivElement | null>(null);
  const commandIdRef = useRef(0);

  useEffect(() => {
    setHoveredObjectId(null);
    setSelectedObjectId(null);
    setMotionRunning(false);
  }, [src, ghostModelUrl]);

  useEffect(() => {
    setInteractionMode(defaultInteractionMode);
  }, [defaultInteractionMode, src, ghostModelUrl]);

  useEffect(() => {
    if (!appearanceOpen) return;
    const closeOutside = (event: PointerEvent) => {
      if (!appearanceRef.current?.contains(event.target as Node)) setAppearanceOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setAppearanceOpen(false);
    };
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [appearanceOpen]);

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
  const cameraPosition = useMemo(
    () =>
      defaultCameraPreset === "front"
        ? (normalizedCamera
            ? ([normalizedCamera.x * 360, normalizedCamera.y * 360, normalizedCamera.z * 360] as const)
            : ([0, 0, 360] as const))
        : ([240, 180, 240] as const),
    [defaultCameraPreset, normalizedCamera?.x, normalizedCamera?.y, normalizedCamera?.z]
  );
  const viewerKey = `${src || "empty"}:${ghostModelUrl || "noghost"}:${defaultCameraPreset}:${normalizedCamera?.x || 0}:${normalizedCamera?.y || 0}:${normalizedCamera?.z || 0}:${resetViewSignal}:${internalResetSignal}`;

  const issueViewerCommand = (type: ViewerCommand["type"]) => {
    commandIdRef.current += 1;
    setViewerCommand({ id: commandIdRef.current, type });
  };

  const resetView = () => {
    setHoveredObjectId(null);
    setSelectedObjectId(null);
    setViewerCommand(null);
    setInteractionMode(defaultInteractionMode);
    setInternalResetSignal((value) => value + 1);
    onClearSelection?.();
  };

  useEffect(() => {
    if (!src) {
      setLoadState({ status: "idle" });
      return;
    }

    const controller = new AbortController();
    setLoadState({ status: "checking" });
    fetch(src, {
      method: "HEAD",
      cache: "no-store",
      signal: controller.signal,
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error(`Model artifact returned ${response.status}.`);
        }
        setLoadState({ status: "ready" });
      })
      .catch((error) => {
        if (controller.signal.aborted) return;
        const message =
          error instanceof Error && error.message
            ? error.message
            : "Could not reach the generated model artifact.";
        setLoadState({
          status: "error",
          message: `${message} Make sure the backend is running and try rebuilding or refreshing.`,
        });
      });

    return () => controller.abort();
  }, [src]);

  if (!src) {
    return (
      <div className="model-placeholder">
        <div className="placeholder-title">No model yet</div>
        <div className="placeholder-body">
          Describe a design or import STEP/STP to start an editable workspace.
        </div>
      </div>
    );
  }

  if (loadState.status === "checking") {
    return (
      <div className="model-placeholder">
        <div className="placeholder-title">Loading model</div>
        <div className="placeholder-body">Checking the generated GLB artifact.</div>
      </div>
    );
  }

  if (loadState.status === "error") {
    return (
      <div className="model-placeholder">
        <div className="placeholder-title">Model unavailable</div>
        <div className="placeholder-body">{loadState.message}</div>
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
        onPointerMissed={() => {
          setHoveredObjectId(null);
          setSelectedObjectId(null);
          onClearSelection?.();
        }}
      >
        {createElement("color", { attach: "background", args: [viewerTheme === "workbench" ? "#18212b" : "#fff8ef"] })}
        {createElement("ambientLight", { intensity: viewerTheme === "workbench" ? 1.15 : 0.9 })}
        {createElement("directionalLight", { position: [5, 8, 4], intensity: viewerTheme === "workbench" ? 1.6 : 1.25 })}
        {createElement("directionalLight", { position: [-4, 3, -5], intensity: viewerTheme === "workbench" ? 0.75 : 0.4 })}
        {showGrid
          ? createElement("gridHelper", {
              args: [180, 36, viewerTheme === "workbench" ? "#536274" : "#ccbfae", viewerTheme === "workbench" ? "#293746" : "#eadfce"],
              position: [0, -0.04, 0],
            })
          : null}
        <Suspense fallback={null}>
          <>
            {hasGhost && ghostModelUrl ? (
              <LoadedModel
                src={ghostModelUrl}
                ghost
                viewerTheme={viewerTheme}
                hoveredObjectId={hoveredObjectId}
                selectedObjectId={selectedObjectId}
              />
            ) : null}
            <LoadedModel
              src={src}
              viewerTheme={viewerTheme}
              hoveredObjectId={hoveredObjectId}
              selectedObjectId={selectedObjectId}
              controlsRef={controlsRef}
              fitDirection={cameraPosition}
              fitView
              motionRunning={motionRunning}
              onMotionAvailable={setMotionAvailable}
              onHover={setHoveredObjectId}
              onSelect={(payload, objectId) => {
                setSelectedObjectId(objectId);
                onSelect?.(payload);
              }}
            />
            {selectionMarker ? <SelectionMarker marker={selectionMarker} /> : null}
            {annotations}
          </>
        </Suspense>
        <CameraTargetController focusTarget={focusTarget} controlsRef={controlsRef} />
        <CameraCommandController command={viewerCommand} controlsRef={controlsRef} />
        <OrbitControls
          ref={controlsRef as never}
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
        {hasGhost ? <div className="model-overlay-chip subtle">Showing changes</div> : null}
        <div className="model-overlay-chip subtle">Drag to orbit · wheel to zoom</div>
        <button
          type="button"
          aria-label="Zoom in"
          title="Zoom in"
          className="model-overlay-chip model-overlay-button"
          onClick={() => issueViewerCommand("zoom-in")}
        >
          +
        </button>
        <button
          type="button"
          aria-label="Zoom out"
          title="Zoom out"
          className="model-overlay-chip model-overlay-button"
          onClick={() => issueViewerCommand("zoom-out")}
        >
          −
        </button>
        <button
          type="button"
          aria-label="Reset view"
          className="model-overlay-chip model-overlay-button"
          onClick={resetView}
        >
          Reset view
        </button>
        <button
          type="button"
          className="model-overlay-chip model-overlay-button subtle"
          onClick={() => setInteractionMode((mode) => (mode === "orbit" ? "pan" : "orbit"))}
        >
          {interactionMode === "orbit" ? "Mode: orbit" : "Mode: pan"}
        </button>
        {motionAvailable ? (
          <button
            type="button"
            className="model-overlay-chip model-overlay-button subtle"
            aria-pressed={motionRunning}
            title="Podgląd ruchu zespołu — bez symulacji tarcia i obciążeń"
            onClick={() => setMotionRunning((running) => !running)}
          >
            {motionRunning ? "Zatrzymaj koło" : "Test obrotu"}
          </button>
        ) : null}
        <div ref={appearanceRef} className="model-appearance-panel">
          <button
            type="button"
            className="model-appearance-trigger"
            aria-expanded={appearanceOpen}
            aria-controls="model-appearance-controls"
            onClick={() => setAppearanceOpen((current) => !current)}
          >
            <span aria-hidden>{appearanceOpen ? "▾" : "▸"}</span> Appearance
          </button>
          {appearanceOpen ? (
            <div id="model-appearance-controls" className="model-appearance-controls">
              <div className="model-appearance-segmented" aria-label="Viewer theme">
                <button type="button" data-active={viewerTheme === "workbench"} onClick={() => setViewerTheme("workbench")}>Workbench</button>
                <button type="button" data-active={viewerTheme === "light"} onClick={() => setViewerTheme("light")}>Light</button>
              </div>
              <label>
                <input type="checkbox" checked={showGrid} onChange={(event) => setShowGrid(event.target.checked)} />
                Grid
              </label>
            </div>
          ) : null}
        </div>
      </div>

      {selectionChip ? <div className="model-selection-chip-slot">{selectionChip}</div> : null}

      {isUpdating ? (
        <div className="model-loading">
          <div className="model-loading-spinner" />
          <span>Przeliczam model 3D…</span>
        </div>
      ) : null}
    </div>
  );
}
