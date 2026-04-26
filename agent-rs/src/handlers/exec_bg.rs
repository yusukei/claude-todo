//! `exec_background` / `exec_status` — fire-and-forget command
//! execution with later status polling.
//!
//! Mirrors the Python implementation at `agent/main.py:285-447`. A
//! global registry holds up to `MAX_BG_JOBS` jobs; when full we evict
//! roughly half of the completed ones (matches Python's eviction
//! pattern). Each job runs in its own tokio task; the shell-resolution
//! and truncation helpers are shared with the synchronous `exec`
//! handler so behaviour stays identical between the two.
//!
//! Notes vs Python:
//! - We capture stdout/stderr at completion (Python also does this).
//!   Live tailing of an in-flight job isn't supported by either.
//! - Job IDs are `uuid v4` hex sliced to 12 chars (Python:
//!   `_uuid.uuid4().hex[:12]`).

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::sync::{Arc, Mutex, OnceLock};
use std::time::{Duration, Instant};

use serde_json::{json, Value};
use tokio::process::Command;
use tokio::time::timeout;

use super::constants::{
    DEFAULT_EXEC_TIMEOUT_SECS, MAX_EXEC_TIMEOUT_SECS, MAX_OUTPUT_BYTES,
};
use super::exec::{resolve_shell_argv, truncate_with_flag};
use crate::path_safety::{resolve_safe_path, PathSafetyError};

const MAX_BG_JOBS: usize = 64;
const COMMAND_SUMMARY_LEN: usize = 200;

#[derive(Debug, Clone, Default)]
struct BackgroundJob {
    job_id: String,
    command_summary: String,
    pid: Option<u32>,
    exit_code: Option<i32>,
    stdout: String,
    stderr: String,
    stdout_truncated: bool,
    stderr_truncated: bool,
    stdout_total_bytes: usize,
    stderr_total_bytes: usize,
    started_at: String,
    completed_at: Option<String>,
    duration_ms: Option<u128>,
}

type Registry = Arc<Mutex<HashMap<String, Arc<Mutex<BackgroundJob>>>>>;

fn registry() -> &'static Registry {
    static R: OnceLock<Registry> = OnceLock::new();
    R.get_or_init(|| Arc::new(Mutex::new(HashMap::new())))
}

fn now_iso() -> String {
    chrono::Utc::now().format("%Y-%m-%dT%H:%M:%S%.6f+00:00").to_string()
}

fn new_job_id() -> String {
    // Python: `uuid.uuid4().hex[:12]` — 12 lowercase hex chars
    let s = uuid::Uuid::new_v4().simple().to_string();
    s.chars().take(12).collect()
}

/// `exec_background` — start a command and return a `job_id` immediately.
pub async fn handle_exec_background(payload: Value) -> Value {
    // Pre-flight: parse the small fields synchronously so we can fail
    // fast (and not allocate a job slot) on bad input.
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
            let mut out = HashMap::with_capacity(map.len());
            for (k, v) in map {
                let s = match v.as_str() {
                    Some(s) => s,
                    None => {
                        return error_payload("env keys/values must be strings");
                    }
                };
                out.insert(k.clone(), s.to_string());
            }
            Some(out)
        }
        Some(_) => return error_payload("env must be an object of string→string"),
    };
    let timeout_secs = payload
        .get("timeout")
        .and_then(Value::as_u64)
        .unwrap_or(MAX_EXEC_TIMEOUT_SECS) // BG default is 1h, not 60s
        .min(MAX_EXEC_TIMEOUT_SECS);
    let _ = DEFAULT_EXEC_TIMEOUT_SECS; // referenced elsewhere
    let shell_hint = payload
        .get("shell")
        .and_then(Value::as_str)
        .unwrap_or("default")
        .to_lowercase();

    // Eviction: if the registry is full, drop ~half of the completed
    // jobs to make room. Mirrors Python's strategy at main.py:397-400.
    {
        let reg = registry().lock().unwrap();
        if reg.len() >= MAX_BG_JOBS {
            drop(reg);
            evict_completed_half();
        }
    }

    let job_id = new_job_id();
    let started_at = now_iso();
    let job = Arc::new(Mutex::new(BackgroundJob {
        job_id: job_id.clone(),
        command_summary: command.chars().take(COMMAND_SUMMARY_LEN).collect(),
        started_at: started_at.clone(),
        ..Default::default()
    }));
    registry()
        .lock()
        .unwrap()
        .insert(job_id.clone(), job.clone());

    // Fire-and-forget the actual run. Errors during spawn surface as
    // exit_code=-1 + stderr in the job; the caller will see them on
    // the next exec_status.
    tokio::spawn(run_bg_job(
        job,
        command,
        base_cwd,
        cwd_override,
        extra_env,
        timeout_secs,
        shell_hint,
    ));

    json!({
        "job_id": job_id,
        "status": "running",
        "started_at": started_at,
    })
}

