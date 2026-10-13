# Design Philosophy — Blood Banking Antibody ID Shell

## Source of inspiration
This UI is modeled on **Skiptocyte: Laboratory Tools** (skiptocyte.com), a
clinical laboratory tool built with a clean, card-based system. We took that
layout language and re-skinned it for blood banking: red + white,
quant/military-medical, with a dark sidebar for navigation and a light
content area for results.

## Core principles
1. **Clean and minimal** — no decorative clutter; every element earns its place.
2. **Quant/military-medical palette** — red (priority, alerts, active) + white
   (clean content) is the theme. High contrast, readable at a glance, no
   pastel menu fatigue.
3. **Systematic spacing** — 4px base grid (0.25rem), consistent 8px scales,
   identical component measuring across panels and results.
4. **Type-driven hierarchy** — IBM Plex Sans Variable (serif != medical; sans
   = clinical), strict type scale, generous line-height.
5. **Dark sidebar = system** — the nav stays dark and stable; content area is
   light so results pop.
6. **Status color discipline** — red for positive/alert/high, amber for
   caution/weak, green for confident/negative; never mixed.
7. **Clinical states, explicit** — confident vs. unconfirmed, auto-control
   positive, inconclusive = all called out, never implied.

## Component language
- **Cards** — rounded (radius 0.65rem), subtle white drop shadow, thin
  border (color 40%).
- **Tables** — zebra rows, hover state, active row accent.
- **Badges** — small, bold, color-coded by status.
- **Buttons** — primary red, secondary outline, destructive for clear removal.

## What this UI IS / IS NOT
- **IS** a front-end dashboard that orchestrates the abid Python engine.
- **IS** responsive, Windows-11-adjacent in chrome (maximized title area,
  taskbar-friendly).
- **IS NOT** a physician-facing diagnostic. All results carry the same
  disclaimer: "For technologist review; not for clinical decision-making."

## Accessibility
- 4.5:1 minimum contrast on text.
- Focus rings from the side, visible.
- Keyboard navigable.
- Support Windows high contrast, no loss of function.

## Status: plain code in the browser
The frontend is hand-written static HTML/CSS/JS in `app/`. No framework,
no build pipeline — one HTML file + one CSS file + one JS file. The engine
`abid/` is pure Python with a CLI; the UI talks to it via `subprocess` (or
a local HTTP bridge). We keep it dependency-free on the frontend so the
installer stays small and portable.
