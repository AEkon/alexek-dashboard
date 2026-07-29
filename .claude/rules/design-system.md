---
name: design-system
description: Design system, color rules, and CSS patterns for the dashboard frontend
metadata:
  type: reference
---

## Color System

Pick exactly 4 colors. Assign them roles. Use CSS custom properties so theming is a one-line change.

```css
:root {
  --color-primary: #722F37;    /* navigation, headers, emphasis */
  --color-accent: #2A9D8F;     /* interactive elements, links, success states */
  --color-highlight: #C4813D;  /* warnings, fragile connections */
  --color-bg: #FAF0E6;         /* page background */
}
```

The specific colors don't matter as much as having clear, non-overlapping roles. Avoid the AI color palette: cyan-on-dark, purple-to-blue gradients, neon accents on dark backgrounds.

## Design Rules

| Rule | Detail |
|------|--------|
| Information density over whitespace | If you have to scroll to understand state, you won't check the dashboard |
| Every chart element links to detail | Click-through from everything — stats, chart bars, table rows |
| Every table column must be sortable | Click header to toggle asc/desc. Missing sort = bug. |
| Cap table rows at 5–10 | "Show more" toggle below. Don't render 500 rows on load. |
| Per-card refresh buttons | Every section header gets a refresh icon |
| No fake or interpolated data | If a scraper failed, show "no data" or last-known value |
| Filter pills, not dropdowns | Clickable, highlighted when active. Filters are visible state. |
| Collapsible sections | Expand/collapse with a chevron. Saves vertical space. |
| Labels on everything | Don't hide context behind tooltips. You'll forget what unlabeled buttons do. |

## CSS Anti-Patterns (The AI Slop Test)

These are patterns AI assistants produce by default. Push back on all of them:

| Don't | Do instead |
|-------|-----------|
| `style={{}}` inline styles | CSS classes. Always. Inline styles bypass theming. |
| Colored left-border "pill" indicators | Subtle background tint `rgba(color, 0.08)` + border-radius |
| Cards inside cards | Flatten the hierarchy. Not everything needs a container. |
| Identical card grids (icon + heading + text × N) | Vary the layout. Tables, lists, inline stats — mix formats. |
| Hero metric layout (big number, small label, gradient) | Inline the number in context where it's actionable |
| Glassmorphism (blur, glass cards, glow borders) | Solid backgrounds. Decorative blur is never purposeful. |
| Gradient text on headings or metrics | Solid color. Gradients are decoration masquerading as emphasis. |
| Rounded rectangles with generic drop shadows | Sharp or very subtle radius. Drop shadows should be barely visible. |
| Pure black `#000` or pure white `#fff` | Tint toward your palette. Pure B&W never appears in nature. |
| Bounce/elastic easing | `ease-out-quart` or `ease-out-expo`. Real objects decelerate smoothly. |
| Modals for everything | Inline expand, slide panels, or navigate. Modals are lazy. |
| Gray text on colored backgrounds | Use a shade of the background color — gray looks washed out |

**The test:** If you showed this interface to someone and said "AI made this," would they believe you immediately? If yes, fix it.

## Typography

- Pick a distinctive display font + a clean body font. Pair, don't match.
- Use a modular type scale with `clamp()` for fluid sizing.
- Vary weights and sizes to create clear hierarchy.
- Don't use Inter, Roboto, Arial, Open Sans, or system defaults. These scream "didn't choose a font."
- Don't use monospace as shorthand for "technical."
- Don't put large rounded-corner icons above every heading — it's templated.

## Spacing

- Create rhythm through *varied* spacing. Tight groupings, generous separations. Not the same padding everywhere.
- Use `clamp()` for fluid spacing that breathes on larger screens.
- Don't center everything. Left-aligned text with asymmetric layouts feels more intentional.