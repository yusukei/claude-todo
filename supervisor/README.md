# mcp-workspace-supervisor

Rust process supervisor for the mcp-todo Python agent. One supervisor
manages exactly one agent on the same host: spawn, restart on crash,
log capture, OS-level kill chain (Job Object on Windows, killpg on
POSIX), and a WebSocket control plane that speaks the
``supervisor_*`` envelope to the mcp-todo backend.

See the design doc in mcp-todo project documents:
**Rust Supervisor 設計書 v2** for the full spec.

## Build

```sh
cargo build --release
# Cross-targets (Windows host is the production target):
cargo build --release --target x86_64-pc-windows-msvc
```

## Run

```sh
mcp-workspace-supervisor --config %APPDATA%/mcp-workspace-supervisor/config.toml
```

See ``config.example.toml`` for the full config surface.

## Layout

| Module       | Responsibility |
|--------------|----------------|
| ``main.rs``  | clap CLI parse, tokio runtime, top-level ``run()`` |
| ``config.rs``| TOML config struct + validation + hot reload boundary |
| ``protocol.rs`` | envelope types (serde) — must stay in sync with the JSON schema in ``protocol/v1/`` (future) |
| ``backend.rs`` | WebSocket client to the backend supervisor endpoint, reconnect with jitter |
| ``process.rs`` | agent subprocess lifecycle on top of a Job Object (Windows) / process group (POSIX) |
| ``log_capture.rs`` | stdout/stderr ring buffer + bounded subscribers + token mask |
| ``handlers.rs`` | dispatch ``supervisor_*`` RPCs |
| ``upgrade.rs`` | download / verify (sha256) / fsync / atomic swap with rollback |
| ``platform.rs`` | OS-specific primitives (Job Object, signal handling) |
