use serde::{Deserialize, Serialize};
use std::{net::IpAddr, time::Duration};
use url::{Host, Url};

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
pub struct Connection {
    pub server_url: String,
    pub allow_loopback_http: bool,
}

impl Connection {
    pub fn validate(input: &str, allow_loopback_http: bool) -> Result<Self, String> {
        let value = input.trim();
        if value.is_empty()
            || value.len() > 2048
            || value
                .chars()
                .any(|c| c.is_control() || c == '\\' || c == ' ')
        {
            return Err("Enter the firm's HTTPS website address.".into());
        }
        let (_, remainder) = value
            .split_once("://")
            .ok_or("Enter an HTTPS origin starting with https://.")?;
        let authority = remainder.split('/').next().unwrap_or("");
        let mut url = Url::parse(value).map_err(|_| "Enter a valid HTTPS website address.")?;
        if authority.contains('@') || !url.username().is_empty() || url.password().is_some() {
            return Err(
                "The server address must not include a username, password or token.".into(),
            );
        }
        if url.query().is_some() || url.fragment().is_some() || url.path() != "/" {
            return Err("Enter only the website origin, for example https://cases.example.com, without a path or token.".into());
        }
        let host = url
            .host()
            .ok_or("The server address must include a hostname.")?;
        let loopback = match host {
            Host::Ipv4(ip) => IpAddr::V4(ip).is_loopback(),
            Host::Ipv6(ip) => IpAddr::V6(ip).is_loopback(),
            Host::Domain(name) => {
                let reserved = name.trim_end_matches('.').to_ascii_lowercase();
                if reserved == "tauri.localhost"
                    || reserved.ends_with(".tauri.localhost")
                    || reserved == "ipc.localhost"
                    || reserved.ends_with(".ipc.localhost")
                {
                    return Err("This hostname is reserved by the desktop client. Use your firm's server address.".into());
                }
                false
            }
        };
        if url.scheme() != "https" && !(url.scheme() == "http" && loopback && allow_loopback_http) {
            return Err("HTTPS is required. Local development HTTP must be explicitly enabled and use 127.0.0.1 or [::1].".into());
        }
        url.set_path("/");
        Ok(Self {
            server_url: url.to_string(),
            allow_loopback_http: url.scheme() == "http",
        })
    }

    pub fn url(&self) -> Result<Url, String> {
        Url::parse(&self.server_url).map_err(|_| {
            "The saved server address is invalid. Forget it and enter the address again.".into()
        })
    }
}

