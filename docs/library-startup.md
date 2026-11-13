# Current production startup (13 November 2026)

The completed distribution is `D:\DahanPhotoLibraryData\production`.
Run `D:\Run-DahanLibrary.cmd` (or `D:\Start-DahanLibrary.cmd`). The package launcher
checks/starts the registered D: tunnel service before starting missing backend and
gateway processes, then verifies local/public health and the frontend release.
Databases and runtime assets are in `D:\DahanPhotoLibraryData\prototype`.
See [portable distribution](portable-distribution.md) for package layout and templates.

The source-root launcher below remains available for a configured development or
non-bundled installation. It is distinct from the outer package launcher in
`distribution/`.

## Source installation and release checks

For a source installation, use the application checkout configured by `dahan-config.json`.
Double-click `Start-DahanLibrary.cmd`, or run `Start-DahanLibrary.ps1` in PowerShell.
The launcher starts the backend on `0.0.0.0:80`, supervises the loopback gateway on
`127.0.0.1:8787`, and starts the installed Cloudflared service if necessary.
Starting a stopped Windows service may require an Administrator shell.
Existing matching listeners are reused; unrelated processes are never stopped.

The configured Cloudflare tunnel must route `dahanphotos.com` to
`http://127.0.0.1:8787`. The gateway defaults to
`%LOCALAPPDATA%\DahanTunnelTest` (override with `-GatewayDirectory`).
LAN IPv4 is detected from the default-route adapter; use `-LanAddress` if there
are multiple adapters. The backend keeps schedules disabled by default.

Success requires available storage, a matching deployed-release manifest,
the expected public release version, and HTTP 401 for anonymous public account
access. Results are saved to `../logs/startup-verification.json`.
A running Cloudflared service alone does not count as a working tunnel.
The launcher does not fetch source or rebuild on startup.

After building, testing, and deploying a new release, regenerate its manifest:

```powershell
python scripts/write-release-manifest.py U:\DahanPhotoLibraryData\library-tools-release
```

Generate this only after validating the deployed files; it records their current
hashes rather than proving they came from Git. Do not commit the machine-specific
manifest. Keep the existing server configuration and tunnel credentials local.

The Library uses one scroll surface on desktop, TV and phones. Completed People
notices and general confirmations fade after 30 seconds, with a dismiss control;
People notices include a review/report action. Active progress remains visible.
Run `node tests/library_notices_scroll_ui.cjs [path-to-playwright]` after building
for notification and scroll regression checks at desktop, TV and phone widths.

# Dahan storage layout — user decision, 2026-11-10

D: is the authoritative persistent library-data drive. Keep main databases at D:\DahanPhotoLibraryData\prototype. Intended runtime assets (thumbnails, previews, faces, frames, matching data and maps): D:\DahanPhotoLibraryData\runtime. U:\DahanPhotoLibraryData is for application deployment, source copies, Python environment and logs, not authoritative library data.

Inspection 2026-11-10: C:\DahanPhotoLibraryData\logs\current-80.json records application and runtime on C: and databases on D:. This is a saved launch record, not proof of current process state. Copied U: server-config.json retains those paths. Neither deployment contains dahan-config.json. U: venv\pyvenv.cfg still references C: Python; repair/rebuild before relying on U: independently. Code resolves model files under DATA.parent/models, so D:\DahanPhotoLibraryData\models is needed with the intended runtime path unless code is changed.

D: reads remain access-denied even after session read permission was granted. Local port 80 refused connection. Live database content, free space and running process configuration could not be verified. Do not assume D: databases are missing. No live configuration, database or service was modified. Preserve C:, U: and D: copies until migration is validated.
