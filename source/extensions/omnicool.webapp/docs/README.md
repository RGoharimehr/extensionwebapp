# Omnicool [omnicool.webapp]

A Kit extension that serves a React web-app UI and bridges it to the live USD
stage via WebSocket.

---

## Extension structure

```
omnicool.webapp/
├── config/
│   └── extension.toml          # Extension metadata; webRoot = "data/webapp"
│
├── data/
│   ├── webapp/                 # ★ COMPILED runtime web app — served by HTTP server
│   │   ├── index.html
│   │   ├── asset-manifest.json
│   │   ├── usd-editor.html
│   │   └── static/             # Minified JS + CSS bundles
│   ├── icon.png
│   └── preview.png
│
├── frontend_source/            # React source (development only — NOT used at runtime)
│   └── README.md               # Dev workflow: edit → build → copy to data/webapp/
│
├── docs/                       # Extension documentation
│
└── omnicool/webapp/            # Python extension package
    ├── extension.py            # Thin lifecycle wrapper (HTTP + WS startup/shutdown)
    ├── backend/
    │   ├── usd_helpers.py      # USD stage utilities
    │   ├── ws_handlers.py      # WebSocket message dispatcher (USD bridge, port 8899)
    │   ├── flownex_metadata.py # Flownex controller metadata helpers
    │   ├── flownex_attr_tools.py
    │   └── flownex_results.py
    ├── transport/
    │   ├── http_server.py      # Static file handler + websockets installer
    │   └── webrtc_server.py    # Optional aiortc WebRTC signaling server
    └── tests/
```

---

## Runtime vs source

| Path | Role | Used at runtime |
|---|---|---|
| `data/webapp/` | Compiled web assets; served at `http://127.0.0.1:3001` | **Yes** |
| `frontend_source/` | React source code and build config | **No** |
| `omnicool/webapp/` | Python backend logic | **Yes** |

The extension **never reads** from `frontend_source/` at runtime.
All UI changes must be built (`npm run build`) and the output copied to
`data/webapp/` before they take effect.

---

## WebSocket endpoints

| Port | Path | Protocol |
|---|---|---|
| 8899 | `ws://127.0.0.1:8899` | USD stage bridge (usd.*, flownex.*, flownex_tools.*) |

---

## Quick start

1. Enable the extension in Kit.
2. Open `http://127.0.0.1:3001` in a browser.
3. The web app connects automatically to the WS bridge at port 8899.

---

## Frontend development

See `frontend_source/README.md` for the edit → build → deploy workflow.
