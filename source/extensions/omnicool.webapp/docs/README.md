# omnicool.webapp — Omniverse Web Extension

A self-contained Omniverse Kit extension that serves a React-based web UI, a USD editor page, and a live prim-inspect HUD — all bridged to the running USD stage via a local WebSocket server.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Quick Start](#quick-start)
- [Configuration (`window.OMNICOOL_CONFIG`)](#configuration-windowomnicool_config)
- [Prim-Inspect HUD](#prim-inspect-hud)
  - [Gesture](#gesture)
  - [Live Attribute Chart](#live-attribute-chart)
- [USD Editor Page](#usd-editor-page)
- [WebSocket API](#websocket-api)
- [Flownex Bridge](#flownex-bridge)
- [Extension Settings](#extension-settings)
- [Development Notes](#development-notes)

---

## Overview

`omnicool.webapp` starts two servers inside the running Kit process:

| Server | Default port | Purpose |
|---|---|---|
| HTTP | `8080` | Serves the React web app (`index.html`) and USD editor (`usd-editor.html`) |
| WebSocket | `8899` | Bi-directional USD command channel |

When you open `http://localhost:8080` you get the React application.  
When you open `http://localhost:8080/usd-editor.html` you get a standalone USD scene inspector.

Both pages share the same WebSocket bridge to the Kit process.

---

## Architecture

```
Browser (index.html / usd-editor.html)
        │  HTTP :8080     WebSocket :8899
        ▼                       ▼
  _StaticHandler         OmnicoolWebAppExt
  (Python HTTP)          ├─ _handle_ws_message()
                         ├─ USD helpers (_get_attr, _set_attr, _pick_prim_path …)
                         └─ Flownex metadata bridge (flownex_metadata.py)
```

---

## Quick Start

1. **Add the extension to your Kit `.toml`:**

   ```toml
   [dependencies]
   "omnicool.webapp" = {}
   ```

2. **Launch your Kit application.** The extension logs the listening URLs:

   ```
   [omnicool.webapp] HTTP  listening on http://0.0.0.0:8080
   [omnicool.webapp] WS    listening on ws://0.0.0.0:8899
   ```

3. **Open the web app** at `http://localhost:8080` in any modern browser.

---

## Configuration (`window.OMNICOOL_CONFIG`)

All user-adjustable settings live in a single `<script>` block at the **top of `index.html`**, before the React bundle loads. Edit this block to customise the app without touching any compiled code:

```js
window.OMNICOOL_CONFIG = {
  // USD attribute queried on long-press to identify a component
  trackedAttr: "flownex:componentName",

  // Fallback prim path shown in demo / offline mode (no Omniverse)
  stubPrimPath: "/World/DataCenter/Rack_A/Pump_01",

  // WebSocket endpoint of the Omniverse extension bridge
  wsUrl: "ws://127.0.0.1:8899",

  // Hold duration (ms) required to trigger prim-inspect
  holdMs: 1000,

  // Maximum USD attributes shown in the inspect HUD card
  maxAttrs: 10,

  // Polling interval (ms) for the live attribute chart
  plotIntervalMs: 2000,

  // Maximum number of data points kept per attribute in the chart
  plotMaxPoints: 60
};
```

> **Tip — changing the tracked attribute:** If your USD stage uses a different attribute to name components (e.g. `custom:label`), change `trackedAttr` here. This is the only place you need to edit.

---

## Prim-Inspect HUD

The prim-inspect HUD lets you click on any prim in the 3D viewport and instantly see its USD attributes in a floating panel — no need to open the USD editor.

### Gesture

1. **Hold `I`** — the cursor changes to a crosshair and a red bar appears at the bottom of the screen indicating inspect mode.
2. **Hold the mouse button for 1 second** over the area of interest — the bar turns purple while the hold is counted down.
3. **Release** — the extension sends a `usd.get_prim_info` request to pick the prim under the cursor and fetch its attributes.
4. A **HUD card** appears near the click showing:
   - The full USD prim path (highlighted in red)
   - A table of attribute names and current values
   - A button to open the prim in the full USD editor
5. **Dismiss** with `Esc` or by clicking anywhere outside the card.

### Live Attribute Chart

Any attribute row in the HUD card can be **clicked** to open a live time-series chart:

1. Inspect a prim (I-key gesture above).
2. **Click any attribute row** — the row highlights and a `▶` indicator appears.
3. A **floating chart panel** appears showing the attribute value plotted over time.
4. The chart **polls `usd.get_attr`** every `plotIntervalMs` milliseconds (default 2 s) and updates the SVG line graph automatically.
5. **Multiple attributes** from the same or different prims can be overlaid — each gets a distinct colour; the Y axis auto-scales.
6. **Remove a single line** by clicking its `×` legend entry.
7. **Close the chart** entirely with the `✕` button in the panel header.

The chart requires a live WebSocket connection to the Kit process; it does not work in offline/demo mode.

---

## USD Editor Page

Navigate to `http://localhost:8080/usd-editor.html` for a standalone USD scene inspector that provides:

- Prim tree browser (children of `/World`)
- Attribute viewer / editor (read + write USD attributes)
- Prim-info HUD (same I-key gesture as the main app)
- WebRTC viewport (optional, disabled by default — see [Extension Settings](#extension-settings))

---

## WebSocket API

All messages are UTF-8 JSON with the envelope:

```json
{ "id": "<string>", "type": "<namespace.action>", "payload": { ... } }
```

Responses:

```json
{ "id": "<same>", "ok": true,  "payload": { ... } }
{ "id": "<same>", "ok": false, "error": "<message>" }
```

### USD namespace

| Type | Payload | Response payload | Notes |
|---|---|---|---|
| `usd.pick` | `{x, y}` normalised | `{primPath}` | Raycasts viewport; falls back to selection |
| `usd.get_prim_info` | `{x, y, maxAttrs?}` | `{primPath, attrs:[{name,value}]}` | Combined pick + attr fetch (used by HUD) |
| `usd.list_children` | `{primPath?}` | `{children:[string]}` | Defaults to `/World` |
| `usd.prim_exists` | `{primPath}` | `{exists:bool}` | |
| `usd.get_attr` | `{primPath, attr}` | `{value}` | Returns `{value:null}` if attr missing |
| `usd.set_attr` | `{primPath, attr, value}` | `{set:true}` | |
| `usd.list_attrs` | `{primPath}` | `{attrs:[string]}` | |
| `usd.create_attr` | `{primPath, attr, typeName, value?}` | `{created:true}` | |
| `usd.delete_attr` | `{primPath, attr}` | `{}` | |

### Flownex namespace

See `flownex_metadata.py` for the full schema. Key types:

| Type | Purpose |
|---|---|
| `flownex.ensure_metadata` | Idempotently create controller metadata on a prim |
| `flownex.get_metadata` | Read full metadata object |
| `flownex.set_desired_property` | Write a desired-value entry |
| `flownex.set_observed_property` | Write an observed-value entry |
| `flownex.load_parameter_table_rows` | Bulk-load parameter definitions from a table |
| `flownex.sync_parameters` | Push desired values back to USD attributes |

---

## Flownex Bridge

`flownex_metadata.py` stores simulation controller state as USD `customData` on a chosen prim, keyed by `omnicool:flownexController`. The metadata schema contains:

```
desiredProperties   – values to write to Flownex
observedProperties  – values read back from Flownex
parameters          – UI parameter definitions (key, label, component, property, bounds)
commandQueue        – pending commands
ready               – connection/project status flags
intent              – simulation mode (steady / transient)
runtime             – last action / result / run state
cache               – optional response cache settings
```

Parameters are loaded from external CSV or JSON tables via `flownex.load_parameter_table_rows`, so the component names and property identifiers are **data-driven** — no code changes are needed when the Flownex model changes.

---

## Extension Settings

Configure in `config/extension.toml`:

| Setting | Default | Description |
|---|---|---|
| `httpPort` | `8080` | HTTP server port |
| `wsPort` | `8899` | WebSocket server port |
| `webrtcEnabled` | `false` | Enable aiortc WebRTC viewport streaming |
| `webrtcPort` | `8900` | WebRTC signaling port |

---

## Development Notes

- The compiled React bundle is at `data/webapp/static/js/main.eb06dcd7.js`.  
  It reads `window.OMNICOOL_CONFIG` at runtime, so most settings can be changed in `index.html` without rebuilding.
- The HTTP server is bound to an **absolute path** via `functools.partial` — changing the working directory has no effect on static file serving.
- WebSocket messages are processed on the Kit main thread; heavy operations should be deferred to a background task.
- Tests live in `omnicool/webapp/tests/`. Run with `./repo.sh test`.

