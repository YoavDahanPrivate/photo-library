<p align="center"><img src="frontend/public/brand/dahan-photo-mark-v2.png" alt="Dahan" width="96"></p>
<h1 align="center">Dahan · Family Library</h1>
<p align="center"><strong>ALPHA</strong> · Your photos, your people, your places.</p>

A self-hosted photo and video library for a household. Browse media from multiple phones, find familiar faces, explore memories on a map, and keep a growing library up to date. Designed for desktop and mobile, including an iPhone Home Screen web app.

**Actively developed ALPHA.** The current target is a trusted home network and Windows host. There are no accounts or authentication: do not expose it directly to the internet. Keep backups of originals and application data.

## Features

- **Library:** timeline grouping, phone/album filters, date sorting, and Photos & Videos / Photos / Videos selection.
- **Unified search:** saved people, countries/cities, devices, dates, albums, media types and map areas, with cursor-aware autocomplete.
- **Maps:** offline country/city labels, stable clusters, multiple included/excluded areas, rectangle zoom, and results combined with other filters.
- **People:** local face detection, naming, correction, merge/split, undo, name-conflict repair and manual marking of missed faces.
- **Sync:** on demand or hourly/daily/weekly/monthly; previews appear before recognition finishes; pause/cancel/resume; optional repeated high-confidence assignment.
- **Duplicates:** exact-file and separate metadata-based HEIC/JPEG review, cross-page selection, recoverable trash and restore. Display-only format-copy hiding defaults on for new browser preferences.
- **Viewer:** large-thumbnail previews, prefetched neighbors, direct swipe dragging, zoom/pan, metadata and full-resolution expanded viewing.
- **Mobile:** scrolling search controls, explicit clear-search button, compact metadata, touch controls and save/share alternatives.
- **Updates:** release detection on opening/resuming and while active; idle reload or an Update now button during editing.
- **Themes:** Sage, Ocean, Plum, Black (light grayscale) and Dark; saved in the browser.

## Quick start

Prerequisites: **Python 3.12**, **Node.js 22+**, npm, and space for originals plus derivatives. The pinned dependencies describe the development environment; installation on a completely clean machine has not yet been certified.

From the repository root in PowerShell:

~~~powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
Set-Location frontend
npm ci
npm run build
Set-Location ..
~~~

Choose runtime storage outside the checkout:

~~~powershell
$env:DAHAN_DATA = 'D:\DahanPhotoLibraryData\prototype'
$env:DAHAN_SOURCE = 'D:\DahanPhotosSync'
$env:DAHAN_DISABLE_SCHEDULER = '1'
New-Item -ItemType Directory -Force -Path $env:DAHAN_DATA | Out-Null
~~~

**Before syncing, configure source folders.** The ALPHA still lists allowed phone-folder names in **backend/core.py → PHONES**. Replace those entries with your immediate subfolder names under DAHAN_SOURCE. Source-folder configuration through the UI is not implemented.

Download local face models and their upstream licence files, then start the API and built frontend:

~~~powershell
.\.venv\Scripts\python.exe -c "from backend.indexer import models; models()"
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8765
~~~

Open **http://127.0.0.1:8765/**. Use **Library tools → Sync & recognition → Sync now**. The environment flag above disables background scheduling during setup; set it to 0 and restart when ready to enable schedules. The backend must remain running for scheduled jobs.

The PowerShell helper scripts retain development-machine paths. Use the commands above for another machine, or review and adapt the helpers first.

## Home-network access

~~~powershell
$env:DAHAN_LAN_ADDRESS = '192.168.1.50' # Your server's actual IPv4 address
$env:DAHAN_DISABLE_SCHEDULER = '0'
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --host 0.0.0.0 --port 80
~~~

Allow the server through Windows Firewall on your private network, then open its LAN address. The explicit host allowlist also accepts **dahanoffice** and **dahanoffice.local**, with HTTP origins on port 80. Your network must resolve these names; the app does not create DNS records. Other aliases can be configured in backend/app.py.

### iPhone Home Screen

Open the URL in Safari and use **Share → Add to Home Screen**. Automatic updates preserve saved preferences; an explicit reload clears unsaved edits. An installation predating the update mechanism must load it once manually.

Native fullscreen and saving to Photos depend on iOS/Safari capabilities. HTTP LAN hosting cannot use secure-context Web Share, so open/save and original-download alternatives are available. Physical iPhone gesture and lifecycle validation remains part of ALPHA testing.

