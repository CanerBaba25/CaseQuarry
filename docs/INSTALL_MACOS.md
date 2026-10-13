# Install on a MacBook

Download `CaseQuarry_VERSION_universal.dmg` and its matching `.sha256` from the regular release. The disk image contains Apple Silicon and Intel code in one application. Verify the checksum before opening it, then drag CaseQuarry into Applications.

```sh
shasum -a 256 CaseQuarry_VERSION_universal.dmg
```

The native client requires macOS 11 or later and uses the system WKWebView. It has an ad-hoc signature, without Developer ID signing or notarization. macOS may ask for explicit approval through Privacy & Security. Follow your firm's security policy; do not disable Gatekeeper or remove system protections to install it.

Open CaseQuarry, enter the firm's final HTTPS origin and connect. Sign in with the account supplied by the firm administrator. The administrator deploys the [shared PostgreSQL server](SERVER_INSTALL.md) on its Windows or Linux host; the Mac client and other computers use that same server. The client does not contain a separate database, copy evidence to the Mac, or provide offline review.

The optional saved URL is restricted to the current account; passwords and provider keys are not stored by native preferences. The Mac shortcut to return to connection settings is `Cmd+Shift+C`. See [desktop installation and security](DESKTOP.md) for connection checks, session boundaries and source build instructions. Browsers on a Mac can use the same HTTPS firm website without installing the desktop client.