#[allow(clippy::too_many_arguments)]
async fn run_bg_job(
    job: Arc<Mutex<BackgroundJob>>,
    command: String,
    base_cwd: Option<String>,
    cwd_override: Option<String>,
    extra_env: Option<HashMap<String, String>>,
    timeout_secs: u64,
    shell_hint: String,
) {
    let start = Instant::now();

    // Resolve cwd_override under base_cwd (if given). Failures land in
    // the job's stderr/exit_code.
    let effective_cwd: Option<PathBuf> = match (&cwd_override, &base_cwd) {
        (Some(over), _) => match resolve_safe_path(over, base_cwd.as_deref()) {
            Ok(p) if p.is_dir() => Some(p),
            Ok(_) => {
                fail_job(
                    &job,
                    -1,
                    "",
                    &format!("cwd_override is not a directory: {over}"),
                    start,
                );
                return;
            }
            Err(e) => {
                fail_job(
                    &job,
                    -1,
                    "",
                    &format!("Invalid cwd_override: {}", format_path_error(e)),
                    start,
                );
                return;
            }
        },
        (None, Some(base)) => Some(Path::new(base).to_path_buf()),
        (None, None) => None,
    };

    let argv = match resolve_shell_argv(&shell_hint) {
        Some(a) => a,
        None => {
            fail_job(
                &job,
                -1,
                "",
                &format!("shell={shell_hint:?} not available on this agent"),
                start,
            );
            return;
        }
    };

    let (program, prefix_args) = argv.split_first().expect("argv non-empty");
    let mut cmd = Command::new(program);
    for a in prefix_args {
        cmd.arg(a);
    }
    cmd.arg(&command);
    if let Some(cwd) = &effective_cwd {
        cmd.current_dir(cwd);
    }
    if let Some(env) = &extra_env {
        for (k, v) in env {
            cmd.env(k, v);
        }
    }
    cmd.stdout(Stdio::piped()).stderr(Stdio::piped()).stdin(Stdio::null());

    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        cmd.process_group(0);
    }
    #[cfg(windows)]
    {
        const CREATE_NEW_PROCESS_GROUP: u32 = 0x0000_0200;
        cmd.creation_flags(CREATE_NEW_PROCESS_GROUP);
    }

    let child = match cmd.spawn() {
        Ok(c) => c,
        Err(e) => {
            fail_job(&job, -1, "", &e.to_string(), start);
            return;
        }
    };
    let pid = child.id();
    {
        let mut g = job.lock().unwrap();
        g.pid = pid;
    }

    let dur = Duration::from_secs(timeout_secs);
    let wait_result = timeout(dur, child.wait_with_output()).await;
    match wait_result {
        Ok(Ok(out)) => {
            let (out_text, out_trunc, out_total) =
                truncate_with_flag(&out.stdout, MAX_OUTPUT_BYTES);
            let (err_text, err_trunc, err_total) =
                truncate_with_flag(&out.stderr, MAX_OUTPUT_BYTES);
            let mut g = job.lock().unwrap();
            g.exit_code = Some(out.status.code().unwrap_or(-1));
            g.stdout = out_text;
            g.stderr = err_text;
            g.stdout_truncated = out_trunc;
            g.stderr_truncated = err_trunc;
            g.stdout_total_bytes = out_total;
            g.stderr_total_bytes = err_total;
            g.completed_at = Some(now_iso());
            g.duration_ms = Some(start.elapsed().as_millis());
        }
        Ok(Err(e)) => {
            fail_job(&job, -1, "", &e.to_string(), start);
        }
        Err(_) => {
            // Timeout: kill the process group on POSIX so the whole
            // pipeline dies; on Windows the immediate child kill is
            // best-effort (TerminateProcess via Tokio).
            #[cfg(unix)]
            if let Some(pid) = pid {
                use nix::sys::signal::{killpg, Signal};
                use nix::unistd::Pid;
                let _ = killpg(Pid::from_raw(pid as i32), Signal::SIGKILL);
            }
            fail_job(
                &job,
                -1,
                "",
                &format!("\n[timeout after {timeout_secs}s]"),
                start,
            );
        }
    }
}

