//! TOML-backed configuration with validation.
//!
//! The shape mirrors ``supervisor/config.example.toml``. Hot reload
//! is implemented at a higher layer (``backend.rs``); this module is
//! pure parsing + validation. Loading never panics on missing
//! optional fields — defaults are explicit so ``cargo build`` of a
//! brand-new install works without hand-editing every key.

use std::path::{Path, PathBuf};

use anyhow::{anyhow, Context, Result};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Config {
    pub backend: BackendConfig,
    pub agent: AgentConfig,
    #[serde(default)]
    pub log: LogConfig,
    #[serde(default)]
    pub restart: RestartConfig,
    #[serde(default)]
    pub supervisor_log: SupervisorLogConfig,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct BackendConfig {
    pub url: String,
    pub token: String,
    #[serde(default = "default_heartbeat_interval_s")]
    pub heartbeat_interval_s: u32,
}

fn default_heartbeat_interval_s() -> u32 {
    30
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct AgentConfig {
    pub mode: AgentMode,
    pub cwd: PathBuf,
    pub url: String,
    pub token: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "kebab-case")]
pub enum AgentMode {
    /// ``uv run python main.py --url <url> --token <token>`` from ``cwd``.
    UvRun,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct LogConfig {
    pub ring_capacity: usize,
    pub file_path: String,
    pub max_line_bytes: usize,
    pub subscriber_channel_capacity: usize,
}

impl Default for LogConfig {
    fn default() -> Self {
        Self {
            ring_capacity: 10_000,
            file_path: String::new(),
            max_line_bytes: 4096,
            subscriber_channel_capacity: 256,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct RestartConfig {
    pub backoff_initial_ms: u64,
    pub backoff_max_ms: u64,
    pub backoff_jitter_pct: u8,
    pub graceful_timeout_ms: u64,
}

impl Default for RestartConfig {
    fn default() -> Self {
        Self {
            backoff_initial_ms: 1_000,
            backoff_max_ms: 32_000,
            backoff_jitter_pct: 20,
            graceful_timeout_ms: 5_000,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct SupervisorLogConfig {
    pub dir: String,
    pub rotation_size_mb: u32,
    pub rotation_keep: u32,
}

impl Default for SupervisorLogConfig {
    fn default() -> Self {
        Self {
            dir: String::new(),
            rotation_size_mb: 10,
            rotation_keep: 5,
        }
    }
}

impl Config {
    pub fn load(path: &Path) -> Result<Self> {
        let raw = std::fs::read_to_string(path)
            .with_context(|| format!("failed to read config file at {}", path.display()))?;
        let cfg: Self = toml::from_str(&raw)
            .with_context(|| format!("failed to parse TOML at {}", path.display()))?;
        cfg.validate()?;
        Ok(cfg)
    }

    pub fn validate(&self) -> Result<()> {
        // Tokens & URLs.
        if !self.backend.token.starts_with("sv_") {
            return Err(anyhow!(
                "backend.token must start with 'sv_' (got {:?})",
                redact(&self.backend.token)
            ));
        }
        if !self.agent.token.starts_with("ta_") {
            return Err(anyhow!(
                "agent.token must start with 'ta_' (got {:?})",
                redact(&self.agent.token)
            ));
        }
        for (label, url) in [("backend.url", &self.backend.url), ("agent.url", &self.agent.url)] {
            let parsed = url::Url::parse(url)
                .with_context(|| format!("{label} is not a valid URL: {url}"))?;
            match parsed.scheme() {
                "ws" | "wss" => {}
                other => {
                    return Err(anyhow!("{label} must be ws:// or wss:// (got {other})"));
                }
            }
        }

        // Agent cwd must exist (validating early gives a nicer error than
        // ``CreateProcess`` returning a cryptic ERROR_FILE_NOT_FOUND).
        if !self.agent.cwd.is_dir() {
            return Err(anyhow!(
                "agent.cwd is not a directory: {}",
                self.agent.cwd.display()
            ));
        }

        // Numeric guards.
        if self.log.ring_capacity == 0 {
            return Err(anyhow!("log.ring_capacity must be > 0"));
        }
        if self.log.max_line_bytes < 64 {
            return Err(anyhow!("log.max_line_bytes must be >= 64"));
        }
        if self.log.subscriber_channel_capacity == 0 {
            return Err(anyhow!("log.subscriber_channel_capacity must be > 0"));
        }
        if self.restart.backoff_initial_ms == 0
            || self.restart.backoff_max_ms < self.restart.backoff_initial_ms
        {
            return Err(anyhow!(
                "restart.backoff_initial_ms must be > 0 and <= backoff_max_ms"
            ));
        }
        if self.restart.backoff_jitter_pct > 100 {
            return Err(anyhow!("restart.backoff_jitter_pct must be in 0..=100"));
        }
        if self.backend.heartbeat_interval_s == 0 {
            return Err(anyhow!("backend.heartbeat_interval_s must be > 0"));
        }
        Ok(())
    }
}

/// Mask a token for logs / error messages — keep just the prefix.
pub(crate) fn redact(token: &str) -> String {
    if token.len() <= 4 {
        return "<short>".to_string();
    }
    format!("{}...", &token[..token.len().min(4)])
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tempfile::TempDir;

    fn write_config(dir: &TempDir, body: &str) -> PathBuf {
        let p = dir.path().join("config.toml");
        let mut f = std::fs::File::create(&p).unwrap();
        f.write_all(body.as_bytes()).unwrap();
        p
    }

    #[test]
    fn parses_minimal_config() {
        let tmp = TempDir::new().unwrap();
        let agent_cwd = tmp.path().join("agent");
        std::fs::create_dir(&agent_cwd).unwrap();
        let p = write_config(
            &tmp,
            &format!(
                r#"
[backend]
url = "wss://example.com/sup/ws"
token = "sv_aabbccdd"

[agent]
mode = "uv-run"
cwd = "{}"
url = "wss://example.com/agent/ws"
token = "ta_eeff0011"
"#,
                agent_cwd.display().to_string().replace('\\', "/"),
            ),
        );
        let cfg = Config::load(&p).expect("load config");
        assert_eq!(cfg.backend.url, "wss://example.com/sup/ws");
        assert_eq!(cfg.backend.heartbeat_interval_s, 30);
        assert_eq!(cfg.log.ring_capacity, 10_000);
        assert!(matches!(cfg.agent.mode, AgentMode::UvRun));
    }

    #[test]
    fn rejects_wrong_token_prefix() {
        let tmp = TempDir::new().unwrap();
        let agent_cwd = tmp.path().join("agent");
        std::fs::create_dir(&agent_cwd).unwrap();
        let p = write_config(
            &tmp,
            &format!(
                r#"
[backend]
url = "wss://example.com/sup/ws"
token = "wrong_prefix"

[agent]
mode = "uv-run"
cwd = "{}"
url = "wss://example.com/agent/ws"
token = "ta_xx"
"#,
                agent_cwd.display().to_string().replace('\\', "/"),
            ),
        );
        let err = Config::load(&p).unwrap_err();
        assert!(err.to_string().contains("backend.token must start with 'sv_'"));
    }

    #[test]
    fn rejects_missing_agent_cwd() {
        let tmp = TempDir::new().unwrap();
        let p = write_config(
            &tmp,
            r#"
[backend]
url = "wss://example.com/sup/ws"
token = "sv_aa"

[agent]
mode = "uv-run"
cwd = "/definitely/does/not/exist/abcxyz"
url = "wss://example.com/agent/ws"
token = "ta_bb"
"#,
        );
        let err = Config::load(&p).unwrap_err();
        assert!(err.to_string().contains("agent.cwd is not a directory"));
    }

    #[test]
    fn rejects_non_ws_scheme() {
        let tmp = TempDir::new().unwrap();
        let agent_cwd = tmp.path().join("agent");
        std::fs::create_dir(&agent_cwd).unwrap();
        let p = write_config(
            &tmp,
            &format!(
                r#"
[backend]
url = "https://example.com/sup/ws"
token = "sv_aa"

[agent]
mode = "uv-run"
cwd = "{}"
url = "wss://example.com/agent/ws"
token = "ta_bb"
"#,
                agent_cwd.display().to_string().replace('\\', "/"),
            ),
        );
        let err = Config::load(&p).unwrap_err();
        assert!(err.to_string().contains("backend.url must be ws://"));
    }
}
