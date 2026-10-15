# Operating and recovering Dahan

## Storage boundaries

| Setting/location | Contents |
| --- | --- |
| Application checkout/release | Python/TypeScript source, built frontend and helper scripts. |
| `DAHAN_DATA` | Filesystem thumbnails (`thumbs`), crops (`faces`), video frames/previews, display originals, maps and People-operation progress/logs. |
| `DAHAN_DATABASE_DIR` | `catalogue.sqlite`, `sync.sqlite`, WAL/SHM sidecars and shared scan lock. Defaults to `DAHAN_DATA`. |
| `DAHAN_SOURCE` | Optional explicit root for upgrading a legacy catalogue; unused on fresh installations. |
| Sibling `models` directory | Local recognition models/licences. |
| `DAHAN_BACKUP_DIR` | Consistent pre-operation catalogue backups when supported by that operation. |

Thumbnails are filesystem files referenced by catalogue identities, not image
blobs embedded in SQLite. Keep both databases together when relocating them.
They include faces, history, annotations, schedules and discovery/work checkpoints.
Moving only code/derivatives does not change those identities. Original-root
validation excludes both runtime and database folders.

Fresh installations default to `%LOCALAPPDATA%\DahanPhotoLibrary\runtime`
for runtime/catalogues, with sibling `models`, `logs` and `backups` folders.
Run `scripts/install.ps1` once to create an empty library. It saves paths in the
ignored `dahan-config.json` beside the root launcher. Each owner adds their own
Databases through Library tools; no original folder or personal device is preset.

Keep the application, Python, derivatives and logs on reliable storage. Both
databases can be on a separate configured disk. Other original roots are
registered Databases; changing `DAHAN_SOURCE` does not relocate their paths.
Use Reconnect moved root for originals. Existing installation-level
`server-config.json` settings are accepted for upgrade compatibility; they
are local operational state and are never distributed with the project.

## Start a development server

The README describes environment/dependency/model setup. `scripts/start.ps1`
selects repository `.venv` or an installation sibling `venv`; override with
`-PythonPath` or `DAHAN_PYTHON`. It reads local installation configuration,
defaults to loopback port 8765, and disables schedules. An original root is not
required. Explicit overrides are useful for disposable development libraries.

```powershell
.\scripts\start.ps1 -DataDirectory 'C:\DahanDev\runtime' `
  -DatabaseDirectory 'C:\DahanDev\databases'
```

Use `-RequireExistingDatabase` for an existing catalogue. Add `-LanAddress` only
for the server's actual IPv4 address; that binds all interfaces and adds the
configured LAN host/origin. Add `-EnableSchedules` explicitly to enable schedules.
`-CheckOnly` resolves settings without starting a process or creating a library.

## Start the installed server

From a built release that contains the root launcher and `scripts/`:

```powershell
.\start-production.ps1 -Port 8765
```

The root launcher delegates to `scripts/start-production.ps1`. Settings come
from explicit parameters, environment variables, local
`dahan-config.json` (or legacy installation-level `server-config.json`), then
per-user defaults. The launcher uses the configured `DAHAN_LAN_ADDRESS`, otherwise
loopback. An explicit `-LanAddress` takes precedence; an empty explicit value
selects loopback. Additional DNS names are opt-in through comma-separated
`DAHAN_HOST_ALIASES`; no personal hostname is trusted by default.

All runtime, database, original, log, backup and Python paths are overridable.
For another installation, pass them explicitly. Keep code/Python/derivatives and
logs on reliable storage; the startup helper uses the configured Python and
standard Windows temporary storage.

```powershell
.\start-production.ps1 -PythonPath 'E:\Dahan\venv\Scripts\python.exe' `
  -RuntimeDirectory 'E:\Dahan\runtime' -DatabaseDirectory 'F:\Dahan\databases' `
  -LogsDirectory 'E:\Dahan\logs' `
  -BackupDirectory 'G:\Dahan-backups' -LanAddress '192.168.1.50'
```

`-CheckOnly` validates/resolves settings without launching. Production always
sets `DAHAN_REQUIRE_EXISTING_DATABASE=1`: absent/empty databases are not silently
recreated. It can still start the web shell when database storage is unavailable.
Run `scripts/install.ps1` for a fresh installation; restore both databases for
an existing library. Setup refuses a partial database pair instead of replacing
it. Ordinary startup never runs the installer or downloads dependencies.

The supervisor writes stdout/stderr and native-fault traces to the configured
log folder, restarts unexpected exits with 5–60 second backoff, and refuses an
occupied port. `current-<port>.json` records application/data paths, supervisor
and launcher PIDs and active log paths. `-SingleRun` disables restart; schedules
remain off unless `-EnableSchedules` is supplied. This is a manual launcher,
not a Windows service or reboot task. Startup never automatically resumes scans.

## Stop work and the server

1. Stop a People operation through its progress panel; wait for the terminal
   result. These separate workers can continue when the web backend restarts.
