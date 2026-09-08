# Custom Cyberpunk Audio Controller and Permanent Scrubber Visibility

We replace the native browser `<audio controls>` element with a fully custom, theme-integrated HTML5 Cyberpunk Audio Controller featuring permanent timeline scrubber thumb visibility, real-time elapsed gradient tracking, and dark-glass aesthetics.

**Context & Problem:**
In Chromium-based browsers (Google Chrome, Microsoft Edge, Brave, Opera), native `<audio controls>` encapsulates all media controls inside a closed Shadow DOM.
Chromium's user-agent stylesheet deliberately hides the timeline slider thumb (`::-webkit-media-controls-timeline::-webkit-slider-thumb`) and dims the track whenever the mouse cursor is not actively hovering over the player.
This resulted in a frustrating user experience: users listening to generated covers could not see where they were in the song without constantly hovering their mouse over the player. Furthermore, Chromium's default audio player renders an incongruous white pill background (`#f1f3f4`) that clashed with AICoverGen's dark Cyberpunk theme.

**Considered Options:**
- CSS overrides targeting browser vendor pseudo-elements (`audio::-webkit-media-controls-*`) — rejected: Modern Chromium strictly enforces Shadow DOM v1 boundaries, completely blocking external CSS rules from styling internal shadow elements.
- Overlay progress indicator bar on top of native player — rejected: Leaves the stark white native player in place, producing visual clutter and redundant disconnected timelines.
- Custom Cyberpunk HTML5 Audio Controller — accepted: Replaces the native controls with a custom dark-glass controller (`.cyber-controller-bar`) containing:
  1. A neon cyan circular Play/Pause button (`▶` / `⏸`).
  2. A crisp monospace time indicator (`0:00 / 2:32`).
  3. A custom range slider (`.cyber-seek-slider`) with a permanently visible, glowing cyan scrubber thumb (`::-webkit-slider-thumb`) and real-time linear-gradient fill.
  4. Volume button and volume slider for seamless audio adjustment.
  5. Backed by the existing in-memory Data URI (`data:audio/mpeg;base64,...`) and client-side download button.

**Consequences:**
- The playback position and scrubber thumb remain 100% visible at all times, completely eliminating the need to hover.
- Full theme harmony with neon cyan (`#00f0ff`), emerald green (`#00ffa5`), and dark glass background.
- Smooth click-to-seek and drag-to-seek functionality.
- Continues to provide 100% IDM immunity, zero unwanted auto-downloads, and flawless Thai Unicode filename preservation.
