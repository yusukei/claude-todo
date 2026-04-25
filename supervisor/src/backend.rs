//! WebSocket client to the backend control plane.
//!
//! Owns the long-lived connection to ``/api/v1/workspaces/supervisor/ws``
//! and runs it under a reconnect loop with exponential backoff
//! (1s -> 32s) plus ±20% jitter (mitigates spec risk R16).
//!
//! Each connection cycle:
//!   1. ``connect_async`` over rustls.
//!   2. Send the auth frame ``{type, token, host_id}``; wait for
//!      ``auth_ok`` (10s timeout).
//!   3. Push the initial ``supervisor_info``.
//!   4. Spawn a heartbeat task (``Ping`` every
//!      ``backend.heartbeat_interval_s``, default 30s — Cloudflare
//!      Tunnel idles connections at 100s).
//!   5. Loop: read frames -> dispatch via ``handlers::Dispatcher``
//!      (one tokio task per RPC, tracked in ``JoinSet``); drain the
//!      outbound mpsc -> write to socket.
//!   6. On disconnect: abort the heartbeat task, ``abort_all`` the
//!      in-flight RPC tasks (spec §6.5: "in-flight RPC を全て abort
//!      + error response"), close the socket, sleep with jitter,
//!      try again.

use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use anyhow::{anyhow, bail, Context, Result};
use futures_util::{SinkExt, StreamExt};
use parking_lot::RwLock;
use rand::Rng;
use serde_json::Value;
use tokio::sync::mpsc;
use tokio::task::JoinSet;
use tokio::time::{sleep, timeout};
use tokio_tungstenite::{connect_async, tungstenite::Message};
use tracing::{info, warn};

use crate::config::Config;
use crate::handlers::Dispatcher;
use crate::process::AgentManager;
use crate::protocol::{kind, AuthFrame, AuthKind, Envelope, SupervisorInfo};

const RECONNECT_INITIAL_MS: u64 = 1_000;
const RECONNECT_MAX_MS: u64 = 32_000;
const RECONNECT_JITTER_PCT: f64 = 0.20;
const AUTH_OK_TIMEOUT: Duration = Duration::from_secs(10);
const OUT_CHANNEL_CAPACITY: usize = 64;

pub struct WsClient {
    config: Arc<RwLock<Config>>,
    config_path: PathBuf,
    agent: Arc<AgentManager>,
    host_id: String,
    hostname: String,
    supervisor_version: &'static str,
}

impl WsClient {
    pub fn new(
        config: Arc<RwLock<Config>>,
        config_path: PathBuf,
        agent: Arc<AgentManager>,
        host_id: String,
        hostname: String,
    ) -> Self {
        Self {
            config,
            config_path,
            agent,
            host_id,
            hostname,
            supervisor_version: env!("CARGO_PKG_VERSION"),
        }
    }

    /// Run forever: connect, serve, reconnect on disconnect.
    pub async fn run(self: Arc<Self>) -> Result<()> {
        let mut backoff_ms = RECONNECT_INITIAL_MS;
        loop {
            match self.connect_and_serve().await {
                Ok(()) => {
                    info!("ws disconnected cleanly; reconnecting");
                    backoff_ms = RECONNECT_INITIAL_MS;
                }
                Err(e) => {
                    warn!(error = %format!("{e:#}"), backoff_ms, "ws error; reconnecting");
                }
            }
            sleep_with_jitter(backoff_ms).await;
            backoff_ms = backoff_ms.saturating_mul(2).min(RECONNECT_MAX_MS);
        }
    }

