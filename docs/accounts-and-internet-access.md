# Dahan permanent internet access

Updated 13 November 2026.

- Public address: https://dahanphotos.com. Use this HTTPS address for sign-in, including at home.
- Cloudflare tunnel: `dahan-photos` (`6792fe04-0c22-424f-9d45-b80ab1d116f5`).
- Route: Cloudflare -> loopback gateway on 8787 -> photo backend on 80.
- Cloudflare supplies the tunnel and HTTPS. The local photo application owns accounts, password hashes, passkeys, sessions, preferences, and activity in the catalogue database.
- Accounts: Yoav, Hila, Bar, Rotem, Guy, Guest. Initial passwords follow the owner-requested Firstname1919 convention, with capitalized first letter. Each account must change its initial password before library access or passkey enrollment. New passwords require at least 10 characters.
- Open **Your name · Account** to change password, enable Face ID / fingerprint, remove a passkey, or sign out / switch user.
- Passkeys are bound to dahanphotos.com. Device verification may use Face ID, fingerprint, or screen-lock PIN. Biometric data never reaches this server. Password sign-in remains available.
- Password change revokes previous sessions. Passkey removal revokes other sessions. Sessions expire after 12 hours; credentials and preferences persist across service restarts.
- All accounts currently share the same library permissions, including Guest. Activity is attributed to the signed-in identity. Theme and source choices remain separate per account.
- Cloudflare Windows service `cloudflared` is Automatic. The registered service now uses the bundled D: tunnel executable and a private token file in the production tunnel directory.
- Photo service and proxy start when Windows user `user` signs in. Startup shortcut: `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Dahan Photo Access.lnk`.
- Gateway and startup supervisor: `D:\DahanPhotoLibraryData\production`. The private tunnel token and machine registration state remain outside Git. The legacy shared `secret.json` is no longer used.
- The PC must stay awake, online, and signed in. A reboot test has not been performed.

Validation: six backend/gateway tests passed; an isolated mobile browser test covered first password change, passkey enrollment and sign-in with a virtual authenticator, and session restoration. Public HTTPS checks confirmed initial login, secure cookie, required password change, protected photos, and logout. Real Face ID / fingerprint enrollment must be completed on each user's device.

The deployment preserves existing preferences and adds account tables. Application-file backup: `dahan-source-staging\accounts-deploy-backup-20261107-092415`. Source backup: `dahan-source-staging\accounts-source-backup-20261107-092330`. Restoring the old gateway also restores the old shared-password behavior; do not restore only the old backend while leaving the new proxy active.
