"use client";

import { Line, OrbitControls } from "@react-three/drei";
import { Canvas, useFrame } from "@react-three/fiber";
import { useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from "react";
import * as THREE from "three";

import { usePrefersReducedMotion } from "@/components/alerts/use-reduced-motion";
import type { CvZone } from "@/lib/cv-map";
import { boxLoop, depthAt, type DepthRelief } from "@/lib/depth-relief";
import { cn } from "@/lib/utils";

import { at, FramePlane, ScanMesh, Surface, Z } from "./depth-relief-scene";

const RESYNC_S = 0.25;

const STAGE: Record<CvZone["stage"], { color: string; width: number; opacity: number; dashed: boolean; tag: string }> = {
  marked: { color: "#f1f1ef", width: 1, opacity: 0.5, dashed: true, tag: "text-fg/70" },
  flagged: { color: "#ffb340", width: 1.6, opacity: 0.95, dashed: false, tag: "text-warning" },
  confirmed: { color: "#ff453a", width: 2.4, opacity: 1, dashed: false, tag: "text-danger" },
};

/** One marked area, its outline following the surface. */
function ZoneOutline({ relief, zone }: { relief: DepthRelief; zone: CvZone }) {
  const s = STAGE[zone.stage];
  const points = useMemo(() => {
    const loop = boxLoop(relief, zone.box, 24).map(([u, v, d]) => at(u, v, d, 0.02));
    return [...loop, loop[0]];
  }, [relief, zone.box]);
  return (
    <Line
      points={points}
      color={s.color}
      lineWidth={s.width}
      transparent
      opacity={s.opacity}
      dashed={s.dashed}
      dashSize={0.04}
      gapSize={0.03}
      depthTest={false}
      renderOrder={zone.stage === "confirmed" ? 3 : zone.stage === "flagged" ? 2 : 1}
    />
  );
}

/** A zone's label anchor: its box's top-left corner on the surface, in the relief's local space. */
const anchorOf = (relief: DepthRelief, zone: CvZone) => at(zone.box[0], zone.box[1], depthAt(relief, zone.box[0], zone.box[1]), 0.02);

/**
 * Moves the plain DOM labels over the canvas each frame by projecting their anchors through the
 * camera (drei's Html would mount a React root per label, which React 19 cannot tear down while
 * the wall re-renders on a camera switch).
 */
function LabelProjector({ anchors, els }: { anchors: [string, [number, number, number]][]; els: RefObject<Map<string, HTMLSpanElement>> }) {
  const local = useRef<THREE.Group>(null);
  const v = useMemo(() => new THREE.Vector3(), []);
  useFrame(({ camera, size }) => {
    const g = local.current;
    if (!g) return;
    g.updateWorldMatrix(true, false);
    for (const [id, p] of anchors) {
      const el = els.current.get(id);
      if (!el) continue;
      v.set(p[0], p[1], p[2]).applyMatrix4(g.matrixWorld).project(camera);
      el.style.transform = `translate(${((v.x + 1) / 2) * size.width}px, ${((1 - v.y) / 2) * size.height}px) translateY(-100%)`;
      el.style.opacity = v.z < 1 ? "1" : "0";
    }
  });
  return <group ref={local} />;
}

/** Slow side-to-side sway of the whole scene; holds while the viewer drags, off under reduced motion. */
function Sway({ still, holding, children }: { still: boolean; holding: RefObject<number>; children: ReactNode }) {
  const group = useRef<THREE.Group>(null);
  const phase = useRef(0);
  useFrame((_, dt) => {
    const g = group.current;
    if (!g) return;
    if (!still && performance.now() > holding.current) phase.current += Math.min(dt, 0.1);
    const p = phase.current;
    g.rotation.y = still ? 0.3 : 0.38 * Math.sin(p * 0.24);
    g.rotation.x = 0.28 + (still ? 0 : 0.06 * Math.sin(p * 0.17));
  });
  return (
    <group ref={group}>
      {/* pivot halfway into the relief so near and far parts swing about its middle */}
      <group position={[0, 0, -Z / 2]}>{children}</group>
    </group>
  );
}

/**
 * A muted, looping, CORS-clean copy of the clip for the texture (a WebGL texture cannot sample the
 * tile's own cross-origin element), kept on the tile's clock. Null until it has a frame, or if it
 * fails, in which case the surface stays shaded by depth.
 */
function useReliefVideo(src: string, clipId: string): HTMLVideoElement | null {
  const [ready, setReady] = useState<{ src: string; el: HTMLVideoElement } | null>(null);
  useEffect(() => {
    const v = document.createElement("video");
    v.crossOrigin = "anonymous";
    v.muted = true;
    v.loop = true;
    v.playsInline = true;
    v.preload = "auto";
    v.src = src;
    let live = true;
    let raf = 0;
    let tile: HTMLVideoElement | null = null;
    const sync = () => {
      if (!tile?.isConnected) {
        tile = document.querySelector<HTMLVideoElement>(`[data-testid="cctv-tile"][data-clip="${CSS.escape(clipId)}"] video`);
      }
      if (tile && tile.readyState >= 2 && v.readyState >= 2 && Math.abs(v.currentTime - tile.currentTime) > RESYNC_S) {
        v.currentTime = tile.currentTime;
      }
      raf = requestAnimationFrame(sync);
    };
    v.addEventListener("loadeddata", () => live && setReady({ src, el: v }), { once: true });
    v.play().catch(() => {});
    raf = requestAnimationFrame(sync);
    return () => {
      live = false;
      cancelAnimationFrame(raf);
      v.pause();
      v.removeAttribute("src");
      v.load();
    };
  }, [src, clipId]);
  return ready && ready.src === src ? ready.el : null;
}

/**
 * 3D view of one camera: the clip's relative depth (one real frame through Depth Anything V2 Small,
 * precomputed by scripts/hazards/depth_relief.py; display only, never part of a review) as a
 * surface carrying the clip's video, with every CV-marked area drawn on it in its stage colour and
 * a contour sweeping through the real depth values. Drag to orbit.
 */
export function DepthReliefView({
  clipId,
  videoSrc,
  relief,
  zones,
}: {
  clipId: string;
  videoSrc: string;
  relief: DepthRelief;
  zones: CvZone[];
}) {
  const still = usePrefersReducedMotion();
  const video = useReliefVideo(videoSrc, clipId);
  const holding = useRef(0);
  const labelEls = useRef(new Map<string, HTMLSpanElement>());
  // confirmed drawn last so it sits on top
  const order = useMemo(() => [...zones].sort((a, b) => rank(a.stage) - rank(b.stage) || a.number - b.number), [zones]);
  // only areas Qwen flagged or confirmed get a label; the rest stay plain outlines
  const labelled = useMemo(() => order.filter((z) => z.stage !== "marked"), [order]);
  const anchors = useMemo(() => labelled.map((z): [string, [number, number, number]] => [z.id, anchorOf(relief, z)]), [labelled, relief]);

  return (
    <div
      className="relative aspect-video w-full cursor-grab overflow-hidden border border-line bg-[#030303] active:cursor-grabbing"
      data-testid="plan-relief"
      data-texture={video ? "video" : "depth"}
      data-zones={zones.length}
    >
      <div className="absolute inset-0">
        <Canvas dpr={[1, 2]} camera={{ position: [0, 0, 4.7], fov: 32 }} gl={{ antialias: true, alpha: true, powerPreference: "high-performance" }}>
          <Sway still={still} holding={holding}>
            <FramePlane />
            <Surface relief={relief} video={video} still={still} />
            <ScanMesh relief={relief} />
            {order.map((z) => (
              <ZoneOutline key={z.id} relief={relief} zone={z} />
            ))}
            <LabelProjector anchors={anchors} els={labelEls} />
          </Sway>
          <OrbitControls
            enableZoom={false}
            enablePan={false}
            enableDamping
            rotateSpeed={0.55}
            minAzimuthAngle={-0.55}
            maxAzimuthAngle={0.55}
            minPolarAngle={Math.PI / 2 - 0.5}
            maxPolarAngle={Math.PI / 2 + 0.25}
            onStart={() => {
              holding.current = Number.POSITIVE_INFINITY;
            }}
            onEnd={() => {
              holding.current = performance.now() + 2500;
            }}
          />
        </Canvas>
      </div>
      {labelled.map((z) => (
        <span
          key={z.id}
          ref={(el) => {
            if (el) labelEls.current.set(z.id, el);
            else labelEls.current.delete(z.id);
          }}
          data-testid="relief-zone-label"
          className={cn(
            "pointer-events-none absolute top-0 left-0 bg-bg/80 px-[3px] text-[8px] leading-[11px] font-bold tracking-[0.08em] whitespace-nowrap opacity-0",
            STAGE[z.stage].tag,
          )}
        >
          {z.id}
        </span>
      ))}
      <span className="micro pointer-events-none absolute top-0.5 left-1 text-fg/55">
        RELATIVE DEPTH · FRAME {relief.frame.index}
        {relief.frame.of ? `/${relief.frame.of}` : ""}
      </span>
      <span className="micro pointer-events-none absolute top-0.5 right-1 text-fg/40">DRAG TO ORBIT</span>
      <span className="micro pointer-events-none absolute bottom-0.5 left-1 text-fg/45" data-testid="relief-source">
        DEPTH ANYTHING V2 S · PRECOMPUTED · NOT SENT TO QWEN
      </span>
    </div>
  );
}

const rank = (s: CvZone["stage"]) => (s === "marked" ? 0 : s === "flagged" ? 1 : 2);
