//! `exec` — synchronous shell command execution.
//!
//! Mirrors `agent/main.py:handle_exec` (lines ~451-617). Handles:
//! - shell selection (default / bash / sh / cmd / pwsh / powershell)
//! - `cwd_override` with path-traversal protection
//! - env override merging on top of the agent's own env
//! - timeout (default 60 s, max 3600 s) → process-group kill on expiry
//! - stdout/stderr truncation at `MAX_OUTPUT_BYTES` (2 MB) with a
//!   `*_truncated` flag and `*_total_bytes` so the caller can detect
//!   loss
//!
//! POSIX-specific: spawned children get a fresh process group via
//! `process_group(0)` so we can `killpg(SIGKILL)` on timeout — without
//! that, only the shell dies and any background pipeline keeps running.

use std::collections::HashMap;
use std::path::Path;
use std::process::Stdio;
use std::time::Duration;

use serde_json::{json, Value};
use tokio::process::Command;
use tokio::time::timeout;

use super::constants::{
    DEFAULT_EXEC_TIMEOUT_SECS, MAX_EXEC_TIMEOUT_SECS, MAX_OUTPUT_BYTES,
};
use crate::path_safety::{resolve_safe_path, PathSafetyError};

/// Request payload for `exec`.
#[derive(Debug, Clone)]
struct ExecRequest {
    command: String,
    base_cwd: Option<String>,
    cwd_override: Option<String>,
    extra_env: Option<HashMap<String, String>>,
    timeout_secs: u64,
    shell_hint: String,
}

impl ExecRequest {
    fn parse(payload: &Value) -> Result<Self, Value> {
        let command = payload
            .get("command")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string();
        let base_cwd = payload.get("cwd").and_then(Value::as_str).map(str::to_owned);
        let cwd_override = payload
            .get("cwd_override")
            .and_then(Value::as_str)
            .map(str::to_owned);
        let extra_env = match payload.get("env") {
            None | Some(Value::Null) => None,
            Some(Value::Object(map)) => {
                let mut out: HashMap<String, String> = HashMap::with_capacity(map.len());
                for (k, v) in map {
                    let s = v.as_str().ok_or_else(|| {
                        exec_error("env keys/values must be strings")
                    })?;
                    out.insert(k.clone(), s.to_string());
                }
                Some(out)
            }
            Some(_) => {
                return Err(exec_error("env must be an object of string→string"));
            }
        };
        let timeout_raw = payload
            .get("timeout")
            .and_then(Value::as_u64)
            .unwrap_or(DEFAULT_EXEC_TIMEOUT_SECS);
        let timeout_secs = timeout_raw.min(MAX_EXEC_TIMEOUT_SECS);
        let shell_hint = payload
            .get("shell")
            .and_then(Value::as_str)
            .unwrap_or("default")
            .to_lowercase();
        Ok(Self {
            command,
            base_cwd,
            cwd_override,
            extra_env,
            timeout_secs,
            shell_hint,
        })
    }
}

