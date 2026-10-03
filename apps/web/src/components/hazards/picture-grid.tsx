"use client";

import { Fragment, useEffect, useRef, useState, type CSSProperties } from "react";

import { mediaUrl } from "@/lib/hazards";
import { cn } from "@/lib/utils";

import { groupByZone, isRawEvidence, type Pic } from "./derive";

/** Height of the burned-in "E### | t=… | kind | Z##" strip on every evidence picture. */
export const LABEL_STRIP_PX = 36;

function viewBoxSupported(): boolean {
  try {
    return typeof CSS !== "undefined" && CSS.supports("object-view-box", "inset(1px 0px 0px 0px)");
  } catch {
    return false;
  }
}

/** Crop the top `px` of a replaced element's natural content (object-view-box; cover as fallback). */
export function cropTopStyle(px: number, fit: "contain" | "cover" = "contain"): CSSProperties {
  if (px <= 0) return { objectFit: fit };
  if (viewBoxSupported()) return { objectFit: fit, objectViewBox: `inset(${px}px 0px 0px 0px)` } as CSSProperties;
  return { objectFit: "cover", objectPosition: "50% 100%" };
}

/**
 * A worker picture: the clean copy when the API has one; otherwise the labelled original with
 * its label strip cropped away, so no ids or numbers show in the worker view.
 */
export function CleanImage({
  pic,
  alt,
  fit = "contain",
  raw = false,
  className,
}: {
  pic: Pick<Pic, "src" | "raw">;
  alt: string;
  fit?: "contain" | "cover";
  /** Show the labelled original as it is (process page). */
  raw?: boolean;
  className?: string;
}) {
  const [useRaw, setUseRaw] = useState(false);
  const [broken, setBroken] = useState(false);
  const url = useRaw && pic.raw ? pic.raw : pic.src;
  const src = mediaUrl(url);
  const crop = !raw && isRawEvidence(url) ? LABEL_STRIP_PX : 0;
  if (!src || broken) {
    return <span className={cn("dot-field flex items-center justify-center text-[11px] text-fg/50", className)}>No picture</span>;
  }
  return (
    // Local API media; next/image's optimizer would only re-fetch it server side.
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={src}
      alt={alt}
      loading="lazy"
      decoding="async"
      onError={() => (!useRaw && pic.raw && pic.raw !== pic.src ? setUseRaw(true) : setBroken(true))}
      className={className}
      style={cropTopStyle(crop, fit)}
      data-cropped={crop > 0 || undefined}
    />
  );
}

export interface PicButtonProps {
  pic: Pic;
  onClick: () => void;
  size?: "sm" | "lg";
  /** Show the "Used for a hazard" mark. */
  markCited?: boolean;
  className?: string;
}

/** A picture the AI was shown, as a button. Caption: "Zone 3 · 0:04" plus the kind of picture. */
export function PicButton({ pic, onClick, size = "sm", markCited = false, className }: PicButtonProps) {
  // "Whole view · 0:06" already says what it is; only add the kind when it says more
  const kind = pic.kind_word && !pic.caption.toLowerCase().startsWith(pic.kind_word.toLowerCase()) ? pic.kind_word : "";
  const label = `${kind ? `${kind}, ` : ""}${pic.caption}`;
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={`${label}. Show this moment`}
      className={cn(
        "group flex min-w-0 flex-col border bg-bg text-left transition-colors hover:border-fg/70",
        pic.cited && markCited ? "border-warning/60" : "border-line",
        className,
      )}
      data-testid="picture"
      data-cited={pic.cited || undefined}
    >
      <span className={cn("relative block w-full overflow-hidden bg-black", size === "lg" ? "aspect-[4/3]" : "aspect-[16/10]")}>
        <CleanImage pic={pic} alt={label} className="absolute inset-0 h-full w-full" />
        {pic.cited && markCited ? (
          <span className="absolute top-1 left-1 bg-warning px-1 text-[10px] leading-[15px] font-bold tracking-[0.06em] text-bg uppercase">
            Used for a hazard
          </span>
        ) : null}
      </span>
      <span
        className={cn(
          "flex flex-1 flex-wrap items-center justify-between gap-x-2 border-t border-line px-1.5 py-1 leading-4",
          size === "lg" ? "text-[12px] text-fg" : "text-[12px] text-fg/85",
        )}
      >
        {/* wrap only between "Zone 2" and "· 0:00", never inside them; the kind drops below */}
        <span className="min-w-0 font-semibold">
          {pic.caption.split(" · ").map((part, i) => (
            <Fragment key={i}>
              {i ? " " : ""}
              <span className="whitespace-nowrap">{i ? `· ${part}` : part}</span>
            </Fragment>
          ))}
        </span>
        {kind ? <span className="min-w-0 truncate text-[11px] text-fg/55">{kind}</span> : null}
      </span>
    </button>
  );
}

/** "Pictures the AI looked at": every picture sent, grouped Whole view, Zone 1, Zone 2, ... */
export function PictureGallery({ pics, onPicture, className }: { pics: readonly Pic[]; onPicture: (p: Pic) => void; className?: string }) {
  const groups = groupByZone(pics);
  return (
    <div className={cn("flex flex-col gap-4", className)} data-testid="picture-gallery">
      {groups.map((g) => (
        <section key={g.name} aria-label={g.name} className="flex flex-col gap-1.5" data-testid="picture-group">
          <h4 className="flex items-baseline gap-2 text-[12px] font-bold tracking-[0.14em] text-fg uppercase">
            {g.name}
            <span className="text-[11px] font-normal tracking-normal text-fg/50 normal-case">
              {g.pics.length} picture{g.pics.length === 1 ? "" : "s"}
            </span>
          </h4>
          <ol className="grid grid-cols-2 gap-2 sm:grid-cols-3 2xl:grid-cols-4">
            {g.pics.map((p) => (
              <li key={p.key} className="min-w-0">
                <PicButton pic={p} onClick={() => onPicture(p)} markCited className="h-full w-full" />
              </li>
            ))}
          </ol>
        </section>
      ))}
    </div>
  );
}

/** An enlarged picture in a modal dialog (Esc or the button closes it). */
export function Lightbox({ pic, onClose }: { pic: Pic | null; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (pic && !d.open) d.showModal();
    if (!pic && d.open) d.close();
  }, [pic]);
  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      aria-label={pic ? pic.caption : "Picture"}
      className="m-auto max-h-[92dvh] w-[min(1100px,94vw)] border border-line-strong bg-bg p-0 text-fg backdrop:bg-black/80"
      data-testid="lightbox"
    >
      {pic ? (
        <figure className="m-0 flex flex-col">
          <div className="relative flex max-h-[80dvh] items-center justify-center bg-black">
            <CleanImage pic={pic} alt={pic.caption} className="max-h-[80dvh] w-full" />
          </div>
          <figcaption className="flex items-center justify-between gap-3 border-t border-line px-3 py-2">
            <span className="text-[15px] font-bold">
              {pic.caption}
              {pic.kind_word ? <span className="ml-2 text-[13px] font-normal text-fg/60">{pic.kind_word}</span> : null}
            </span>
            <button
              type="button"
              autoFocus
              onClick={onClose}
              className="h-9 border border-fg/80 px-3 text-[13px] hover:bg-fg hover:text-bg"
              data-testid="lightbox-close"
            >
              Close <span className="text-fg/50">(Esc)</span>
            </button>
          </figcaption>
        </figure>
      ) : null}
    </dialog>
  );
}
