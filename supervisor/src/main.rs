//! Entry point for ``mcp-workspace-supervisor``.
//!
//! Day 3 wires the runtime end-to-end: parse args, load + validate
//! config, set up tracing, build the multi-thread tokio runtime,
//! launch ``AgentManager::run_supervised`` and ``WsClient::run`` as
//! sibling tasks, and wait for Ctrl-C to drive a graceful shutdown
//! of the agent (which in turn closes the WS by dropping the runtime
//! when ``main`` returns).

use std::path::PathBuf;
use std::process::ExitCode;
use std::sync::Arc;

use anyhow::{Context, Result};
use clap::Parser;
use parking_lot::RwLock;
use sha2::{Digest, Sha256};
use tracing::{error, info, warn};

mod backend;
mod config;
mod handlers;
mod log_capture;
#[cfg(not(windows))]
mod platform_posix;
#[cfg(windows)]
mod platform_windows;
mod process;
mod protocol;

#[derive(Debug, Parser)]
#[command(name = "mcp-workspace-supervisor", version, about)]
struct Cli {
    /// Path to the TOML config file.
    #[arg(long)]
    config: PathBuf,
}

fn main() -> ExitCode {
    if let Err(e) = run() {
        eprintln!("supervisor: fatal: {e:#}");
        return ExitCode::from(1);
    }
    ExitCode::SUCCESS
}

fn run() -> Result<()> {
    init_tracing();

    let cli = Cli::parse();
    let cfg = config::Config::load(&cli.config)
        .with_context(|| format!("failed to load {}", cli.config.display()))?;
    info!(
        backend = %cfg.backend.url,
        agent_cwd = %cfg.agent.cwd.display(),
        "config loaded"
    );

    let runtime = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .thread_name("supervisor-rt")
        .build()
        .context("build tokio runtime")?;

    runtime.block_on(async_main(cli.config, cfg))
}

async fn async_main(config_path: PathBuf, cfg: config::Config) -> Result<()> {
    let agent_cmd = process::AgentCommand::from_config(&cfg.agent);
    let restart_cfg = cfg.restart.clone();
    let log_cfg = cfg.log.clone();

    // Shared mutable config — handlers::Dispatcher can hot-reload it
    // for fields that don't require a restart (spec §8.2).
    let shared_cfg: Arc<RwLock<config::Config>> = Arc::new(RwLock::new(cfg));

    let ring = log_capture::LogRing::new(
        log_cfg.ring_capacity,
        log_cfg.max_line_bytes,
        log_cfg.subscriber_channel_capacity,
    );

    let agent = Arc::new(
        process::AgentManager::new(
            agent_cmd,
            restart_cfg,
            ring,
            // Day 3 keeps the no-op shutdown hook; the real WS-backed
            // hook (sending a ``shutdown`` RPC to the agent over its
            // own WS) requires backend cooperation and lands in Day 4.
            Arc::new(process::NoShutdownHook),
        )
        .context("build AgentManager")?,
    );

    let host_id = compute_host_id();
    let hostname = read_hostname();
    info!(host_id, hostname, "host identity computed");

    let ws_client = Arc::new(backend::WsClient::new(
        shared_cfg.clone(),
        config_path,
        agent.clone(),
        host_id,
        hostname,
    ));

    // Sibling tasks. ``run_supervised`` returns Ok(()) once it has
    // observed ``stop()``; ``ws_client.run()`` runs forever (we abort
    // it on shutdown).
    let agent_task = tokio::spawn({
        let agent = agent.clone();
        async move { agent.run_supervised().await }
    });
    let ws_task = tokio::spawn(ws_client.run());

    // Block on Ctrl-C (or SIGTERM via the same handler on Unix).
    if let Err(e) = tokio::signal::ctrl_c().await {
        warn!(error = %e, "ctrl-c handler failed; shutting down anyway");
    }
    info!("shutdown signal received; stopping agent");
    agent.stop();

    // Give the agent loop a moment to perform graceful_kill and exit.
    let agent_join = tokio::time::timeout(
        std::time::Duration::from_secs(15),
        agent_task,
    )
    .await;
    match agent_join {
        Ok(Ok(Ok(()))) => info!("agent task exited cleanly"),
        Ok(Ok(Err(e))) => warn!(error = %e, "agent task returned error"),
        Ok(Err(e)) => warn!(error = %e, "agent task panicked"),
        Err(_) => warn!("agent task did not exit within 15s"),
    }

    // Tear down the WS task last so it can flush pending pushes.
    ws_task.abort();
    let _ = ws_task.await;

    Ok(())
}

fn init_tracing() {
    let env_filter = tracing_subscriber::EnvFilter::try_from_default_env()
        .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info"));
    if let Err(e) = tracing_subscriber::fmt()
        .with_env_filter(env_filter)
        .with_target(false)
        .try_init()
    {
        let _ = e;
        error!("tracing was already initialised; continuing");
    }
}

fn read_hostname() -> String {
    std::env::var("COMPUTERNAME")
        .or_else(|_| std::env::var("HOSTNAME"))
        .or_else(|_| std::env::var("HOST"))
        .unwrap_or_else(|_| "unknown".to_string())
}

/// Stable-per-machine identifier derived from the hostname. The spec
/// (§3.1, §2.2) only requires that backend can correlate the
/// supervisor + agent on the same host; a sha256-hashed hostname is
/// enough for the 1:1 single-host deployment, and it doesn't leak
/// the hostname in plaintext over the wire.
fn compute_host_id() -> String {
    let hostname = read_hostname();
    let mut hasher = Sha256::new();
    hasher.update(hostname.as_bytes());
    let digest = hasher.finalize();
    digest.iter().take(16).map(|b| format!("{b:02x}")).collect()
}
