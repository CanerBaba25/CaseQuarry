# CaseQuarry Desktop for Windows

CaseQuarry Desktop 0.3 is a Windows x64 connection client for a running CaseQuarry firm server. It opens the same live workspace as the website. Several desktops and browsers can share that server's accounts, matter permissions, review decisions, audit records and central evidence store.

The installer does not deploy a server, create a separate evidence database or provide offline synchronization. Deploy the server first using the server installation guide. A firm administrator supplies the website's HTTPS address and creates the required accounts and memberships.

## Install and connect

1. Download `CaseQuarry_0.3.0_x64-setup.exe` from the GitHub release and verify its SHA-256 against the release checksums.
2. Run the installer. It installs for the current Windows user. Microsoft Edge WebView2 is required; the bundled Microsoft bootstrapper downloads the runtime if missing. That first runtime installation requires internet access. Windows 10 or later is the supported baseline.
3. Open CaseQuarry and enter the firm website origin, such as `https://cases.example.com`, without a sign-in path, query or token. The website must expose `/api/v1/setup` on the same origin.
4. Select **Connect to firm server**. The client checks TLS and the setup API before opening the workspace. Sign in with your existing account. An uninitialized server uses the existing setup flow; its administrator still needs the server's setup token.

The release installer and application are **unsigned**. No publisher certificate, signing identity or SmartScreen reputation is claimed. Automatic binary updates are not included: install a newer GitHub release to update the desktop. The live workspace follows the version deployed by the firm administrator.

## Connection settings and sessions

Use **Connection → Firm connection…** or `Ctrl+Shift+C` to return to local settings. **Close workspace** returns to settings. Closing the connection window or choosing **Exit CaseQuarry** exits the application.

The optional saved server address is encrypted for the current Windows account using Windows DPAPI, in the application configuration directory's `firm-connection.dpapi` file. **Forget saved server** deletes that preference; it does not revoke a server-side session. Sign out in the workspace when leaving an account. Native code does not read or store passwords, provider keys, session cookies or evidence. DPAPI does not protect against a compromise of the Windows account itself. [Microsoft DPAPI documentation](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata).

The workspace uses an in-private WebView2 profile. Exiting the application ends its browser session; server-side expiration, revocation and account controls still apply. Explicit original downloads and production deliveries use the existing authorized web workflows. There is no offline evidence workspace.

## HTTPS and local development

Firm connections require HTTPS, including servers on another computer or private network. Preflight uses the operating system's trusted certificate roots and never bypasses validation. Redirects are rejected: enter the final HTTPS origin supplied by the administrator.

For a server on the same computer, expand **Local development connection** and explicitly enable HTTP. Only literal loopback IP addresses are accepted, such as `http://127.0.0.1:3000` or `http://[::1]:3000`. HTTP hostnames, LAN addresses, URL credentials and reserved desktop IPC origins are rejected. The loopback API check bypasses system proxies so it connects locally.

## Desktop security boundary

The bundled connection screen has three native commands: read the protected preference, validate/connect to a server, and forget the preference. Every command checks the trusted window label and bundled asset origin as well as its Tauri capability. All commands are enrolled in the application permission manifest.

The remote workspace has **no native capabilities or remote IPC grants**. It cannot invoke settings commands or native filesystem, process, shell or plugin APIs. Navigation stays on the selected server's origin; pop-ups and navigation to other origins are blocked. Remote content uses the server's web policies. The local screen has a restricted Content Security Policy and loads no external scripts or fonts. [Tauri capabilities documentation](https://v2.tauri.app/security/capabilities/).

## Build from source

On Windows, install Node.js 24, Rust with `x86_64-pc-windows-msvc`, Visual Studio C++ Build Tools and WebView2. Ensure `cargo` is on the process's `PATH`. Desktop has an independent Cargo workspace and lockfile; evidence-core's server CI does not acquire desktop platform dependencies.

```powershell
npm --prefix apps/desktop ci
npm --prefix apps/desktop run build:ui
cargo test --locked --manifest-path apps/desktop/src-tauri/Cargo.toml
npm --prefix apps/desktop run build
```

Installer:

```text
apps/desktop/src-tauri/target/x86_64-pc-windows-msvc/release/bundle/nsis/CaseQuarry_0.3.0_x64-setup.exe
```

Executable: `apps/desktop/src-tauri/target/x86_64-pc-windows-msvc/release/casequarry-desktop.exe`.

`npm --prefix apps/desktop run dev` rebuilds the bundled screen and runs the native development app; it does not start a firm server. Tracked icons are deterministic rasterizations of `apps/desktop/public/logo.svg` using the pinned Tauri CLI. NSIS and WebView2 packaging follow Tauri's Windows installer process. [Windows installer documentation](https://v2.tauri.app/distribute/windows-installer/).
