# CaseQuarry Desktop

CaseQuarry Desktop is a connection client for a running CaseQuarry firm server. Windows, MacBook and Ubuntu clients open the same live workspace as the website. Several desktops and browsers share that server's accounts, matter permissions, review decisions, audit records and central evidence store.

The installer does not deploy a server, create a separate evidence database or provide offline synchronization. Deploy the server first using the server installation guide. A firm administrator supplies the website's HTTPS address and creates the required accounts and memberships.

## Install and connect

Download the installer for your operating system from the latest regular release and verify its SHA-256 against its matching `.sha256` file:

| Computer                                           | Installer                            | Installation and runtime                                                                                                                                                                                                                                                        |
| -------------------------------------------------- | ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Windows x64, Windows 10 or later                   | `CaseQuarry_<version>_x64-setup.exe` | Run the installer for the current user. Microsoft Edge WebView2 is required. If missing, the installer downloads Microsoft's bootstrapper and opens its prerequisite installation interface; review Microsoft's terms. This initial runtime installation needs internet access. |
| MacBook, Apple Silicon or Intel, macOS 11 or later | `CaseQuarry_<version>_universal.dmg` | Open the disk image and drag CaseQuarry into Applications. Both CPU architectures are included. The client uses the system's WKWebView.                                                                                                                                         |
| Ubuntu 24.04 x64 desktop                           | `CaseQuarry_<version>_amd64.deb`     | Run `sudo apt install ./CaseQuarry_<version>_amd64.deb`, then open CaseQuarry from the application menu. APT installs declared GTK/WebKit and certificate prerequisites from your configured system repositories.                                                               |

The DEB requires glibc 2.39 or later and WebKitGTK 4.1; Ubuntu 24.04 is the tested distribution target. Other Linux distributions, earlier Debian/Ubuntu versions, ARM Linux and an AppImage are not part of this release. A browser can connect from other supported desktop environments without installing the native client.

1. Deploy or obtain the firm's running HTTPS server.
2. Install the client for your computer using the table above.
3. Open CaseQuarry and enter the firm website origin, such as `https://cases.example.com`, without a sign-in path, query or token. The website must expose `/api/v1/setup` on the same origin.
4. Select **Connect to firm server**. The client checks TLS and the setup API before opening the workspace. Sign in with your existing account. An uninitialized server uses the existing setup flow; its administrator still needs the server's setup token.

The Windows installer is **unsigned**. The Mac application has an **ad-hoc signature**, not an Apple Developer ID signature or notarization; macOS may require explicit approval in Privacy & Security after the checksum is verified. No publisher certificate, SmartScreen reputation or Apple approval is claimed. Follow your firm's installation policy; the project does not require disabling system security protections. Automatic binary updates are not included: install a newer regular release to update the desktop. The live workspace follows the version deployed by the firm administrator.

## Microsoft runtime terms and privacy