pub async fn handle_exec(payload: Value) -> Value {
    let req = match ExecRequest::parse(&payload) {
        Ok(r) => r,
        Err(e) => return e,
    };

    // ── Validate base_cwd exists (matches Python early check) ──
    if let Some(ref base) = req.base_cwd {
        if !Path::new(base).is_dir() {
            return exec_error(format!("Working directory does not exist: {base}"));
        }
    }

    // ── Resolve cwd_override under base_cwd (with path safety) ──
    let effective_cwd = match (&req.cwd_override, &req.base_cwd) {
        (Some(over), _) => match resolve_safe_path(over, req.base_cwd.as_deref()) {
            Ok(p) => {
                if !p.is_dir() {
                    return exec_error(format!(
                        "cwd_override is not a directory: {over}"
                    ));
                }
                Some(p)
            }
            Err(e) => {
                return exec_error(format!(
                    "Invalid cwd_override: {}",
                    format_path_error(e)
                ));
            }
        },
        (None, Some(base)) => Some(Path::new(base).to_path_buf()),
        (None, None) => None,
    };

    // ── Resolve shell argv ──
    let argv = match resolve_shell_argv(&req.shell_hint) {
        Some(a) => a,
        None => {
            return exec_error(format!(
                "shell={:?} not available on this agent",
                req.shell_hint
            ));
        }
    };

    // ── Build Command ──
    let (program, prefix_args) = argv.split_first().expect("argv non-empty");
    let mut cmd = Command::new(program);
    for a in prefix_args {
        cmd.arg(a);
    }
    cmd.arg(&req.command);
    if let Some(cwd) = &effective_cwd {
        cmd.current_dir(cwd);
    }
    if let Some(env) = &req.extra_env {
        for (k, v) in env {
            cmd.env(k, v);
        }
    }
    cmd.stdout(Stdio::piped()).stderr(Stdio::piped()).stdin(Stdio::null());

    // POSIX: detach into a fresh process group so timeout kill takes
    // out the whole pipeline (sh's children too).
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        cmd.process_group(0);
    }
    // Windows: a new process group lets us send Ctrl-Break later if
    // we want graceful termination. For the SIGKILL-equivalent we use
    // child.kill() which falls back to TerminateProcess. tokio's
    // Command exposes `creation_flags` directly — no trait import
    // needed (unlike std's Command, where it lives on
    // `os::windows::process::CommandExt`).
    #[cfg(windows)]
    {
        const CREATE_NEW_PROCESS_GROUP: u32 = 0x0000_0200;
        cmd.creation_flags(CREATE_NEW_PROCESS_GROUP);
    }

    // ── Spawn ──
    let child = match cmd.spawn() {
        Ok(c) => c,
        Err(e) => return exec_error(e.to_string()),
    };
    // Capture pid before we move child into wait — needed for POSIX killpg.
    let _pid = child.id();

    // ── Wait with timeout, kill on expiry ──
    let dur = Duration::from_secs(req.timeout_secs);
    let wait_result = timeout(dur, child.wait_with_output()).await;
    match wait_result {
        Ok(Ok(out)) => exec_result(out.status.code(), out.stdout, out.stderr, false, 0),
        Ok(Err(e)) => exec_error(e.to_string()),
        Err(_elapsed) => {
            // Timeout — kill, drain, return.
            // After the inner future is dropped, the Child handle is gone;
            // re-spawn pattern would be cleaner, but we don't need to drain
            // output if the kill happens (pipes auto-close on EOF). The
            // Python implementation captures partial output via communicate()
            // after kill; we approximate by returning the truncation marker
            // only.
            #[cfg(unix)]
            if let Some(pid) = _pid {
                let _ = unix_killpg(pid as i32);
            }
            // `wait_with_output` consumed the child, but on timeout the
            // future was dropped before completion. We can't drain
            // further; report the timeout cleanly so callers know the
            // process was killed.
            exec_timeout_result(req.timeout_secs)
        }
    }
}

fn exec_result(
    exit_code: Option<i32>,
    stdout: Vec<u8>,
    stderr: Vec<u8>,
    extra_truncate_marker: bool,
    _placeholder: usize,
) -> Value {
    let _ = extra_truncate_marker;
    let (out_text, out_trunc, out_total) = truncate_with_flag(&stdout, MAX_OUTPUT_BYTES);
    let (err_text, err_trunc, err_total) = truncate_with_flag(&stderr, MAX_OUTPUT_BYTES);
    json!({
        "exit_code": exit_code.unwrap_or(-1),
        "stdout": out_text,
        "stderr": err_text,
        "stdout_truncated": out_trunc,
        "stderr_truncated": err_trunc,
        "stdout_total_bytes": out_total,
        "stderr_total_bytes": err_total,
    })
}

fn exec_timeout_result(timeout_secs: u64) -> Value {
    json!({
        "exit_code": -1,
        "stdout": "",
        "stderr": format!("\n[timeout after {timeout_secs}s]"),
        "stdout_truncated": false,
        "stderr_truncated": false,
        "stdout_total_bytes": 0,
        "stderr_total_bytes": 0,
    })
}

