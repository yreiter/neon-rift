# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Neon Rift is a zero-dependency browser game — a single HTML page with one JS file and one CSS file. No build step, no package manager, no framework. Open `index.html` directly in a browser to run it.

The README is in Hebrew; the UI text is also in Hebrew (`lang="he" dir="rtl"`).

## Running the Game

Serve locally with any static file server, for example:

```bash
python3 -m http.server 8080
# then open http://localhost:8080
```

Or open `index.html` directly in a browser (`file://` works fine since there are no module imports).

There is no build, no lint, and no test tooling configured.

## Architecture

All game logic lives in `game.js` (single file, ~430 lines). Key concepts:

- **State object** (`createState`): the single source of truth reset on each `startGame()` call. Holds player, enemies, cores, particles, stars, timers, score, combo, shield, and shake.
- **Game loop** (`loop`): driven by `requestAnimationFrame`. Caps `dt` at 32 ms to prevent physics tunnelling on tab-restore. Calls `update(dt)` then `draw()` each frame.
- **Input**: keyboard state tracked in a `Set<string>` (`keys`). Touch controls fire synthetic `pointerdown`/`pointerup` events that add/remove the same lowercase key strings, so `movePlayer` is input-agnostic.
- **Collision**: simple circle–circle distance checks (`distance(a, b) < a.r + b.r`). No spatial index — iterates all entities each frame.
- **Difficulty ramp**: enemy speed scales with `state.time`; spawn interval shrinks linearly from 1.15 s toward a 0.32 s floor.
- **Combo multiplier**: increments on core collection, decays continuously at 0.055/s, and resets to 1 on any hit.
- **Dash mechanic**: `state.dashTimer > 0` doubles player speed and reduces enemy collision damage from 20 → 4 shield points; costs 1 shield point to activate.
- **Screen shake**: `state.shake` is added as a random canvas translate on every draw frame and decays at 18/s.
- **Canvas DPI**: `resizeCanvas()` scales by `devicePixelRatio` and applies a matching `setTransform`; all game coordinates use CSS pixels via `canvas.getBoundingClientRect()` through `worldSize()`.

## CSS Conventions

- CSS custom properties defined on `:root` hold the colour palette (`--cyan`, `--rose`, `--gold`, `--lime`, `--panel`, `--line`, `--ink`, `--muted`). Prefer these over inline colour values.
- Responsive breakpoints: `≤720px` and `(hover: none and pointer: coarse)` both show touch controls and make the canvas fill the viewport. The `.panel` info bar is hidden below `720px` and below `620px` viewport height.
- Touch-control visibility is CSS-only (display toggled via media queries); JS never reads or sets it.