The desktop installer does not embed Microsoft's bootstrapper or a fixed WebView2 runtime. Existing runtime installations are reused; a missing prerequisite is obtained directly from Microsoft's service. WebView2 is separately governed by Microsoft's terms and is not relicensed under CaseQuarry's Apache License. The installed third-party notices contain the Microsoft component disclosure and official links. [Microsoft download and license terms](https://developer.microsoft.com/en-us/microsoft-edge/webview2/), [runtime distribution documentation](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution).

WebView2 collects required and optional diagnostic information; Windows diagnostic settings govern optional collection. Microsoft Defender SmartScreen is enabled by default and can send security-related navigation or download information to Microsoft. CaseQuarry does not claim to disable those runtime mechanisms. Evergreen runtime updates are managed by Microsoft independently of CaseQuarry's release updates. Review [WebView2 data and privacy](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/data-privacy) and [Microsoft's Privacy Statement](https://privacy.microsoft.com/en-us/privacystatement) when deploying the client for confidential matters.

## Connection settings and sessions

Use **Connection → Firm connection…** or `Ctrl+Shift+C` (`Cmd+Shift+C` on Mac) to return to local settings. **Close workspace** returns to settings. Closing the connection window or choosing **Exit CaseQuarry** exits the application.

Choose **Interface language** on the connection screen to translate its controls
and native menus. This device preference is stored separately from the server
address and account sign-in. The opened workspace uses the signed-in account's
language setting. Both support all 13 [interface languages](LANGUAGES.md), including
Simplified Chinese, Traditional Chinese and Hindi. Typed connection details remain
intact when changing language.

The optional saved server address is encrypted for the current Windows account using Windows DPAPI, in the application configuration directory's `firm-connection.dpapi` file. **Forget saved server** deletes that preference; it does not revoke a server-side session. Sign out in the workspace when leaving an account. Native code does not read or store passwords, provider keys, session cookies or evidence. DPAPI does not protect against a compromise of the Windows account itself. [Microsoft DPAPI documentation](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata).

On Mac and Linux, the optional preference is URL-only JSON in `firm-connection.json`, with the application directory restricted to mode `0700` and the file to `0600` for the current account. It is not encrypted; native code verifies ownership and permissions and refuses symlinked or oversized preference files. Only the server URL and explicit loopback setting are saved on every platform. API keys, account passwords and evidence are never written into this preference.

The workspace requests the system WebView's private browsing mode. Exiting the application ends its browser session; server-side expiration, revocation and account controls still apply. Explicit original downloads and production deliveries use the existing authorized web workflows. There is no offline evidence workspace. System WebView updates and diagnostics follow the operating system's policies.

## HTTPS and local development

Firm connections require HTTPS, including servers on another computer or private network. Preflight uses the operating system's trusted certificate roots and never bypasses validation. Redirects are rejected: enter the final HTTPS origin supplied by the administrator.

For a server on the same computer, expand **Local development connection** and explicitly enable HTTP. Only literal loopback IP addresses are accepted, such as `http://127.0.0.1:3000` or `http://[::1]:3000`. HTTP hostnames, LAN addresses, URL credentials and reserved desktop IPC origins are rejected. The loopback API check bypasses system proxies so it connects locally.

## Desktop security boundary

The bundled connection screen has four native commands: read the protected preference, validate/connect to a server, forget the preference, and set the native menu language. Language updates accept only supported codes and bounded, nonempty menu labels without control characters. Every command checks the trusted window label and bundled asset origin as well as its Tauri capability. All commands are enrolled in the application permission manifest.

The remote workspace has **no native capabilities or remote IPC grants**. It cannot invoke settings commands or native filesystem, process, shell or plugin APIs. Navigation stays on the selected server's origin; pop-ups and navigation to other origins are blocked. Remote content uses the server's web policies. The local screen has a restricted Content Security Policy and loads no external scripts or fonts. [Tauri capabilities documentation](https://v2.tauri.app/security/capabilities/).

## Build from source

Install Node.js 24 and Rust, with `cargo` on the process's `PATH`. Desktop has an independent Cargo workspace and lockfile; evidence-core's server CI does not acquire desktop platform dependencies. Windows additionally needs Visual Studio C++ Build Tools and WebView2. Mac builds require Xcode Command Line Tools and both `aarch64-apple-darwin` and `x86_64-apple-darwin` Rust targets. Ubuntu builds require the system development packages listed in [Tauri's prerequisites](https://v2.tauri.app/start/prerequisites/).

```powershell
npm --prefix apps/desktop ci
npm --prefix apps/desktop run build:ui
cargo test --locked --manifest-path apps/desktop/src-tauri/Cargo.toml
npm --prefix apps/desktop run build:windows
```

Installer:

```text
apps/desktop/src-tauri/target/x86_64-pc-windows-msvc/release/bundle/nsis/CaseQuarry_<version>_x64-setup.exe
```

Executable: `apps/desktop/src-tauri/target/x86_64-pc-windows-msvc/release/casequarry-desktop.exe`.

On a Mac:

```sh
rustup target add aarch64-apple-darwin x86_64-apple-darwin
npm --prefix apps/desktop ci
npm --prefix apps/desktop run build:macos
```

On Ubuntu 24.04:

```sh
sudo apt-get update
sudo apt-get install --yes libwebkit2gtk-4.1-dev build-essential curl wget file libxdo-dev libssl-dev libayatana-appindicator3-dev librsvg2-dev
npm --prefix apps/desktop ci
npm --prefix apps/desktop run build:linux
```

Mac DMGs are written under `target/universal-apple-darwin/release/bundle/dmg/`; Linux DEBs under `target/x86_64-unknown-linux-gnu/release/bundle/deb/`, relative to `apps/desktop/src-tauri/`. Desktop CI tests native preferences and connection guards on each operating system, installs the Ubuntu DEB, and checks the same Universal DMG on Intel and Apple Silicon runners. The explicit `--diagnose-runtime` mode exercises the actual local system WebView and temporary URL-preference storage, never the user's saved preferences or a remote firm. Set `CASEQUARRY_DESKTOP_DIAGNOSTIC_REPORT` to a new absolute file path to capture the result. [Universal build pipeline](https://v2.tauri.app/distribute/pipelines/github/), [Mac ad-hoc signing](https://v2.tauri.app/distribute/sign/macos/), [Debian packaging](https://v2.tauri.app/distribute/debian/).

`npm --prefix apps/desktop run dev` rebuilds the bundled screen and runs the native development app; it does not start a firm server. Tracked icons are deterministic rasterizations of `apps/desktop/public/logo.svg` using the pinned Tauri CLI. NSIS and WebView2 packaging follow Tauri's Windows installer process. [Windows installer documentation](https://v2.tauri.app/distribute/windows-installer/).
