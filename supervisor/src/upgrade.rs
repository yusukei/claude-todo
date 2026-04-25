//! Atomic agent-binary upgrade flow per spec §6.4.
//!
//! Steps:
//!   1. Create ``<exe>.lock`` so an interrupted upgrade can be
//!      detected on the next supervisor start.
//!   2. Stream-download to ``<exe>.new`` while computing sha256.
//!   3. Verify the streamed sha256 matches the request's expected
//!      digest; abort + delete on mismatch.
//!   4. ``sync_all`` the ``.new`` file (Win32 ``FlushFileBuffers``
//!      via the std impl).
//!   5. Pause the supervised loop (``AgentManager::pause``); kills
//!      the live agent without bumping the crash counter.
//!   6. Atomically swap: rename ``<exe>`` -> ``<exe>.old``, rename
//!      ``<exe>.new`` -> ``<exe>``.
//!   7. Re-hash the file at the target path; rollback on mismatch.
//!   8. Resume the supervised loop — the new binary is spawned.
//!   9. Observe for 30s; if the agent crashes more than once during
//!      this window, rollback (``<exe>.old`` -> ``<exe>``).
//!  10. On success, delete ``<exe>.old`` and the ``.lock`` file.

use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration;

use anyhow::{bail, Context, Result};
use futures_util::StreamExt;
use sha2::{Digest, Sha256};
use tokio::fs;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::time::{sleep, Instant};
use tracing::{info, warn};

use crate::process::AgentManager;
use crate::protocol::UpgradeResponse;

const OBSERVE_DURATION: Duration = Duration::from_secs(30);
const PAUSE_TIMEOUT: Duration = Duration::from_secs(15);
const SHA256_HEX_LEN: usize = 64;

pub async fn run_upgrade(
    target: &Path,
    download_url: &str,
    expected_sha256: &str,
    agent: Arc<AgentManager>,
) -> UpgradeResponse {
    match try_upgrade(target, download_url, expected_sha256, agent).await {
        Ok(()) => UpgradeResponse {
            success: true,
            new_version: None,
            error: None,
        },
        Err(e) => UpgradeResponse {
            success: false,
            new_version: None,
            error: Some(format!("{e:#}")),
        },
    }
}

async fn try_upgrade(
    target: &Path,
    download_url: &str,
    expected_sha256: &str,
    agent: Arc<AgentManager>,
) -> Result<()> {
    if expected_sha256.len() != SHA256_HEX_LEN
        || !expected_sha256.bytes().all(|b| b.is_ascii_hexdigit())
    {
        bail!("expected sha256 must be {SHA256_HEX_LEN} lowercase hex chars");
    }
    let expected = expected_sha256.to_ascii_lowercase();

    let new_path = append_extension(target, "new");
    let old_path = append_extension(target, "old");
    let lock_path = append_extension(target, "lock");

    fs::write(&lock_path, b"upgrading\n")
        .await
        .with_context(|| format!("create lock file {}", lock_path.display()))?;
    let _lock_guard = LockGuard {
        path: lock_path.clone(),
    };

    // 1+2: download + running sha256.
    let download_hash = download_to(&new_path, download_url).await?;
    if download_hash != expected {
        let _ = fs::remove_file(&new_path).await;
        bail!(
            "sha256 mismatch (download): expected {expected}, got {download_hash}"
        );
    }

    // 3: explicit fsync (download_to already calls sync_all but make
    // the contract obvious here for the §6.4 audit trail).
    sync_path(&new_path).await?;

    // 4: pause supervised loop and wait for agent to reach Stopped.
    agent
        .pause(PAUSE_TIMEOUT)
        .await
        .context("agent pause for upgrade")?;

    // Helper: rollback closure used for both verify-fail and crash-
    // observation paths. Re-pauses the loop, restores from .old, and
    // resumes — leaving the crash counter and run state coherent.
    let rollback_from_old = |old: PathBuf, target: PathBuf, agent: Arc<AgentManager>| async move {
        let _ = fs::remove_file(&target).await;
        if old.exists() {
            if let Err(e) = fs::rename(&old, &target).await {
                warn!(error = %e, "rollback rename failed");
            }
        }
        agent.resume();
    };

    // 5: atomic swap. tokio::fs::rename uses MoveFileEx-equivalent
    // on Windows (REPLACE_EXISTING semantics).
    if target.exists() {
        let _ = fs::remove_file(&old_path).await;
        if let Err(e) = fs::rename(target, &old_path).await {
            agent.resume();
            return Err(e).with_context(|| {
                format!("rename {} -> {}", target.display(), old_path.display())
            });
        }
    }
    if let Err(e) = fs::rename(&new_path, target).await {
        // If the second rename fails we have to put .old back to
        // avoid leaving the agent without a binary at all.
        let restore_err = if old_path.exists() {
            fs::rename(&old_path, target).await.err()
        } else {
            None
        };
        agent.resume();
        if let Some(re) = restore_err {
            warn!(error = %re, "restore from .old failed during swap-failure path");
        }
        return Err(e)
            .with_context(|| format!("rename {} -> {}", new_path.display(), target.display()));
    }

    // 6: re-hash the file at the target path.
    let post_hash = sha256_file(target).await?;
    if post_hash != expected {
        warn!(
            expected,
            actual = post_hash,
            "post-write sha256 mismatch; rolling back"
        );
        rollback_from_old(old_path.clone(), target.to_path_buf(), agent.clone()).await;
        bail!(
            "sha256 mismatch (post-write): expected {expected}, got {post_hash}"
        );
    }

    // 7: resume — supervised loop will respawn with the new binary.
    let crashes_baseline = agent.status().consecutive_crashes;
    agent.resume();

    // 8: observe. A single crash can be a transient race during
    // respawn; two within the window flags the new binary as broken.
    let deadline = Instant::now() + OBSERVE_DURATION;
    while Instant::now() < deadline {
        sleep(Duration::from_millis(500)).await;
        let snap = agent.status();
        if snap.consecutive_crashes > crashes_baseline.saturating_add(1) {
            warn!(
                crashes = snap.consecutive_crashes,
                baseline = crashes_baseline,
                "new binary crashed during 30s observation; rolling back"
            );
            agent
                .pause(PAUSE_TIMEOUT)
                .await
                .context("agent pause for rollback")?;
            rollback_from_old(old_path.clone(), target.to_path_buf(), agent.clone()).await;
            bail!("new binary crashed twice within 30s; rolled back");
        }
    }

    // 9: cleanup.
    let _ = fs::remove_file(&old_path).await;
    info!(target = %target.display(), "upgrade succeeded");
    Ok(())
}

