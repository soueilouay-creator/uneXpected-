# uneXpected Phone Workspace — Design Specification

**Status:** Approved direction; implementation in progress
**Date:** 2026-10-31
**Target:** Existing installable phone PWA served at `/mobile/`

## Product goal

Turn the phone companion into a conversation-first AI workspace. Users can choose ChatGPT, Claude, or OpenRouter for each new message in the same conversation, see exactly which provider/model answered, and move between workspace areas through a left-side navigation drawer.

## Visual direction

- **Canvas:** graphite near-black `#0B1017`; use the existing dark product identity rather than introduce a new theme.
- **Surfaces:** raised blue-slate `#121B27` / `#182434`; separate areas with subtle borders, not a grid of decorative cards.
- **Text:** near-white `#EDF2F7`; secondary `#9AA8B9`; tertiary `#748398`.
- **Brand accent:** restrained soft violet `#A99AFF` inherited from the current uneXpected identity; reserve it for primary actions, focus, and selected navigation.
- **Provider accents:** distinct, low-saturation labels for ChatGPT, Claude, and OpenRouter; provider colors identify provenance, not decorative surfaces.
- **Typography:** system/Inter-style sans, compact utility labels, strong 24–30px view titles, readable 14–15px conversation text, 1.55–1.65 body leading.
- **Shape:** 10–14px interactive controls, 16px workspace panels; avoid enclosing every paragraph in a card.
- **Motion:** short drawer and state transitions; obey `prefers-reduced-motion`.

## Layout

### Desktop / wide viewport

```
┌───────────────┬────────────────────────────────────────────────────┐
│ Brand         │ View title                         Gateway status  │
│ New chat      ├────────────────────────────────────────────────────┤
│               │ Conversation / workspace content                   │
│ Home          │                                                    │
│ Chat          │                                                    │
│ Projects      │                                                    │
│ Memory        │                                                    │
│ Agent profiles│                                                    │
│ Settings      │                                                    │
│               ├────────────────────────────────────────────────────┤
│ Recent chats  │ Model selector · composer                          │
└───────────────┴────────────────────────────────────────────────────┘
```

### Phone viewport

```
┌────────────────────────────────────┐
│ Menu   uneXpected      Connection  │
├────────────────────────────────────┤
│ Conversation title   Model route   │
│                                    │
│ Messages with provider provenance  │
│                                    │
│                                    │
├────────────────────────────────────┤
│ ChatGPT · Claude · OpenRouter      │
│ Message composer             Send  │
└────────────────────────────────────┘
  └─ Left drawer overlays content with
     backdrop; main view remains focused.
```

The sidebar is persistent on wider screens and becomes a keyboard-accessible slide-in drawer below 760px. The conversation stream owns remaining height; composer stays anchored at the bottom while respecting safe-area insets and the on-screen keyboard. No bottom tab bar.

## Conversation behavior

- Visible choices: ChatGPT, Claude, OpenRouter, Compare ChatGPT + Claude, and Local only.
- The selected route applies to the next message only. Existing messages and their provider provenance never change.
- Direct OpenRouter sends use `mode: "openrouter"` on `POST /orchestrate`.
- Direct OpenRouter success is shown as an OpenRouter response, never synthesis.
- When ChatGPT, Claude, or Compare mode has no usable primary response, the backend may attempt one OpenRouter fallback. A successful primary response prevents fallback.
- Every assistant turn preserves provider, status, configured/requested route, actual returned model, latency, error, and fallback provenance.
- Compare mode continues to show separate ChatGPT and Claude results and the synthesis result when returned.
- No simulated answer is shown when a provider request fails.

## Preserved product behavior

Keep the existing IndexedDB database name, version, stores, and record structure so conversations, projects, memories, improvements, and settings remain readable. Keep local workspace commands, agent/skill profile browsing, backup export/import, speech recognition/synthesis, opt-in context sharing, persistent-storage request, and PWA install/offline shell.

The gateway access token remains in JavaScript memory only. It must not be stored in IndexedDB, localStorage, sessionStorage, logs, or backups. Provider API keys remain on the server.

## Source and delivery approach

Track the new phone surface in `mobile-release/`; copy it over the historical archived PWA source during CI restore and the Docker build. This avoids editing the compressed legacy asset archive and makes the exact deployed mobile source reviewable.

## Acceptance checks

1. Direct ChatGPT, Claude, and OpenRouter routes send the selected route.
2. Direct OpenRouter sends exactly one OpenRouter request and do not trigger a second fallback attempt.
3. Fallback remains limited to primary failure and retains result provenance.
4. Mid-conversation model changes apply only to the next message.
5. Assistant message metadata shows provider, actual model, latency, and fallback status where present.
6. Sidebar opens/closes with button, backdrop, Escape, and navigation selection; wide viewports keep it persistent.
7. Existing local records and workspace tools remain available.
8. Access token remains memory-only; no browser provider secret is introduced.
9. Existing phone PWA, mobile route, auth and gateway tests pass.
