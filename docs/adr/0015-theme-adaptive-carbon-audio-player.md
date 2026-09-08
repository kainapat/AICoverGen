# Theme-Adaptive Carbon Audio Player Card

We align the custom HTML5 Audio Player Card with the WebUI's IBM Carbon theme (`ibm-software/gradio-carbon-theme`) using dynamic Gradio CSS variables, IBM Carbon Blue accents (`#0f62fe`), and modern rounded geometry while preserving all core playback and isolation features.

**Context & Problem:**
Previously, ADR 0007 established a custom HTML5 Audio Player to overcome Chromium's native Shadow DOM auto-hiding of the timeline scrubber thumb and to protect against IDM auto-downloads.
However, that controller hardcoded a vivid Cyberpunk palette: neon cyan (`#00f0ff`), neon green (`#00ffa5`), and intense cyan glow shadows (`rgba(0, 240, 255, 0.35)`).
Because AICoverGen's WebUI runs under `ibm-software/gradio-carbon-theme` (an IBM Carbon design system featuring deep slate/gray surfaces, crisp 1px borders, and IBM Blue `#0f62fe` primary buttons), the glowing neon player looked incongruous and visually discordant with the rest of the application.

**Considered Options:**
- Revert to Chromium native player — rejected: Re-introduces Chromium's hidden scrubber thumb, lack of contrast, and IDM interception vulnerabilities.
- Static hardcoded Carbon colors — rejected: Does not respond dynamically if Gradio's theme tokens or dark/light modes change.
- Dynamic Gradio CSS Variables with Carbon Fallbacks — accepted:
  1. Leverage Gradio theme custom properties: `var(--block-background-fill, #161616)`, `var(--border-color-primary, #393939)`, `var(--background-fill-secondary, #262626)`, and `var(--primary-600, #0f62fe)`.
  2. Style Play/Pause button and Download button in Carbon Blue (`#0f62fe` / `var(--button-primary-background-fill)`) matching the primary `[Generate]` button.
  3. Keep the timeline scrubber thumb 100% visible at all times with real-time linear-gradient track progression in Carbon Blue.
  4. Display status metadata using a refined Carbon Pill Badge (`rgba(15, 98, 254, 0.12)` background, `#4589ff` text).
  5. Update the empty placeholder state with matching Carbon dashed borders and typography.

**Consequences:**
- The Audio Player Card seamlessly integrates with the WebUI's visual theme across all components and accordions.
- Retains 100% IDM immunity, zero auto-downloads, full Thai Unicode filename handling, and permanent scrubber visibility.
- Modern Carbon Rounded geometry (8px cards, 6px buttons) creates a professional, cohesive studio interface.
