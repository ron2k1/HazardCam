"use client";

import { useState } from "react";

import { mediaUrl, type HazardImage } from "@/lib/hazards";
import { cn } from "@/lib/utils";

export interface ThumbProps {
  image: HazardImage;
  onClick: () => void;
  /** Extra caption line (technical view: evidence id, kind, area). */
  detail?: string;
  className?: string;
}

/** A picture the AI was shown, as a button that seeks the video to its moment. */
export function Thumb({ image, onClick, detail, className }: ThumbProps) {
  const [broken, setBroken] = useState(false);
  const src = mediaUrl(image.image_url);
  const label = `${image.kind_label} at ${image.time_label}`;
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={`${label}. Go to this moment in the video`}
      className={cn("group flex min-w-0 flex-col border border-line bg-bg text-left transition-colors hover:border-fg/70", className)}
      data-testid="picture"
    >
      <span className="relative block aspect-[16/10] w-full overflow-hidden bg-black">
        {src && !broken ? (
          // Local API / public media; next/image's optimizer would only re-fetch it server side.
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={src}
            alt={label}
            loading="lazy"
            decoding="async"
            onError={() => setBroken(true)}
            className="absolute inset-0 h-full w-full object-contain"
          />
        ) : (
          <span className="dot-field absolute inset-0 flex items-center justify-center text-[11px] text-fg/50">No picture</span>
        )}
      </span>
      <span className="flex flex-wrap items-center justify-between gap-x-2 border-t border-line px-1.5 py-1 text-[12px] leading-4 text-fg/85">
        <span className="whitespace-nowrap">{image.kind_label}</span>
        <span className="whitespace-nowrap text-fg/60 tabular-nums">{image.time_label}</span>
      </span>
      {detail ? <span className="truncate border-t border-line px-1.5 py-0.5 text-[10px] leading-4 tracking-[0.08em] text-muted uppercase">{detail}</span> : null}
    </button>
  );
}

export interface PictureGridProps {
  images: readonly HazardImage[];
  onPicture: (image: HazardImage) => void;
  /** Per-image technical caption (same order as images). */
  details?: readonly (string | undefined)[];
  className?: string;
}

/** Every picture sent to the AI, in the order it was sent. */
export function PictureGrid({ images, onPicture, details, className }: PictureGridProps) {
  return (
    <ol
      className={cn("grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-6 2xl:grid-cols-7", className)}
      data-testid="picture-grid"
    >
      {images.map((im, i) => (
        <li key={`${im.image_url}-${i}`} className="min-w-0">
          <Thumb image={im} onClick={() => onPicture(im)} detail={details?.[i]} className="h-full w-full" />
        </li>
      ))}
    </ol>
  );
}