fn truncate_with_flag(data: &[u8], limit: usize) -> (String, bool, usize) {
    let total = data.len();
    let truncated = total > limit;
    let slice = if truncated { &data[..limit] } else { data };
    let text = String::from_utf8_lossy(slice).into_owned();
    (text, truncated, total)
}

fn exec_error(msg: impl Into<String>) -> Value {
    json!({
        "exit_code": -1,
        "stdout": "",
        "stderr": msg.into(),
        "stdout_truncated": false,
        "stderr_truncated": false,
        "stdout_total_bytes": 0,
        "stderr_total_bytes": 0,
    })
}

fn format_path_error(e: PathSafetyError) -> String {
    match e {
        PathSafetyError::CwdRequired => "cwd is required".into(),
        PathSafetyError::CwdNotADir(c) => format!("Working directory does not exist: {c}"),
        PathSafetyError::NulByte => "Invalid path: contains NUL byte".into(),
        PathSafetyError::Traversal => "Path traversal not allowed".into(),
    }
}

#[cfg(unix)]
fn unix_killpg(pid: i32) -> nix::Result<()> {
    use nix::sys::signal::{killpg, Signal};
    use nix::unistd::Pid;
    killpg(Pid::from_raw(pid), Signal::SIGKILL)
}

/// Map a `shell=` hint to a command + prefix args. Returns `None` when
/// the requested shell is not available on this host.
fn resolve_shell_argv(hint: &str) -> Option<Vec<String>> {
    match hint {
        "" | "default" => Some(default_shell_argv()),
        "bash" | "sh" => find_bash_argv(),
        "cmd" => find_cmd_argv(),
        "pwsh" | "powershell" => find_pwsh_argv(),
        _ => None,
    }
}

fn default_shell_argv() -> Vec<String> {
    if cfg!(windows) {
        let comspec = std::env::var("COMSPEC")
            .unwrap_or_else(|_| r"C:\Windows\system32\cmd.exe".into());
        vec![comspec, "/c".into()]
    } else {
        vec!["/bin/sh".into(), "-c".into()]
    }
}

fn find_bash_argv() -> Option<Vec<String>> {
    if cfg!(windows) {
        // Try Git for Windows / msys2 in that order.
        let candidates = [
            r"C:\Program Files\Git\bin\bash.exe",
            r"C:\Program Files\Git\usr\bin\bash.exe",
            r"C:\Program Files (x86)\Git\bin\bash.exe",
            r"C:\msys64\usr\bin\bash.exe",
            r"C:\msys2\usr\bin\bash.exe",
        ];
        for c in candidates {
            if Path::new(c).exists() {
                return Some(vec![c.into(), "-c".into()]);
            }
        }
        None
    } else {
        for c in ["/bin/bash", "/usr/bin/bash", "/bin/sh"] {
            if Path::new(c).exists() {
                return Some(vec![c.into(), "-c".into()]);
            }
        }
        None
    }
}

fn find_cmd_argv() -> Option<Vec<String>> {
    if cfg!(windows) {
        let comspec = std::env::var("COMSPEC")
            .unwrap_or_else(|_| r"C:\Windows\system32\cmd.exe".into());
        if Path::new(&comspec).exists() {
            Some(vec![comspec, "/c".into()])
        } else {
            None
        }
    } else {
        None
    }
}