    async fn connect_and_serve(&self) -> Result<()> {
        let (url, token, heartbeat_s) = {
            let cfg = self.config.read();
            (
                cfg.backend.url.clone(),
                cfg.backend.token.clone(),
                cfg.backend.heartbeat_interval_s as u64,
            )
        };

        info!(%url, "connecting to backend");
        let (ws_stream, _) = connect_async(&url).await.context("ws connect failed")?;
        let (mut write, mut read) = ws_stream.split();

        // Auth handshake.
        let auth_frame = AuthFrame {
            kind: AuthKind::Auth,
            token: token.clone(),
            host_id: self.host_id.clone(),
        };
        let auth_json = serde_json::to_string(&auth_frame).context("serialize auth")?;
        write
            .send(Message::Text(auth_json.into()))
            .await
            .context("send auth")?;

        match timeout(AUTH_OK_TIMEOUT, read.next()).await {
            Ok(Some(Ok(Message::Text(s)))) => {
                let v: Value = serde_json::from_str(s.as_str())
                    .context("parse auth response")?;
                if v["type"].as_str() != Some(kind::AUTH_OK) {
                    bail!("expected auth_ok, got {:?}", v["type"]);
                }
            }
            Ok(Some(Ok(other))) => bail!("expected text auth_ok, got {:?}", other),
            Ok(Some(Err(e))) => bail!("ws read during auth: {e}"),
            Ok(None) => bail!("ws closed before auth_ok"),
            Err(_) => bail!("auth_ok timeout"),
        }
        info!("auth_ok received");

        // Outbound channel — drained inside the main select! loop.
        let (out_tx, mut out_rx) = mpsc::channel::<Message>(OUT_CHANNEL_CAPACITY);

        // Initial supervisor_info push.
        let info = self.build_supervisor_info();
        let info_env = Envelope {
            kind: kind::SUPERVISOR_INFO.to_string(),
            request_id: None,
            payload: info,
        };
        let info_json = serde_json::to_string(&info_env).context("serialize info")?;
        out_tx
            .send(Message::Text(info_json.into()))
            .await
            .ok();

        // RPC dispatcher; the per-connection mpsc is its outbound side.
        let dispatcher = Arc::new(Dispatcher::new(
            self.agent.clone(),
            out_tx.clone(),
            self.config.clone(),
            self.config_path.clone(),
        ));

        // Heartbeat task — Ping frames keep the CF Tunnel alive.
        let hb_tx = out_tx.clone();
        let hb_handle = tokio::spawn(async move {
            let mut iv = tokio::time::interval(Duration::from_secs(heartbeat_s));
            iv.tick().await; // skip the immediate-fire first tick
            loop {
                iv.tick().await;
                if hb_tx
                    .send(Message::Ping(Vec::<u8>::new().into()))
                    .await
                    .is_err()
                {
                    break;
                }
            }
        });

        // In-flight handlers — abort_all on disconnect (spec §6.5).
        let mut in_flight: JoinSet<()> = JoinSet::new();

        let result: Result<()> = loop {
            tokio::select! {
                msg = read.next() => {
                    match msg {
                        Some(Ok(Message::Text(s))) => {
                            let env: Envelope<Value> = match serde_json::from_str(s.as_str()) {
                                Ok(e) => e,
                                Err(e) => {
                                    warn!(error = %e, "bad envelope; ignoring");
                                    continue;
                                }
                            };
                            let dispatcher = dispatcher.clone();
                            in_flight.spawn(async move {
                                dispatcher.dispatch(env).await;
                            });
                        }
                        Some(Ok(Message::Ping(p))) => {
                            let _ = out_tx.send(Message::Pong(p)).await;
                        }
                        Some(Ok(Message::Pong(_))) => {}
                        Some(Ok(Message::Close(_))) => break Ok(()),
                        Some(Ok(_)) => {}
                        Some(Err(e)) => break Err(anyhow!("ws read: {e}")),
                        None => break Ok(()),
                    }
                }
                Some(out_msg) = out_rx.recv() => {
                    if let Err(e) = write.send(out_msg).await {
                        break Err(anyhow!("ws write: {e}"));
                    }
                }
                else => break Ok(()),
            }
        };

        // Cleanup. ``abort_all`` is best-effort; the in-flight tasks
        // were holding ``out_tx`` clones, which are about to be
        // dropped along with this scope — any handler that hadn't
        // already sent its response will silently drop it.
        hb_handle.abort();
        in_flight.abort_all();
        let _ = write.close().await;
        result
    }

    fn build_supervisor_info(&self) -> SupervisorInfo {
        let snap = self.agent.status();
        let agent_uptime_s = snap.started_at.map(|s| {
            let now = chrono::Utc::now();
            (now - s).num_seconds().max(0) as u64
        });
        SupervisorInfo {
            hostname: self.hostname.clone(),
            host_id: self.host_id.clone(),
            os: std::env::consts::OS.to_string(),
            supervisor_version: self.supervisor_version.to_string(),
            agent_version: None,
            agent_pid: snap.pid,
            agent_uptime_s,
        }
    }
}

async fn sleep_with_jitter(ms: u64) {
    let factor = rand::thread_rng().gen_range(-RECONNECT_JITTER_PCT..=RECONNECT_JITTER_PCT);
    let wait = ((ms as f64) * (1.0 + factor)).max(0.0) as u64;
    sleep(Duration::from_millis(wait)).await;
}
