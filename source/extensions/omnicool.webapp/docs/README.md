# Omnicool [omnicool.webapp]

A web-app–backed Omniverse Kit extension that serves a compiled React frontend
and bridges it to USD stage data and the Flownex simulation backend over
WebSocket and WebRTC.

## Extension folder structure

```
omnicool.webapp/
  config/extension.toml    — extension manifest and default settings
  docs/                    — this documentation
  data/
    webapp/                ← RUNTIME: compiled web app served by the HTTP server
                             (index.html, static/js/*.js, static/css/*.css …)
                             Update by running `npm run build` in the React
                             source folder and copying the output here.
  omnicool/webapp/
    extension.py           — Kit extension lifecycle; starts HTTP + WS servers
    backend/               — USD helpers, Flownex bridge, WS message dispatcher
    transport/             — HTTP static server, WebSocket/WebRTC transport
  frontend_source/         ← DEVELOPMENT ONLY: React source code
                             Not used at runtime; kept for future development.
                             See frontend_source/README.md for build instructions.
```

## Runtime vs. source

| Folder | Used at runtime? | Purpose |
|---|---|---|
| `data/webapp/` | **Yes** | Compiled web assets served by the extension |
| `frontend_source/` | **No** | React source; requires a build step before deployment |

The repository root `webrtc-react/` directory mirrors `frontend_source/` as the
canonical location for the React project source.

## Servers started by the extension

| Server | Default | Protocol | Purpose |
|---|---|---|---|
| HTTP static | `http://127.0.0.1:3001` | HTTP | Serves `data/webapp/` |
| USD WS bridge | `ws://127.0.0.1:8899` | WS | USD stage queries (`usd.*`, `flownex.*`) |
| Bridge + WebRTC | `ws://127.0.0.1:8001` | WS + HTTP | Flownex push protocol + WebRTC signaling at `/webrtc/offer` |
| Standalone WebRTC | `http://127.0.0.1:8900` | HTTP | Optional; enabled via `webrtcEnabled = true` |

