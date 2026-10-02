# Component provenance (apps/web)

Each component in `apps/web/src/components` that was copied from outside the repo is listed here with its origin and license. All code is vendored into the repo, and the browser never fetches anything from 21st.dev, a CDN or Google Fonts (see "Offline check").

## 21st.dev access

21st.dev was unreachable in practice. Every registry URL tried with `pnpm dlx shadcn@latest add "https://21st.dev/r/<author>/<component>"` returned HTTP 403 `authentication_required`, and the Magic MCP server is unauthenticated in this environment. Two consequences:

- Where a 21st.dev listing re-publishes an open-source registry, the source was pulled from that author's public registry instead. These are the Magic UI components below; on 21st.dev they are listed under `@dillionverma`.
- Where no public source exists, an equivalent was built by hand. This covers the Elixr spiral hero, whose source is private, and the HUD/targeting visuals.

## Copied components

| Component | File | Origin | License | Normalization |
|---|---|---|---|---|
| Flickering Grid | `src/components/ui/flickering-grid.tsx` | Magic UI, listed on 21st.dev at `/@dillionverma/components/flickering-grid`; source from `https://magicui.design/r/flickering-grid.json` | MIT, (c) Magic UI | See below |
| Number Ticker | `src/components/ui/number-ticker.tsx` | Magic UI, listed on 21st.dev at `/@dillionverma/components/number-ticker`; source from `https://magicui.design/r/number-ticker.json` | MIT, (c) Magic UI | See below |
| Button | `src/components/ui/button.tsx` | shadcn/ui `button`, base-nova style (`@base-ui/react` primitive), added with `shadcn` 4.21.1 | MIT | Restyled to the HUD: square, 1px outline, tracked uppercase. Variants `default` (outline), `solid`, `ghost`, `danger` |

Flickering Grid normalization:
- monochrome `--fg` default color
- 20 fps cap
- one static frame under `prefers-reduced-motion`
- `className` merge fix

Number Ticker normalization:
- `text-fg`
- re-animates when `value` changes
- near-critical spring (damping 34 / stiffness 260) instead of upstream 60 / 100. Upstream takes about 3 s to settle and was caught at 0.71 for a 0.74 value.
- writes the value directly under reduced motion

Each copied file carries its origin in a header comment.

## Built by hand (no usable 21st source)

| Component | File | Replaces 21st plan item |
|---|---|---|
| Intersection wireframe (landing) | `src/components/landing/intersection-wireframe.tsx` | `elixr` spiral/geometric hero (private source) |
| Blind-zone plan | `src/components/ops/blind-zone-plan.tsx` + `src/lib/geometry.ts` | animated HUD targeting |
| Agent trace | `src/components/ops/trace-panel.tsx` | agent trace / streaming execution |
| Stack health, barcode, frame counter, panel frame | `src/components/ops/stack-health-panel.tsx`, `src/components/hud/*` | system monitor / telemetry blocks |

The blind-zone plan's FOV wedges, blind-area mask, rays and reticles are plain SVG. Labels are placed by a deterministic collision-avoiding placer (`placeLabels` in `src/lib/geometry.ts`), with a leader line when a marker sits inside a reticle.

## Runtime dependencies

| Package | Version | License | Use |
|---|---|---|---|
| `motion` | 13.5.0 | MIT | the single animation runtime (`MotionConfig reducedMotion="user"`) |
| `@base-ui/react` | 1.8.0 | MIT | button primitive |
| `class-variance-authority` | 0.7.1 | Apache-2.0 | button variants |
| `cn` | 0.4.0 | MIT | class merge (shadcn) |
| `tw-animate-css` | 1.4.0 | MIT | shadcn animation utilities |
| `@fontsource-variable/jetbrains-mono` | 5.3.0 | OFL-1.1 | self-hosted variable font via `next/font/local` (latin, normal + italic woff2) |

`clsx`, `tailwind-merge` and `lucide-react` were added by `shadcn init` but nothing imported them. They were removed.

## Offline check (production build)

- `.next/**` contains no `fonts.googleapis`, `fonts.gstatic` or CDN host.
- Two woff2 files are emitted under `.next/static`.
- Every http(s) string in the client bundle is inert:
  - the configured API base `http://127.0.0.1:8080`
  - the SVG namespace (w3.org)
  - error-message doc links (nextjs.org, react.dev, base-ui.com)
  - a core-js license URL
  - URL-parsing placeholders (`https://a`, `https://x`, `http://n`)
- Playwright recorded 0 requests leaving `127.0.0.1:3000` across all 13 captures (`design/screenshots/report.json`).
