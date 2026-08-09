export type Point3 = { x: number; y: number; z: number };

/**
 * CAD/STL artifacts are Z-up. The GLB exporter rotates them -90 degrees
 * around X for the browser's Y-up coordinate system.
 */
export function cadPointToViewer(point: Point3): Point3 {
  return {
    x: point.x,
    y: point.z,
    z: -point.y,
  };
}