2. Pause or Stop scan in Library tools and wait for the saved checkpoint. Current
   decoding/network work may need to finish; matching checks controls between
   scoring blocks. Resume keeps completed work.
3. For a supervised server, create `stop-<port>.txt` in its log directory. Verify
   the recorded supervisor and Dahan listener before stopping those processes.
   Stop the supervisor first so it cannot immediately replace the backend.

Useful read-only checks:

```powershell
Get-Content (Join-Path $env:LOCALAPPDATA 'DahanPhotoLibrary\logs\current-80.json')
Get-NetTCPConnection -LocalPort 80 -State Listen
Invoke-RestMethod http://127.0.0.1/api/health
```

Do not stop an unrelated process just because it uses port 80. `current-80.json`
contains the Python launcher PID, while the listening native child can have a
different PID. Inspect command line/parentage before stopping it.

## Unavailable drives

`/api/health` reports server and storage separately. Static pages can remain
available while database APIs return actionable JSON 503 responses. Initialization
retries when storage returns; interrupted scans wait for explicit Resume. Missing
roots do not imply that all originals were deleted. People progress lives under
`DAHAN_DATA/people-operations`, and its status/Stop routes remain available when
catalogue initialization is unavailable. Transient Windows progress-file locks
are retried without misreporting a disconnected catalogue.

A supervisor cannot repair hardware or guarantee writes to a failing drive.
Drive I/O errors and filesystem repair warnings do not establish whether the
cause is the disk, cable, USB power or controller. No automatic filesystem repair/formatting is performed.

## Back up and restore

For a complete offline backup, finish/stop People workers and pause/stop scans,
then stop the backend and supervisor. Back up:

- Both SQLite databases, including any existing WAL files with their databases
  when making an offline copy. Never copy just a live main `.sqlite` file.
- The application/release, lockfiles, configuration, runtime derivatives, models
  and map references. A Python environment can be rebuilt; copied environments
  are not generally relocatable.
- Every original root separately, including any recoverable duplicate trash.

Alternatively use SQLite's online backup API for consistent individual database
snapshots; pause writers when taking a coordinated catalogue/job pair. Built-in
pre-migration snapshots are not a complete server/originals backup. Keep verified
backups on a different physical device. Do not overwrite the only known-good copy.

Restore into separate directories first. With the restored databases offline,
run `PRAGMA quick_check` against **each** SQLite file. Start an isolated instance
with schedules disabled, a different port and `DAHAN_REQUIRE_EXISTING_DATABASE=1`.
Verify media counts/IDs, people/corrections/history, manual date/location edits,
root ownership and paused checkpoints. Test thumbnail and original access before
resuming. Integrity checks do not establish physical-drive reliability.

Remembered NAS access is in the backend account's Windows Credential Manager,
scoped to the **database-directory path** and SMB server. Moving that directory
or changing account/computer may require re-entering credentials. Passwords are
not part of a Git checkout, catalogue snapshot or exported server configuration.

## Move to another disk

Stop writers as above. Copy the application, runtime/model/map files and the
coordinated database pair; rebuild the Python environment at its new location
from `requirements.lock.txt`. Pass the new launcher paths. For models, retain
the sibling `models` relationship to the runtime directory. Keep database paths
unchanged if only moving code/derivatives. Reconnect moved **original roots** in
the app rather than re-registering them. Verify identity/annotation preservation
before starting any scan. Keep the previous installation until recovery is tested.

## Offline maps

The installer downloads public offline references and builds the place index
without opening the media catalogue. To install these separately, set
`DAHAN_DATA` to the intended runtime directory and run:

```powershell
.\.venv\Scripts\python.exe -m backend.setup_references
```

To install only the overview map:

```powershell
.\.venv\Scripts\python.exe scripts/download-map.py
```

Put [Natural Earth country boundaries](https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson)
at `DAHAN_DATA/maps/countries.geojson` and [GeoNames cities1000](https://download.geonames.org/export/dump/cities1000.zip)
at `DAHAN_DATA/maps/cities1000.zip`. Run `python -m backend.place_names` with the
configured runtime/database environment to build/enrich offline place references.

## Maintenance and release scripts

`scripts/check.ps1` runs fixture tests/build and optional mocked browser checks
from a source checkout with tests and frontend dependencies installed.
`index-sample.ps1` and `scan-all.ps1` are explicit developer indexing commands;
they require configured paths and existing databases. `measure.py` accepts an
explicit runtime/database folder and API URL, with slow original/derivative walks
opt-in rather than assuming a 200-photo fixture. Prefer Library tools sync
for managed Pause/Stop/Resume. Full scan has its own pause-file behavior and
must not overlap a sync run; both use the shared scan lock.

Release source changes and dependencies together. Copy hashed frontend assets
before `index.html`, and `version.json` last. Retain old assets for open sessions.
Inspect active scans/People jobs before a backend restart. Do not include runtime
data, models, NAS passwords, personal originals, compiled output or machine-local
deployment logs in Git. Operational snapshots/checkpoints stay outside the repo.