async fn download_to(dest: &Path, url: &str) -> Result<String> {
    let resp = reqwest::get(url)
        .await
        .with_context(|| format!("GET {url}"))?
        .error_for_status()
        .with_context(|| format!("GET {url} returned non-success"))?;

    let mut file = fs::File::create(dest)
        .await
        .with_context(|| format!("create {}", dest.display()))?;
    let mut hasher = Sha256::new();
    let mut stream = resp.bytes_stream();
    while let Some(chunk) = stream.next().await {
        let chunk = chunk.context("read response chunk")?;
        hasher.update(&chunk);
        file.write_all(&chunk)
            .await
            .with_context(|| format!("write {}", dest.display()))?;
    }
    file.flush()
        .await
        .with_context(|| format!("flush {}", dest.display()))?;
    file.sync_all()
        .await
        .with_context(|| format!("sync_all {}", dest.display()))?;
    drop(file);
    Ok(hex_lower(&hasher.finalize()))
}

async fn sync_path(p: &Path) -> Result<()> {
    let f = fs::File::open(p)
        .await
        .with_context(|| format!("open {} for fsync", p.display()))?;
    f.sync_all()
        .await
        .with_context(|| format!("sync_all {}", p.display()))?;
    Ok(())
}

async fn sha256_file(p: &Path) -> Result<String> {
    let mut file = fs::File::open(p)
        .await
        .with_context(|| format!("open {}", p.display()))?;
    let mut hasher = Sha256::new();
    let mut buf = vec![0u8; 64 * 1024];
    loop {
        let n = file
            .read(&mut buf)
            .await
            .with_context(|| format!("read {}", p.display()))?;
        if n == 0 {
            break;
        }
        hasher.update(&buf[..n]);
    }
    Ok(hex_lower(&hasher.finalize()))
}

fn hex_lower(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

/// Append a literal ``.<ext>`` to the path's filename. Used instead
/// of ``Path::with_extension`` because the latter *replaces* an
/// existing extension (so ``foo.exe`` would become ``foo.new``
/// instead of the desired ``foo.exe.new``).
fn append_extension(path: &Path, ext: &str) -> PathBuf {
    let mut s = path.as_os_str().to_owned();
    s.push(".");
    s.push(ext);
    PathBuf::from(s)
}

struct LockGuard {
    path: PathBuf,
}

impl Drop for LockGuard {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.path);
    }
}

