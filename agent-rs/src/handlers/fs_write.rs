//! Write FS handler: `write_file`.
//!
//! Creates parent directories on demand. Future tasks (`agent-rs/04`)
//! reuse the path-traversal helper for `mkdir` / `delete` / `move` /
//! `copy` and add their own functions to this module.

use std::path::Path;

use serde_json::{json, Value};

use super::constants::MAX_FILE_BYTES;
use crate::path_safety::{resolve_safe_dir, PathSafetyError};

/// `write_file` — UTF-8 text write with auto-mkdir for parents.
pub async fn handle_write_file(payload: Value) -> Value {
    let path_input = payload.get("path").and_then(Value::as_str).unwrap_or("");
    let cwd_input = payload.get("cwd").and_then(Value::as_str);
    let content = payload
        .get("content")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();

    let resolved = match resolve_safe_dir(path_input, cwd_input) {
        Ok(p) => p,
        Err(e) => return error_response(format_path_error(e)),
    };

    let bytes = content.into_bytes();
    if bytes.len() > MAX_FILE_BYTES {
        return error_response(format!(
            "Content too large: {} bytes (max {} MB)",
            bytes.len(),
            MAX_FILE_BYTES / 1024 / 1024
        ));
    }

    let resolved_for_blocking = resolved.clone();
    let result = tokio::task::spawn_blocking(move || {
        write_blocking(&resolved_for_blocking, &bytes)
    })
    .await;
    match result {
        Ok(v) => v,
        Err(e) => error_response(format!("write task panicked: {e}")),
    }
}

fn write_blocking(path: &Path, data: &[u8]) -> Value {
    if let Some(parent) = path.parent() {
        if !parent.as_os_str().is_empty() {
            if let Err(e) = std::fs::create_dir_all(parent) {
                return io_error_response(path, e);
            }
        }
    }
    if let Err(e) = std::fs::write(path, data) {
        return io_error_response(path, e);
    }
    json!({
        "success": true,
        "bytes_written": data.len(),
        "path": path.to_string_lossy(),
    })
}

fn error_response(msg: String) -> Value {
    json!({
        "success": false,
        "error": msg,
    })
}

fn io_error_response(path: &Path, e: std::io::Error) -> Value {
    use std::io::ErrorKind;
    match e.kind() {
        ErrorKind::PermissionDenied => {
            error_response(format!("Permission denied: {}", path.display()))
        }
        _ => error_response(e.to_string()),
    }
}

fn format_path_error(e: PathSafetyError) -> String {
    match e {
        PathSafetyError::CwdRequired => "cwd is required".into(),
        PathSafetyError::CwdNotADir(c) => format!("Working directory does not exist: {c}"),
        PathSafetyError::NulByte => "Invalid path: contains NUL byte".into(),
        PathSafetyError::Traversal => "Path traversal not allowed".into(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use tempfile::TempDir;

    fn tmp() -> TempDir {
        tempfile::tempdir().unwrap()
    }
    fn cwd_str(d: &TempDir) -> String {
        d.path().to_string_lossy().into_owned()
    }

    #[tokio::test]
    async fn write_basic() {
        let d = tmp();
        let v = handle_write_file(
            json!({"path": "out.txt", "cwd": cwd_str(&d), "content": "hello"}),
        )
        .await;
        assert_eq!(v["success"], true);
        assert_eq!(v["bytes_written"], 5);
        assert_eq!(fs::read_to_string(d.path().join("out.txt")).unwrap(), "hello");
    }

    #[tokio::test]
    async fn write_creates_parent_dirs() {
        let d = tmp();
        let v = handle_write_file(json!({
            "path": "sub/nested/out.txt",
            "cwd": cwd_str(&d),
            "content": "x",
        }))
        .await;
        assert_eq!(v["success"], true);
        assert!(d.path().join("sub").join("nested").join("out.txt").exists());
    }

    #[tokio::test]
    async fn write_traversal_rejected() {
        let d = tmp();
        let v = handle_write_file(json!({
            "path": "../escape.txt",
            "cwd": cwd_str(&d),
            "content": "x",
        }))
        .await;
        assert_eq!(v["success"], false);
        assert!(v["error"]
            .as_str()
            .unwrap_or("")
            .to_lowercase()
            .contains("traversal"));
    }

    #[tokio::test]
    async fn write_missing_cwd_rejected() {
        let v = handle_write_file(json!({"path": "x", "content": "y"})).await;
        assert_eq!(v["success"], false);
        assert!(v["error"]
            .as_str()
            .unwrap_or("")
            .to_lowercase()
            .contains("cwd"));
    }

    #[tokio::test]
    async fn write_too_large_rejected() {
        let d = tmp();
        let big: String = std::iter::repeat('x')
            .take(MAX_FILE_BYTES + 1)
            .collect();
        let v = handle_write_file(json!({
            "path": "big.txt",
            "cwd": cwd_str(&d),
            "content": big,
        }))
        .await;
        assert_eq!(v["success"], false);
        assert!(v["error"]
            .as_str()
            .unwrap_or("")
            .contains("Content too large"));
    }
}