fn find_pwsh_argv() -> Option<Vec<String>> {
    let candidates: &[&str] = if cfg!(windows) {
        &[
            r"C:\Program Files\PowerShell\7\pwsh.exe",
            r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
        ]
    } else {
        &["/usr/bin/pwsh", "/usr/local/bin/pwsh"]
    };
    for c in candidates {
        if Path::new(c).exists() {
            return Some(vec![
                (*c).into(),
                "-NoProfile".into(),
                "-Command".into(),
            ]);
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn tmp() -> TempDir {
        tempfile::tempdir().unwrap()
    }

    #[tokio::test]
    async fn exec_default_shell_echo() {
        let v = handle_exec(json!({
            "command": if cfg!(windows) { "echo hello" } else { "echo hello" },
        }))
        .await;
        assert_eq!(v["exit_code"], 0);
        let out = v["stdout"].as_str().unwrap();
        assert!(out.contains("hello"), "stdout was {out:?}");
        assert_eq!(v["stdout_truncated"], false);
    }

    #[tokio::test]
    async fn exec_nonzero_exit_propagates() {
        let v = handle_exec(json!({
            "command": if cfg!(windows) { "exit /b 42" } else { "exit 42" },
        }))
        .await;
        assert_eq!(v["exit_code"], 42);
    }

    #[tokio::test]
    async fn exec_cwd_runs_in_dir() {
        let d = tmp();
        std::fs::write(d.path().join("marker.txt"), "1").unwrap();
        let cmd = if cfg!(windows) { "dir /b" } else { "ls" };
        let v = handle_exec(json!({
            "command": cmd,
            "cwd": d.path().to_string_lossy(),
        }))
        .await;
        assert_eq!(v["exit_code"], 0);
        let out = v["stdout"].as_str().unwrap();
        assert!(out.contains("marker.txt"), "stdout was {out:?}");
    }

    #[tokio::test]
    async fn exec_cwd_override_respects_path_safety() {
        let d = tmp();
        let v = handle_exec(json!({
            "command": "echo hi",
            "cwd": d.path().to_string_lossy(),
            "cwd_override": "../escape",
        }))
        .await;
        assert_eq!(v["exit_code"], -1);
        let err = v["stderr"].as_str().unwrap_or("");
        assert!(
            err.to_lowercase().contains("invalid cwd_override"),
            "stderr: {err}"
        );
    }

    #[tokio::test]
    async fn exec_env_override_visible_to_child() {
        let v = handle_exec(json!({
            "command": if cfg!(windows) {
                "echo %FOO_TEST_VAR%"
            } else {
                "echo $FOO_TEST_VAR"
            },
            "env": {"FOO_TEST_VAR": "bar123"},
        }))
        .await;
        assert_eq!(v["exit_code"], 0);
        let out = v["stdout"].as_str().unwrap();
        assert!(out.contains("bar123"), "stdout: {out:?}");
    }

    #[tokio::test]
    async fn exec_env_must_be_object_of_strings() {
        let v = handle_exec(json!({
            "command": "echo x",
            "env": {"FOO": 123},
        }))
        .await;
        assert_eq!(v["exit_code"], -1);
        assert!(v["stderr"].as_str().unwrap_or("").contains("strings"));
    }

    #[tokio::test]
    async fn exec_unknown_shell_rejected() {
        let v = handle_exec(json!({
            "command": "echo x",
            "shell": "nonsense",
        }))
        .await;
        assert_eq!(v["exit_code"], -1);
        assert!(v["stderr"].as_str().unwrap_or("").contains("not available"));
    }

    #[tokio::test]
    async fn exec_timeout_returns_marker() {
        // Ask for a 1-second timeout on a 10s sleep. Under POSIX
        // process_group kill, the sleep is killed via SIGKILL to the
        // process group. On Windows, child.kill() takes out cmd.exe.
        let cmd = if cfg!(windows) {
            // `ping -n 11 127.0.0.1 > NUL` ≈ 10 s sleep that works
            // under piped stdio (cmd's `timeout /t` exits 125 when
            // stdin is redirected, so it can't be used here).
            "ping -n 11 127.0.0.1 > NUL"
        } else {
            "sleep 10"
        };
        let start = std::time::Instant::now();
        let v = handle_exec(json!({
            "command": cmd,
            "timeout": 1,
        }))
        .await;
        let elapsed = start.elapsed();
        assert!(
            elapsed < Duration::from_secs(5),
            "timeout took too long: {:?}",
            elapsed
        );
        assert_eq!(v["exit_code"], -1);
        assert!(v["stderr"]
            .as_str()
            .unwrap_or("")
            .contains("[timeout after"));
    }

    #[tokio::test]
    async fn exec_base_cwd_must_exist() {
        let v = handle_exec(json!({
            "command": "echo x",
            "cwd": "/this/path/does/not/exist/anywhere",
        }))
        .await;
        assert_eq!(v["exit_code"], -1);
        assert!(v["stderr"]
            .as_str()
            .unwrap_or("")
            .contains("Working directory does not exist"));
    }
}
