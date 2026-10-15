<p align="center"><img src="frontend/public/brand/dahan-photo-mark-v2.png" alt="Dahan" width="96"></p>
<h1 align="center">Dahan · Family Library</h1>
<p align="center"><strong>ALPHA</strong> · Your photos, your people, your places.</p>

A self-hosted photo/video library for a household, with local face recognition,
offline maps, and desktop/mobile browsing. The current milestone adds configurable
Databases → Sources → Albums and guided, repeatable face-review automation.

The application currently targets a Windows host on a trusted home network.
Accounts, authentication and HTTPS provisioning are not implemented; keep the
unauthenticated server off the public internet.

## Documentation

- [User guide](docs/USER_GUIDE.md): databases, relayout, scanning, People, metadata and mobile workflows.
- [Operations](docs/OPERATIONS.md): startup, storage locations, stopping work, backups, recovery and moving disks.
- [15 October 2026 milestone](docs/MILESTONE-2026-10-15.md): implementation summary, validation and remaining work.
- [Changelog](CHANGELOG.md).

## Features

- **Library tools:** register folders with editable Database/Source aliases, choose among three layout interpretations, preview file assignments, and manage independent visibility, sync and schedules.
- **Advanced relayout:** subtree Source overrides, child Databases and logical Linked Sources across Databases. Confirm catalogue migrations while preserving media identities and annotations.
- **Network originals:** localhost-only credential entry, Windows Credential Manager persistence, existing-session recovery and unavailable-drive handling.
- **Resumable scans:** durable directory snapshots, file/work checkpoints, Pause/Stop/Resume, live folder/file progress and incremental publication into Library.
- **People:** local detection, naming, correction, split/merge, undo, bounded review pages and transactional bulk approval. A user-started high-confidence loop approves → reevaluates → repeats, with progress and Stop.
- **Dates and locations:** preserve embedded data; edit missing/estimated dates or named places/coordinates through previewed catalogue changes. Map includes Unlocated and No GPS collections.
- **Browsing:** unified search, offline maps, timeline/date sorting, Album/Sub Album paths, large previews, prefetched neighbors and touch navigation.
- **Mobile:** immediate loading shell and iOS launch images; in-app HTTP save helpers and separate Safari downloads; native file sharing when trusted HTTPS is available.
- **Duplicates:** reviewed exact/format-copy cleanup, recoverable trash, restore and display-only HEIC/JPEG copy hiding.
- **Runtime:** separate application/derivative and SQLite storage, JSON storage errors, health reporting and a supervised production launcher.

## Development setup

Prerequisites: Python 3.12, Node.js 22+, npm, and storage for derivatives and models.
Run from the checkout in PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
npm ci --prefix frontend
npm run build --prefix frontend -- --configLoader runner

$env:DAHAN_DATA = 'C:\DahanDev\runtime'
$env:DAHAN_DATABASE_DIR = 'C:\DahanDev\databases'
$env:DAHAN_SOURCE = 'C:\DahanDev\originals'
# Create/use your own disposable originals folder for development.
New-Item -ItemType Directory -Path $env:DAHAN_SOURCE -Force | Out-Null
.\.venv\Scripts\python.exe -c "from backend.indexer import models; models()"
.\scripts\start.ps1
```

Open **http://127.0.0.1:8765/**. Configure folders in **Library tools → Databases,
Sources & Albums** before starting sync. Startup registers/migrates the initial
legacy root; additional folders are registered through the app. New local
catalogues can be initialized by this development launcher; installed servers
use the existing-database guard described in [Operations](docs/OPERATIONS.md).

Face models, map references and FFmpeg are needed for the corresponding
enrichment stages. See the user/operations guides for offline map installation.
For frontend development, run `npm run dev --prefix frontend` alongside the API;
Vite proxies `/api` to port 8765.

## Verify and release

```powershell
.\scripts\check.ps1
```

This runs the backend tests on temporary fixtures and the TypeScript/Vite build.
Optional mocked browser checks cover manual approval, progress and the automatic
loop. With Playwright and Edge available:

```powershell
.\scripts\check.ps1 -BrowserChecks -PlaywrightModule 'C:\path\to\node_modules\playwright'
```

The milestone passed **389 backend tests**, the production build and browser
checks. Migration, removal, interruption and approval tests used isolated
catalogues and disposable media. Physical iPhone/native-share and clean-machine
installation certification remain separate work.

Each frontend build has a unique release ID. Deploy hashed assets first,
`index.html` next and `version.json` last; retain earlier hashed assets for open
tabs. Built output, libraries, SQLite files, credentials, models, logs and media
do not belong in Git. Production startup does not build or install dependencies.

## Attribution

Face models and upstream licence files come from [OpenCV Zoo](https://github.com/opencv/opencv_zoo).
Boundaries are from [Natural Earth](https://www.naturalearthdata.com/) (public
domain), and place names from [GeoNames](https://www.geonames.org/) (CC BY 4.0).
Dependencies retain their licences. This repository does not assign a new
open-source licence to the application.