pub async fn probe_server(connection: &Connection) -> Result<bool, String> {
    let verified = Connection::validate(&connection.server_url, connection.allow_loopback_http)?;
    let endpoint = verified
        .url()?
        .join("api/v1/setup")
        .map_err(|_| "The server address is invalid.")?;
    let mut client_builder = reqwest::Client::builder()
        .timeout(Duration::from_secs(12))
        .connect_timeout(Duration::from_secs(8))
        .redirect(reqwest::redirect::Policy::none())
        .user_agent(concat!("CaseQuarryDesktop/", env!("CARGO_PKG_VERSION")));
    if verified.allow_loopback_http {
        client_builder = client_builder.no_proxy();
    }
    let client = client_builder
        .build()
        .map_err(|_| "The secure connection could not be initialized.")?;
    let mut response = client.get(endpoint).send().await.map_err(|_| {
        "Cannot reach the firm server. Check the address, network connection and HTTPS certificate. No certificate checks are bypassed."
    })?;
    if response.status().is_redirection() {
        return Err("The server redirects to another address. Enter the final HTTPS website origin supplied by your administrator.".into());
    }
    if !response.status().is_success() {
        return Err(format!(
            "The server returned HTTP {}. Confirm the CaseQuarry website address with your administrator.",
            response.status().as_u16()
        ));
    }
    if response
        .content_length()
        .is_some_and(|length| length > 4096)
    {
        return Err("The server did not return a supported CaseQuarry connection response.".into());
    }
    let mut body = Vec::new();
    while let Some(chunk) = response
        .chunk()
        .await
        .map_err(|_| "The server connection was interrupted.")?
    {
        if body.len() + chunk.len() > 4096 {
            return Err("The server connection response is too large.".into());
        }
        body.extend_from_slice(&chunk);
    }
    #[derive(Deserialize)]
    struct Setup {
        required: bool,
    }
    let setup: Setup = serde_json::from_slice(&body).map_err(|_| {
        "This address did not return the CaseQuarry setup API. Use the firm's website origin, with /api available on that same origin."
    })?;
    Ok(setup.required)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        io::{Read, Write},
        net::TcpListener,
    };

    #[test]
    fn accepts_https_origins_and_normalizes_default_port() {
        assert_eq!(
            Connection::validate(" https://CASES.example.com:443/ ", false)
                .unwrap()
                .server_url,
            "https://cases.example.com/"
        );
        assert!(
            !Connection::validate("https://cases.example.com", true)
                .unwrap()
                .allow_loopback_http
        );
    }

    #[test]
    fn http_requires_explicit_literal_loopback() {
        for address in ["http://127.0.0.1:3000", "http://[::1]:3000"] {
            assert!(Connection::validate(address, true).is_ok());
            assert!(Connection::validate(address, false).is_err());
        }
        for address in [
            "http://localhost:3000",
            "http://cases.example.com",
            "http://192.168.1.2",
            "http://0.0.0.0",
        ] {
            assert!(Connection::validate(address, true).is_err());
        }
    }

    #[test]
    fn rejects_credentials_paths_queries_and_reserved_origins() {
        for address in [
            "https://user:secret@cases.example.com",
            "https://@cases.example.com",
            "https://cases.example.com/login",
            "https://cases.example.com?token=secret",
            "https://cases.example.com/#token",
            "https://tauri.localhost",
            "https://IPC.localhost",
            "https://a.tauri.localhost.",
            "file:///C:/Windows",
            "javascript:alert(1)",
            "https://cases.example.com\\evil",
            "https://ca\nses.example.com",
            "https:/cases.example.com",
        ] {
            assert!(
                Connection::validate(address, true).is_err(),
                "unsafe address was accepted"
            );
        }
    }

    fn endpoint(
        status: &str,
        headers: &str,
        body: &str,
    ) -> (Connection, std::thread::JoinHandle<()>) {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let connection =
            Connection::validate(&format!("http://{}", listener.local_addr().unwrap()), true)
                .unwrap();
        let response = format!(
            "HTTP/1.1 {status}\r\nContent-Length: {}\r\n{headers}Connection: close\r\n\r\n{body}",
            body.len()
        );
        let worker = std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            stream
                .set_read_timeout(Some(Duration::from_secs(5)))
                .unwrap();
            let mut request = [0; 2048];
            let read = stream.read(&mut request).unwrap();
            assert!(String::from_utf8_lossy(&request[..read]).starts_with("GET /api/v1/setup "));
            stream.write_all(response.as_bytes()).unwrap();
        });
        (connection, worker)
    }

    #[test]
    fn probes_actual_http_setup_response() {
        let (connection, worker) = endpoint(
            "200 OK",
            "Content-Type: application/json\r\n",
            r#"{"required":true}"#,
        );
        assert!(tauri::async_runtime::block_on(probe_server(&connection)).unwrap());
        worker.join().unwrap();
    }

    #[test]
    fn refuses_redirect_and_foreign_or_oversized_payload() {
        for (status, headers, body) in [
            ("302 Found", "Location: https://other.example.com/\r\n", ""),
            ("200 OK", "", "<html>Other service</html>"),
            ("200 OK", "", &"x".repeat(4097)),
        ] {
            let (connection, worker) = endpoint(status, headers, body);
            assert!(tauri::async_runtime::block_on(probe_server(&connection)).is_err());
            worker.join().unwrap();
        }
    }
}
