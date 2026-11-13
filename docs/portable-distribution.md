# Portable production distribution

The source tree is the application. `distribution/` contains templates for the
outer production package; do not replace the source-root launcher with that
package launcher.

The deployed layout is:

```text
D:\DahanPhotoLibraryData\
  prototype\                 catalogue.sqlite, sync.sqlite, generated assets
  models\                    YuNet/SFace models
  production\
    app\                     this source tree plus frontend/dist
    python\                  isolated Python and installed requirements
    gateway\password_gateway.py
    tunnel\cloudflared.exe
    tunnel\tunnel.token      private, never commit
    cachepacks\<pack-id>\    verified immutable image-cache packs
    cache-pack-config.json
    Start-DahanLibrary.ps1
    Start-DahanLibrary.cmd
    Install-Host.ps1
    Verify-DahanRuntime.py
    logs\
D:\DahanPhotosSync\           existing local original media
```

Copy the top-level distribution templates to the production root. The launchers in
`distribution/drive-root/` belong at the drive root (`D:\\` in this layout). Copy the built application
to `app/`, and `scripts/password_gateway.py` to `gateway/`. Provision the isolated
Python environment, models and Cloudflared separately. Copy the example cache
configuration to `cache-pack-config.json` and set its relative path to an actually
verified pack. The pack needs its index, ownership and successful verification
receipt, plus the listed ZIP_STORED archives. A fabricated receipt is not a substitute
for source/checksum verification. Source development installations can omit
`DAHAN_CACHE_PACKS` and continue using ordinary generated-image files.

The package launcher checks the already-registered Cloudflared service first,
starts the backend on `0.0.0.0:80`, ensures the loopback gateway on `127.0.0.1:8787`,
and checks local and public health plus the expected frontend version. It reuses
existing healthy processes and rejects unrelated port owners. Only starting a
stopped Windows service may require elevation; the application runs as the user.
The configured public route is tunnel → loopback gateway → backend. This template
uses the existing deployment's `dahanphotos.com` endpoint; configure the hostname,
host registration and tunnel for another installation.

`Install-Host.ps1` is an installation-specific registration helper for the existing
Cloudflared service. Inspect it before using on another host. Its ownership marker,
service token, cache receipts and machine configuration are deployment state,
not source artifacts. `Verify-DahanRuntime.py` audits a fully assembled package;
run it with the bundled isolated interpreter from that package.

Verified cache reads check member CRC and SHA, and support HTTP range requests.
Existing loose files remain readable. New generated images use the sharded
`prototype/cache-image-overrides` tree. Original media and databases are never
stored in cache archives. NAS original-media roots remain on the NAS unless
explicitly migrated; a portable application does not make those originals local.

## Frontend validation

Build with `npm ci --prefix frontend` and `npm run build --prefix frontend`.
Install Playwright in the development environment and run:

```text
node tests/library_release_ui.cjs <path-to-playwright-module>
node tests/nonblocking_preview_ui.cjs <path-to-playwright-module>
```

These checks use a fixture server and write screenshots to temporary directories.
They cover responsive controls, search dismissal, sharing/saving handoff,
unobstructed loading notices, nonblocking previews, menu cancellation, mobile
portrait/landscape sheets, and width-aware information rows. Native share/save
destinations depend on the browser and operating system.

Databases, originals, thumbnails, cache archives, credentials, tunnel tokens,
runtime binaries, node_modules, builds, logs and machine-local configuration must
remain outside Git. Keep backups before moving an existing installation.
