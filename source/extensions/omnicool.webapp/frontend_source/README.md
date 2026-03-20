# Frontend Source (Development Only)

This folder is for the React frontend source code. It is **not** used by the
extension at runtime. Place the React project here for development.

## Folder roles

| Folder | Purpose |
|---|---|
| `../data/webapp/` | **Runtime** — compiled web app served by the extension HTTP server |
| `frontend_source/` (this folder) | **Development only** — React source; not loaded by the extension |

## How to update the web app

1. Develop and iterate inside this folder (or in `webrtc-react/` at the
   repository root, which mirrors this location).
2. Build the React app:
   ```
   npm run build
   ```
3. Copy the build output into `../data/webapp/`:
   ```
   cp -r build/* ../data/webapp/
   ```
4. Commit the updated `data/webapp/` contents.

> **Never** point the extension's `webRoot` setting at this folder.
> The extension only reads from `data/webapp/`.