fn fail_job(
    job: &Arc<Mutex<BackgroundJob>>,
    exit_code: i32,
    stdout: &str,
    stderr: &str,
    start: Instant,
) {
    let mut g = job.lock().unwrap();
    g.exit_code = Some(exit_code);
    g.stdout = stdout.into();
    g.stderr = stderr.into();
    g.completed_at = Some(now_iso());
    g.duration_ms = Some(start.elapsed().as_millis());
}

fn format_path_error(e: PathSafetyError) -> String {
    match e {
        PathSafetyError::CwdRequired => "cwd is required".into(),
        PathSafetyError::CwdNotADir(c) => format!("Working directory does not exist: {c}"),
        PathSafetyError::NulByte => "Invalid path: contains NUL byte".into(),
        PathSafetyError::Traversal => "Path traversal not allowed".into(),
    }
}

fn evict_completed_half() {
    let mut reg = registry().lock().unwrap();
    let completed: Vec<String> = reg
        .iter()
        .filter_map(|(id, job)| {
            let g = job.lock().unwrap();
            if g.completed_at.is_some() {
                Some(id.clone())
            } else {
                None
            }
        })
        .collect();
    let drop_n = completed.len() / 2 + 1;
    for id in completed.into_iter().take(drop_n) {
        reg.remove(&id);
    }
}

fn error_payload(msg: impl Into<String>) -> Value {
    json!({ "error": msg.into() })
}

