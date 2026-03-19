# Frontend Source — Development Only

This folder is for the React web-app **source code**.
It is **not used at runtime** by the Omniverse extension.

---

## Folder roles

| Folder | Purpose | Used at runtime? |
|---|---|---|
| `../data/webapp/` | Compiled/built web assets served by the extension HTTP server | **Yes** |
| `frontend_source/` (this folder) | React source code, `package.json`, build config | **No** |

The extension Python code (`extension.py`, `backend/`, `transport/`) reads only
from `data/webapp/` as defined by the `webRoot` setting in `config/extension.toml`.

---

## Development workflow

1. Place your React project here (`package.json`, `src/`, etc.).
2. Make your UI changes.
3. Build the project:
   ```bash
   npm install
   npm run build
   ```
4. Copy the build output into the runtime folder:
   ```bash
   # From this directory (adjust 'build/' to your framework's output folder)
   cp -r build/* ../data/webapp/
   ```
5. Restart the extension (or reload the browser) to pick up the new assets.

> **Note:** Only the contents of `../data/webapp/` are tracked as runtime
> extension assets. Frontend source files in this folder are for development
> purposes only and do not affect the running extension directly.

---

## Current compiled build

The file `../data/webapp/asset-manifest.json` lists the entry points that are
currently deployed and served by the extension.
