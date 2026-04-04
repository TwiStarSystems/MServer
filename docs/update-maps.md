# BlueMap Integration Guide

This document explains how BlueMap is integrated into MServerController for the **World Map** feature, and how to update or troubleshoot it.

## Overview

[BlueMap](https://github.com/BlueMap-Minecraft/BlueMap) is an open-source tool that reads Minecraft world files and generates interactive 3D maps viewable in a browser. MServerController uses the **BlueMap CLI** (standalone mode, no plugin required) to render maps on demand and serves the output through the Flask backend.

- **Project Website:** https://bluecolored.de/bluemap/
- **Documentation:** https://bluemap.bluecolored.de/
- **GitHub:** https://github.com/BlueMap-Minecraft/BlueMap
- **Releases:** https://github.com/BlueMap-Minecraft/BlueMap/releases

## How It Works

### Architecture

```
MServerController
├── tools/bluemap/
│   └── bluemap-cli.jar          ← Shared JAR (downloaded once)
└── servers/<server-id>/
    ├── world/                   ← Minecraft world data
    ├── bluemap-config/          ← Per-server BlueMap config (HOCON .conf files)
    │   ├── core.conf
    │   ├── webapp.conf
    │   ├── webserver.conf       ← Disabled (Flask serves instead)
    │   ├── maps/
    │   │   ├── overworld.conf
    │   │   ├── nether.conf
    │   │   └── end.conf
    │   ├── storages/
    │   │   └── file.conf
    │   └── .last_render         ← Timestamp marker
    └── bluemap/web/             ← Rendered output (served to browser)
        ├── index.html           ← Vue 3 + Three.js viewer
        ├── assets/
        ├── settings.json
        └── maps/
            ├── overworld/       ← Rendered tile data
            ├── nether/
            └── end/
```

### Flow

1. **Install:** User clicks "Install BlueMap" → downloads `bluemap-cli.jar` from GitHub releases → runs it once to generate default configs → patches configs to point at the server's world directory.
2. **Render:** User clicks "Render Map" → spawns `java -jar bluemap-cli.jar -c <config> -r -g` in a background thread → monitors stdout for progress.
3. **View:** The rendered web files are served through Flask at `/api/servers/<id>/bluemap/viewer/` and embedded in an iframe in the World Map tab.

### Key Design Decisions

- **BlueMap's built-in webserver is disabled** (`webserver.conf → enabled: false`). Flask serves the static files instead, keeping everything behind the existing auth system.
- **One JAR, per-server configs.** The CLI JAR is shared in `tools/bluemap/`, but each server gets its own config directory and output directory.
- **No plugin needed.** The CLI reads world files directly from disk — works with any server type (Vanilla, Paper, Forge, etc.).

## Updating BlueMap

### Update the JAR

1. Delete the old JAR:
   ```
   rm tools/bluemap/bluemap-cli.jar
   ```

2. The next time a user clicks "Download & Install" from the World Map tab, it will query the GitHub API for the latest release and download the correct CLI JAR automatically:
   ```
   https://api.github.com/repos/BlueMap-Minecraft/BlueMap/releases/latest
   ```
   The asset name varies by version (e.g. `bluemap-5.18-cli.jar`), so the API is used to find the correct download URL.

   Or download manually:
   ```bash
   cd tools/bluemap/
   # Check the latest release page for the exact filename
   wget https://github.com/BlueMap-Minecraft/BlueMap/releases/download/v5.18/bluemap-5.18-cli.jar -O bluemap-cli.jar
   ```
   
   Or use the **Upload JAR from Local** button in the UI to upload a manually-downloaded JAR.

3. After updating, do a **full re-render** (click "Full Re-render" in the UI) to regenerate configs and tiles with the new version.

### Regenerate Configs

If BlueMap's config format changes between versions, you may need to regenerate configs for each server:

1. Delete the per-server config directory:
   ```bash
   rm -rf servers/<server-id>/bluemap-config/
   ```

2. Open the World Map tab and click "Render Map" — configs will be auto-regenerated.

### Manual Config Editing

Per-server configs are in `servers/<server-id>/bluemap-config/`. Key files:

| File | Purpose |
|------|---------|
| `core.conf` | Render thread count, data directory, metrics |
| `webapp.conf` | Webroot path, viewer UI settings |
| `webserver.conf` | Should stay `enabled: false` (Flask serves) |
| `maps/overworld.conf` | World path, sky color, render area, LOD settings |
| `maps/nether.conf` | Nether dimension config |
| `maps/end.conf` | End dimension config |
| `storages/file.conf` | Output directory, tile compression |

Common tweaks:
- **Limit render area:** Edit `maps/overworld.conf` and add a `render-mask` (circle/box shape)
- **Increase render threads:** Edit `core.conf` → `render-thread-count` (default: 1)
- **Change LOD:** Edit `maps/overworld.conf` → `lod-count` (default: 3), `lod-factor` (default: 5)

## BlueMap CLI Reference

```bash
# Generate/update default configs
java -jar bluemap-cli.jar -c <config-dir>

# Render all maps
java -jar bluemap-cli.jar -c <config-dir> -r

# Force full re-render (ignores change tracking)
java -jar bluemap-cli.jar -c <config-dir> -r -f

# Render + regenerate webapp files
java -jar bluemap-cli.jar -c <config-dir> -r -g

# Render specific maps only
java -jar bluemap-cli.jar -c <config-dir> -r -m "overworld,nether"

# Start built-in webserver only (not used in our integration)
java -jar bluemap-cli.jar -c <config-dir> -w
```

Full CLI options: `java -jar bluemap-cli.jar --help`

## Requirements

- **Java 17+** must be installed on the host (same Java used by Minecraft servers).
- Rendering is CPU and disk-intensive. A large world can take significant time on the first render. Subsequent incremental renders are much faster.
- The Minecraft server should ideally be **stopped** during rendering to avoid reading partially-written chunks, though BlueMap handles this gracefully in most cases.

## API Routes

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/servers/<id>/bluemap/status` | Get install/render status |
| POST | `/api/servers/<id>/bluemap/setup` | Download latest JAR via GitHub API + generate configs |
| POST | `/api/servers/<id>/bluemap/update` | Force re-download latest JAR from GitHub |
| POST | `/api/servers/<id>/bluemap/upload` | Upload a local JAR file |
| POST | `/api/servers/<id>/bluemap/render` | Start a render (`{ "force": true }` for full) |
| GET | `/api/servers/<id>/bluemap/viewer/` | Serve the web viewer (iframe src) |

> **Note:** The World Map tab is hidden for Bedrock servers since BlueMap only supports Java Edition world files.

## Troubleshooting

- **"BlueMap Not Installed"** — Click Install. Requires internet access to download from GitHub.
- **Render never finishes** — Check that Java 17+ is installed (`java -version`). Check server logs.
- **Map is blank/empty** — The Minecraft server needs to have been started at least once to generate world files in the `world/` directory.
- **Configs out of date** — Delete `servers/<id>/bluemap-config/` and re-render.
- **Tiles not loading in viewer** — BlueMap stores tiles gzip-compressed. The Flask route handles `.gz` content encoding automatically.