/// `exec_status` — return the current state of a background job.
pub async fn handle_exec_status(payload: Value) -> Value {
    let job_id = payload.get("job_id").and_then(Value::as_str).unwrap_or("");
    if job_id.is_empty() {
        return json!({"error": "job_id is required", "status": "not_found"});
    }
    let job_arc = {
        let reg = registry().lock().unwrap();
        reg.get(job_id).cloned()
    };
    let Some(job_arc) = job_arc else {
        return json!({
            "error": format!("Job not found: {job_id}"),
            "status": "not_found",
        });
    };
    let g = job_arc.lock().unwrap();
    let mut out = json!({
        "job_id": g.job_id,
        "status": if g.completed_at.is_some() { "completed" } else { "running" },
        "command": g.command_summary,
        "started_at": g.started_at,
    });
    if let Some(completed_at) = &g.completed_at {
        let map = out.as_object_mut().unwrap();
        map.insert("exit_code".into(), json!(g.exit_code.unwrap_or(-1)));
        map.insert("stdout".into(), json!(g.stdout));
        map.insert("stderr".into(), json!(g.stderr));
        map.insert("stdout_truncated".into(), json!(g.stdout_truncated));
        map.insert("stderr_truncated".into(), json!(g.stderr_truncated));
        map.insert("stdout_total_bytes".into(), json!(g.stdout_total_bytes));
        map.insert("stderr_total_bytes".into(), json!(g.stderr_total_bytes));
        map.insert("completed_at".into(), json!(completed_at));
        map.insert("duration_ms".into(), json!(g.duration_ms.unwrap_or(0)));
    } else if let Some(pid) = g.pid {
        out.as_object_mut().unwrap().insert("pid".into(), json!(pid));
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Test helper: spawn an exec_background and wait for completion.
    async fn run_and_wait(payload: Value, max_wait_secs: u64) -> Value {
        let started = handle_exec_background(payload).await;
        let job_id = started["job_id"].as_str().unwrap().to_string();
        let deadline = Duration::from_secs(max_wait_secs);
        let start = Instant::now();
        loop {
            let v = handle_exec_status(json!({"job_id": job_id})).await;
            if v["status"] == "completed" {
                return v;
            }
            if start.elapsed() > deadline {
                panic!("job {job_id} did not complete within {max_wait_secs}s: {v:?}");
            }
            tokio::time::sleep(Duration::from_millis(50)).await;
        }
    }

    #[tokio::test]
    async fn bg_short_command_completes() {
        let v = run_and_wait(
            json!({
                "command": if cfg!(windows) { "echo hello" } else { "echo hello" },
            }),
            10,
        )
        .await;
        assert_eq!(v["exit_code"], 0);
        let out = v["stdout"].as_str().unwrap();
        assert!(out.contains("hello"), "stdout: {out}");
        assert!(v["duration_ms"].as_u64().unwrap() < 10_000);
    }

    #[tokio::test]
    async fn bg_immediate_status_running_then_done() {
        // Long-ish command to catch the running state.
        let cmd = if cfg!(windows) {
            "ping -n 3 127.0.0.1 > NUL"
        } else {
            "sleep 1"
        };
        let started = handle_exec_background(json!({"command": cmd})).await;
        assert_eq!(started["status"], "running");
        let job_id = started["job_id"].as_str().unwrap().to_string();
        // Immediately polled status should still be running.
        let mid = handle_exec_status(json!({"job_id": &job_id})).await;
        assert!(
            mid["status"] == "running" || mid["status"] == "completed",
            "status: {}",
            mid["status"]
        );
        // Wait until done.
        let deadline = Instant::now() + Duration::from_secs(15);
        loop {
            let v = handle_exec_status(json!({"job_id": &job_id})).await;
            if v["status"] == "completed" {
                assert_eq!(v["exit_code"], 0);
                break;
            }
            if Instant::now() > deadline {
                panic!("did not complete in time");
            }
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
    }

    #[tokio::test]
    async fn bg_unknown_job_id_not_found() {
        let v = handle_exec_status(json!({"job_id": "nonexistent12"})).await;
        assert_eq!(v["status"], "not_found");
    }

    #[tokio::test]
    async fn bg_missing_job_id_not_found() {
        let v = handle_exec_status(json!({})).await;
        assert_eq!(v["status"], "not_found");
    }

    #[tokio::test]
    async fn bg_invalid_env_rejected_synchronously() {
        let v = handle_exec_background(json!({
            "command": "echo x",
            "env": {"FOO": 123},
        }))
        .await;
        assert!(v["error"].as_str().unwrap_or("").contains("strings"));
    }

    #[tokio::test]
    async fn bg_invalid_cwd_override_recorded_in_job() {
        let d = tempfile::tempdir().unwrap();
        let v = run_and_wait(
            json!({
                "command": "echo x",
                "cwd": d.path().to_string_lossy(),
                "cwd_override": "../escape",
            }),
            5,
        )
        .await;
        assert_eq!(v["exit_code"], -1);
        assert!(v["stderr"]
            .as_str()
            .unwrap_or("")
            .to_lowercase()
            .contains("invalid cwd_override"));
    }

    /// Ignored by default — walks the registry to MAX_BG_JOBS and
    /// triggers eviction. Run with `cargo test bg_eviction --
    /// --ignored` if you want to exercise it manually.
    #[tokio::test]
    #[ignore]
    async fn bg_eviction_when_full() {
        for _ in 0..(MAX_BG_JOBS + 4) {
            let _ = handle_exec_background(json!({"command": "echo eviction-test"}))
                .await;
        }
        // Wait briefly for the spawned tasks to settle.
        tokio::time::sleep(Duration::from_millis(500)).await;
        let reg = registry().lock().unwrap();
        assert!(
            reg.len() <= MAX_BG_JOBS,
            "registry exceeded MAX_BG_JOBS: {}",
            reg.len()
        );
    }
}
