"use client";

import { useFrame } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";

import type { DepthRelief } from "@/lib/depth-relief";

/** World size of the frame (16:9) and how far the nearest point stands out of it. */
export const W = 3.2;
export const H = 1.8;
export const Z = 0.85;
const ROW_STEP = 4;
const COL_STEP = 8;
/**
 * A grid triangle whose corners differ by more than this (0..1 depth) straddles an object's edge: it is
 * left out instead of stretched across the gap. On the wall clips a cell's median spread is ~0.01
 * and its 99th percentile 0.13-0.24, so this drops the 3-5% of cells that are real edges.
 */
const EDGE_CUT = 0.07;
/** The scan contour: one pass from the nearest depth to the farthest, then a rest. */
const SWEEP_RUN_S = 3.6;
const SWEEP_REST_S = 1.4;

/** A grid point (u, v across and down the frame, d its 0..1 depth) in the relief's local space. */
export const at = (u: number, v: number, d: number, lift = 0): [number, number, number] => [(u - 0.5) * W, (0.5 - v) * H, d * Z + lift];

/**
 * Adds the scan contour to a basic material: a thin bright band at one depth (`uSweep`, 0..1, off
 * below 0) plus a soft glow around it, read from each vertex's own depth. The uniform lives on
 * `userData.sweep`, where the frame loop moves it.
 */
function withSweep(m: THREE.MeshBasicMaterial) {
  const sweep = { value: -1 };
  m.userData.sweep = sweep;
  m.onBeforeCompile = (shader) => {
    shader.uniforms.uSweep = sweep;
    shader.vertexShader = shader.vertexShader
      .replace("#include <common>", "#include <common>\nattribute float depth;\nvarying float vDepth;")
      .replace("#include <begin_vertex>", "#include <begin_vertex>\nvDepth = depth;");
    shader.fragmentShader = shader.fragmentShader
      .replace("#include <common>", "#include <common>\nuniform float uSweep;\nvarying float vDepth;")
      .replace(
        "#include <opaque_fragment>",
        [
          "float sweepD = (vDepth - uSweep);",
          "outgoingLight += vec3(0.62) * exp(-sweepD * sweepD / 0.00012) + vec3(0.1) * exp(-sweepD * sweepD / 0.004);",
          "#include <opaque_fragment>",
        ].join("\n"),
      );
  };
  m.customProgramCacheKey = () => "relief-sweep";
  return m;
}

/**
 * The frame as a displaced surface: the clip's own video when it plays, else shaded by depth.
 * Cells that straddle an object's edge are dropped (see EDGE_CUT), so near objects stand clear of
 * what is behind them instead of dragging a sheet back to it.
 */
export function Surface({ relief, video, still }: { relief: DepthRelief; video: HTMLVideoElement | null; still: boolean }) {
  const geometry = useMemo(() => {
    const { w, h, values } = relief;
    // PlaneGeometry lays vertices out row by row from the top-left, the grid's own order.
    const g = new THREE.PlaneGeometry(W, H, w - 1, h - 1);
    const pos = g.getAttribute("position") as THREE.BufferAttribute;
    const shade = new Float32Array(pos.count * 3);
    const depth = new Float32Array(pos.count);
    for (let i = 0; i < pos.count; i++) {
      const d = values[i] / 255;
      depth[i] = d;
      pos.setZ(i, d * Z);
      const c = 0.1 + 0.8 * d;
      shade.set([c, c, c], i * 3);
    }
    // per triangle, not per cell: an edge then steps by half a cell, along the diagonal
    const index: number[] = [];
    const tri = (p: number, q: number, r: number) => {
      if (Math.max(depth[p], depth[q], depth[r]) - Math.min(depth[p], depth[q], depth[r]) <= EDGE_CUT) index.push(p, q, r);
    };
    for (let iy = 0; iy < h - 1; iy++) {
      for (let ix = 0; ix < w - 1; ix++) {
        const a = iy * w + ix;
        const b = a + w;
        tri(a, b, a + 1);
        tri(b, b + 1, a + 1);
      }
    }
    g.setIndex(index);
    g.setAttribute("color", new THREE.BufferAttribute(shade, 3));
    g.setAttribute("depth", new THREE.BufferAttribute(depth, 1));
    return g;
  }, [relief]);
  useEffect(() => () => geometry.dispose(), [geometry]);

  const texture = useMemo(() => {
    if (!video) return null;
    const t = new THREE.VideoTexture(video);
    t.colorSpace = THREE.SRGBColorSpace;
    return t;
  }, [video]);
  useEffect(() => () => texture?.dispose(), [texture]);

  const material = useMemo(
    () =>
      withSweep(
        texture
          ? new THREE.MeshBasicMaterial({ map: texture, color: "#cfcfcb", side: THREE.DoubleSide, toneMapped: false })
          : new THREE.MeshBasicMaterial({ vertexColors: true, side: THREE.DoubleSide, toneMapped: false }),
      ),
    [texture],
  );
  useEffect(() => () => material.dispose(), [material]);

  const mesh = useRef<THREE.Mesh>(null);
  useFrame(({ clock }) => {
    const sweep = (mesh.current?.material as THREE.Material | undefined)?.userData.sweep as { value: number } | undefined;
    if (!sweep) return;
    const t = clock.getElapsedTime() % (SWEEP_RUN_S + SWEEP_REST_S);
    // near to far: the contour walks out from the camera; none under reduced motion
    sweep.value = still || t >= SWEEP_RUN_S ? -1 : 1.02 - (t / SWEEP_RUN_S) * 1.04;
  });

  return <mesh ref={mesh} geometry={geometry} material={material} />;
}

