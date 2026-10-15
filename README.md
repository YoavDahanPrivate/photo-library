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
- [Face matching](docs/FACE_MATCHING.md): calibration, review batches, cached comparisons and model candidates.
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

## Install on your own Windows PC

Prerequisites: Python 3.12 (with the Windows `py` launcher), Node.js 22+ with npm,
internet access during installation, and at least 10 GiB free for scanning in
addition to the space your thumbnails and previews will need. Clone/download
this repository, open PowerShell in that folder, then run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\start-production.ps1 -Port 8765
```

Open **http://127.0.0.1:8765/**, then go to **Library tools → Databases, Sources &
Albums → + Add Database**. Choose/type your own original folder, review the
suggested Sources/Albums, confirm, and start Sync. A fresh install has **zero
registered Databases, Sources or media**. No folder on the developer's computer
is required or registered automatically.

The installer creates a local Python environment, installs locked dependencies,
builds the frontend, downloads face models and public offline map references,
and initializes both catalogues. Downloads may take several minutes. It stores
installation paths in ignored `dahan-config.json`; no NAS credentials go there.
The default runtime/catalogue location is
`%LOCALAPPDATA%\DahanPhotoLibrary\runtime`. Logs, backups and models are sibling
folders. Thumbnails are files under `runtime\thumbs`, referenced by SQLite.

Choose different runtime and catalogue disks at installation if desired:

```powershell
.\scripts\install.ps1 -DataDirectory 'E:\PhotoLibrary\runtime' `
  -DatabaseDirectory 'F:\PhotoLibrary\catalogues'
```

Startup reads this installation's configuration. Launchers also accept explicit
path overrides and environment variables; original folder roots/aliases live in
the catalogue after registration. A different Windows account uses its own
default storage unless you explicitly configure a shared installation. Keep
`dahan-config.json` when backing up, but do not publish it with the source.

`-SkipDependencies` reuses an already provisioned Python/frontend environment;
`-PythonPath` selects that environment. `-SkipModels` / `-SkipMaps` omit optional
installation downloads for development, but recognition/location enrichment
requires those resources before a complete sync. `-CheckOnly` reports intended
paths without installing or creating a library. Production startup requires
both databases and never silently recreates a missing catalogue.

This is a PowerShell installer, not yet a signed one-click Windows installer.
First-run, folder registration, thumbnail creation and restart persistence are
covered by isolated tests. A completely separate physical PC remains a useful
release acceptance check.

## Development setup

Use the installer above, then `npm run dev --prefix frontend` alongside
`scripts/start.ps1`. Vite proxies `/api` to port 8765. The development launcher
can initialize disposable catalogues; use `-RequireExistingDatabase` for saved
libraries. Set `DAHAN_DATA` and optionally `DAHAN_DATABASE_DIR` when running
Python modules directly; the same per-user default applies otherwise.

`DAHAN_SOURCE` is an **optional legacy-upgrade setting**, never required for a
fresh install. An old catalogue without registered roots needs its original
root set explicitly during migration. Source folder names are inferred from
the old records; `DAHAN_LEGACY_SOURCES` can explicitly supply a JSON list of
additional immediate Source folders. Modern registered libraries keep stable
identities and annotations when upgraded. See [Operations](docs/OPERATIONS.md)
before moving an established installation.

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

The current source passed **403 backend tests**, the production build and three
browser checks, including independent-install and matching-quality tests. Migration, removal, interruption and approval tests used isolated
catalogues and disposable media. Physical iPhone/native-share and installation
on a separate physical PC remain separate release checks; isolated first-run
tests also exercise the Windows launcher.

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