## Offline maps and place names

Install the overview coastline:

~~~powershell
.\.venv\Scripts\python.exe scripts/download-map.py
~~~

Place these reference files in **DAHAN_DATA/maps/**:

| File | Source |
| --- | --- |
| countries.geojson | [Natural Earth countries, 1:50m](https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson) |
| cities1000.zip | [GeoNames cities1000](https://download.geonames.org/export/dump/cities1000.zip) |

Run **python -m backend.place_names** using the configured environment to enrich the catalogue. Nearby settlement labels and country boundaries are approximate. Media without GPS remains searchable through other filters.

## Search examples

~~~text
Includes("Alex") and Place("Italy")
Phone("My iPhone") and after 2025
between May 2025 and April 2026
Place("USA") and MediaType("video")
date >= 2025 and date < 2026
~~~

Use actual saved names/devices from your catalogue. Bare recognized names and places are accepted. Boolean AND/OR/NOT, parentheses, and date comparisons <, <=, >, >=, =, == and != are supported. After/before exclude the named period; between includes both endpoints. Recognition filters describe detected faces, not a guarantee about everyone present.

## Architecture and storage

| Layer | Implementation |
| --- | --- |
| UI | React, TypeScript, Vite, local SVG maps |
| API | FastAPI / Uvicorn |
| Catalogue and jobs | SQLite, durable job records and resumable processing |
| Images | Pillow / HEIF support, OpenCV |
| Faces | Local YuNet / SFace models and reference-example matching |
| Video | FFmpeg via imageio-ffmpeg; sampled frames and compatible previews |

DAHAN_SOURCE contains uploaded originals. DAHAN_DATA contains databases, thumbnails, face crops, previews and map data. Face models live in a sibling models directory. Runtime data and personal media are excluded from this repository.

Indexing does not rewrite originals. **Duplicate cleanup intentionally moves selected original files** into recoverable .dtrash/dahan-duplicates folders. Restore refuses to overwrite conflicting paths. Trash does not free disk space.

Back up originals, both SQLite databases and supporting runtime data. Use a consistent SQLite backup or stop the server before copying databases; copying only an active main database file can omit WAL data. Existing checkpoints are not a substitute for tested disaster recovery.

## Development and release

Run the API on port 8765 and **npm run dev** in frontend/; Vite proxies /api to that port.

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests -q
Set-Location frontend
npm run build
~~~

Backend tests use temporary fixtures. Supplemental JavaScript regression scripts in tests/*.cjs expect transpiled modules in their named qa-* folders; these are developer checks, not yet a unified test runner.

Each frontend build embeds a unique release ID and emits version.json. Deploy hashed assets first, index.html next, and version.json last. Retain older hashed assets for already-open sessions. The backend serves the shell and version manifest without caching. Avoid modifying the release manifest independently of its matching JavaScript build.

If Vite’s default config bundler encounters a directory-access error in a restricted Windows environment, use **npm run build -- --configLoader runner**. The ALPHA snapshot passed TypeScript and this alternate-loader production build.

Recent work passed TypeScript, production builds, scoped regression tests and browser checks. Historical full-suite results do not represent fresh certification of this complete snapshot. No clean-machine or physical-iPhone certification is claimed.

## Remaining work

- Object, animal, scenery and occasion searches, such as trips or parties.
- Recognition accuracy evaluation and performance tuning. Scores are heuristics, not calibrated probabilities; automatic predictions do not become trusted reference examples without confirmation.
- Same-frame video co-occurrence search and manual face marking in arbitrary video frames. Current recognition samples can miss brief appearances.
- Full-length browser-compatible video delivery. Standard compatible previews are limited to 60 seconds; originals depend on browser codec support.
- Live Photo pairing.
- Accounts, per-user permissions, HTTPS provisioning and Windows-service installation.
- Production storage/database validation and tested backup/restore.
- Continued testing of large libraries, offline drives, source-file errors and native mobile interactions.

## Attribution

Models come from [OpenCV Zoo](https://github.com/opencv/opencv_zoo), with their upstream licence files. Boundaries are from [Natural Earth](https://www.naturalearthdata.com/) (public domain); place names are from [GeoNames](https://www.geonames.org/) (CC BY 4.0). Dependencies retain their own licences. This snapshot does not assign a new open-source licence to the application.