/** Every 4th row and 8th column of the grid as lines on the surface (not across an edge): the scan-mesh look. */
export function ScanMesh({ relief }: { relief: DepthRelief }) {
  const geometry = useMemo(() => {
    const { w, h, values } = relief;
    const pts: number[] = [];
    const seg = (i0: number, j0: number, i1: number, j1: number) => {
      const d0 = values[j0 * w + i0] / 255;
      const d1 = values[j1 * w + i1] / 255;
      if (Math.abs(d1 - d0) > EDGE_CUT) return;
      pts.push(...at(i0 / (w - 1), j0 / (h - 1), d0, 0.004), ...at(i1 / (w - 1), j1 / (h - 1), d1, 0.004));
    };
    for (let iy = 0; iy < h; iy += ROW_STEP) {
      for (let ix = 0; ix < w - 1; ix++) seg(ix, iy, ix + 1, iy);
    }
    for (let ix = 0; ix < w; ix += COL_STEP) {
      for (let iy = 0; iy < h - 1; iy++) seg(ix, iy, ix, iy + 1);
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
    return g;
  }, [relief]);
  useEffect(() => () => geometry.dispose(), [geometry]);
  return (
    <lineSegments geometry={geometry}>
      <lineBasicMaterial color="#f1f1ef" transparent opacity={0.12} toneMapped={false} />
    </lineSegments>
  );
}

/**
 * The flat image plane behind the relief: the camera frame's outline at depth 0 and a faint grid
 * past it, so the relief reads as standing out of the picture.
 */
export function FramePlane() {
  const [outline, grid] = useMemo(() => {
    const x0 = -W / 2;
    const y0 = -H / 2;
    const o = new THREE.BufferGeometry();
    o.setAttribute(
      "position",
      new THREE.Float32BufferAttribute([x0, y0, 0, -x0, y0, 0, -x0, y0, 0, -x0, -y0, 0, -x0, -y0, 0, x0, -y0, 0, x0, -y0, 0, x0, y0, 0], 3),
    );
    const pts: number[] = [];
    const step = 0.2;
    const gx = W * 0.75;
    const gy = H * 0.85;
    for (let x = -gx; x <= gx + 1e-6; x += step) pts.push(x, -gy, -0.04, x, gy, -0.04);
    for (let y = -gy; y <= gy + 1e-6; y += step) pts.push(-gx, y, -0.04, gx, y, -0.04);
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
    return [o, g];
  }, []);
  useEffect(
    () => () => {
      outline.dispose();
      grid.dispose();
    },
    [outline, grid],
  );
  return (
    <>
      <lineSegments geometry={grid}>
        <lineBasicMaterial color="#f1f1ef" transparent opacity={0.05} toneMapped={false} />
      </lineSegments>
      <lineSegments geometry={outline}>
        <lineBasicMaterial color="#f1f1ef" transparent opacity={0.3} toneMapped={false} />
      </lineSegments>
    </>
  );
}