/// On supervisor startup, recover from an interrupted upgrade.
///
/// If a ``.lock`` file exists for ``target``: an upgrade was in
/// progress when the supervisor died. Restore from ``.old`` if the
/// target file is missing or stale, delete any half-written ``.new``,
/// and clear the lock.
pub fn recover_interrupted_upgrade(target: &Path) -> Result<()> {
    let lock_path = append_extension(target, "lock");
    let old_path = append_extension(target, "old");
    let new_path = append_extension(target, "new");

    if !lock_path.exists() {
        return Ok(());
    }
    warn!(
        target = %target.display(),
        "found interrupted upgrade lock; attempting recovery"
    );
    if old_path.exists() && !target.exists() {
        std::fs::rename(&old_path, target)
            .context("restore target from .old")?;
        info!("restored target from .old");
    }
    if new_path.exists() {
        let _ = std::fs::remove_file(&new_path);
    }
    let _ = std::fs::remove_file(&lock_path);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[test]
    fn append_extension_preserves_existing() {
        let p = Path::new("/tmp/agent.exe");
        assert_eq!(
            append_extension(p, "new"),
            PathBuf::from("/tmp/agent.exe.new")
        );
        assert_eq!(
            append_extension(p, "old"),
            PathBuf::from("/tmp/agent.exe.old")
        );
        assert_eq!(
            append_extension(p, "lock"),
            PathBuf::from("/tmp/agent.exe.lock")
        );
    }

    #[test]
    fn append_extension_handles_no_extension() {
        let p = Path::new("/tmp/agent");
        assert_eq!(
            append_extension(p, "new"),
            PathBuf::from("/tmp/agent.new")
        );
    }

    #[tokio::test]
    async fn sha256_file_matches_known_vector() {
        let tmp = TempDir::new().unwrap();
        let p = tmp.path().join("data.bin");
        fs::write(&p, b"abc").await.unwrap();
        // sha256("abc") = ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad
        assert_eq!(
            sha256_file(&p).await.unwrap(),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
    }

    #[tokio::test]
    async fn lock_guard_removes_lock_on_drop() {
        let tmp = TempDir::new().unwrap();
        let lock = tmp.path().join("agent.exe.lock");
        fs::write(&lock, b"upgrading\n").await.unwrap();
        assert!(lock.exists());
        {
            let _g = LockGuard { path: lock.clone() };
        }
        assert!(!lock.exists());
    }

    #[test]
    fn recover_no_lock_is_noop() {
        let tmp = TempDir::new().unwrap();
        let target = tmp.path().join("agent.exe");
        std::fs::write(&target, b"v1").unwrap();
        recover_interrupted_upgrade(&target).expect("noop");
        assert_eq!(std::fs::read(&target).unwrap(), b"v1");
    }

    #[test]
    fn recover_with_lock_restores_old_when_target_missing() {
        let tmp = TempDir::new().unwrap();
        let target = tmp.path().join("agent.exe");
        let old = tmp.path().join("agent.exe.old");
        let lock = tmp.path().join("agent.exe.lock");
        let new = tmp.path().join("agent.exe.new");
        std::fs::write(&old, b"v1").unwrap();
        std::fs::write(&new, b"partial").unwrap();
        std::fs::write(&lock, b"upgrading\n").unwrap();

        recover_interrupted_upgrade(&target).expect("recover");

        assert_eq!(std::fs::read(&target).unwrap(), b"v1");
        assert!(!new.exists());
        assert!(!lock.exists());
    }

    #[test]
    fn try_upgrade_rejects_bad_sha256_format() {
        // No tokio runtime needed — we short-circuit before any async
        // work via the format check.
        let rt = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .unwrap();
        let tmp = TempDir::new().unwrap();
        let target = tmp.path().join("agent.exe");
        let agent = std::sync::Arc::new(
            crate::process::AgentManager::new(
                crate::process::AgentCommand {
                    program: PathBuf::from(if cfg!(windows) { "cmd.exe" } else { "/bin/sh" }),
                    args: vec!["-c".into(), "true".into()],
                    cwd: std::env::current_dir().unwrap(),
                    env: std::collections::HashMap::new(),
                },
                crate::config::RestartConfig::default(),
                crate::log_capture::LogRing::new(10, 4096, 16),
                std::sync::Arc::new(crate::process::NoShutdownHook),
            )
            .unwrap(),
        );
        let resp = rt.block_on(run_upgrade(
            &target,
            "https://example/missing",
            "not-hex",
            agent,
        ));
        assert!(!resp.success);
        let err = resp.error.unwrap();
        assert!(
            err.contains("expected sha256 must be"),
            "unexpected error: {err}"
        );
    }
}
