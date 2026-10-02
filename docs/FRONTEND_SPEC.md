# Frontend Spec

## Stack

- Next.js + TypeScript
- Tailwind
- shadcn primitives where useful
- 21st.dev copied-source components
- Motion/Framer Motion; keep GSAP only when required by imported component

## Pages

### `/`
Landing page matching the supplied monochrome scientific/architectural screenshot. Replace the Vitruvian figure with a wireframe urban intersection / camera FOV geometry. Primary action: `ENTER SYSTEM`.

### `/ops`
Main judged screen:
- 3 visible input cameras
- 1 withheld ground-truth camera (clearly labeled `JUDGE GROUND TRUTH — NOT MODEL INPUT`)
- agent trace
- evidence timeline
- blind-zone visualization
- hypothesis panel
- local stack health

## Theme tokens

```css
:root {
  --bg: #050505;
  --panel: #090909;
  --fg: #f1f1ef;
  --muted: #777773;
  --dim: #3e3e3b;
  --line: rgba(255,255,255,.12);
  --line-strong: rgba(255,255,255,.28);
  --danger: #ff453a;
  --radius: 0px;
}
```

Use square borders, telemetry labels, coordinates, frame IDs, and subtle grid/noise. Do not create a rounded-card SaaS dashboard.

## 21st.dev

Reference components:
- elixr: https://21st.dev/@ibssibss7/components/elixr
- animated HUD targeting UI: search 21st for `animated hud targeting`

Current CLI setup reference:
```bash
npm i -g @21st-dev/cli
21st login
npx @21st-dev/cli install-skill
21st search "hud targeting"
21st search "agent trace"
21st search "system monitor"
```

For Claude Code integration, current 21st docs also expose:
```bash
npx @21st-dev/cli init --client claude --write
```

Install/copy source before the final offline demo; do not fetch UI components at runtime.

## Motion

Animations should communicate system state, not distract:
- subtle rotating FOV / target geometry
- scanning line only while analyzing
- evidence nodes illuminate as SSE events arrive
- hypothesis resolves from `UNKNOWN` to a bounded result
- respect `prefers-reduced-motion`
