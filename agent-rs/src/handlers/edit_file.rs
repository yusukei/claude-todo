//! `edit_file` — verbatim string replacement in a UTF-8 text file.
//!
//! Python parity (`agent/main.py:805-890`):
//! - `old_string` is required and must differ from `new_string`
//! - With `replace_all=false` (default), exactly one match is required;
//!   ambiguous matches return an error listing the line numbers
//! - When 0 matches are found, returns up to 3 "nearest candidate"
//!   lines using a similarity heuristic (we approximate Python's
//!   `difflib.get_close_matches` with normalized Jaro-Winkler — same
//!   shape, slightly different scoring)

use std::path::Path;

use serde_json::{json, Value};

use super::constants::MAX_FILE_BYTES;
use crate::path_safety::{resolve_safe_path, PathSafetyError};

const NEAREST_TOP_K: usize = 3;
const NEAREST_CUTOFF: f64 = 0.4;
const MATCH_LINES_CAP: usize = 20;
const CANDIDATE_DISPLAY_LEN: usize = 120;

pub async fn handle_edit_file(payload: Value) -> Value {
    let path_input = payload.get("path").and_then(Value::as_str).unwrap_or("");
    let cwd_input = payload.get("cwd").and_then(Value::as_str);
    let old_string = payload
        .get("old_string")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    let new_string = payload
        .get("new_string")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    let replace_all = payload
        .get("replace_all")
        .and_then(Value::as_bool)
        .unwrap_or(false);

    if old_string.is_empty() {
        return error_response("old_string is required");
    }
    if old_string == new_string {
        return error_response("old_string and new_string must differ");
    }

    let resolved = match resolve_safe_path(path_input, cwd_input) {
        Ok(p) => p,
        Err(e) => return error_response(format_path_error(e)),
    };
    let resolved_for_blocking = resolved.clone();

    let result = tokio::task::spawn_blocking(move || {
        edit_blocking(&resolved_for_blocking, &old_string, &new_string, replace_all)
    })
    .await;
    match result {
        Ok(v) => v,
        Err(e) => error_response(format!("edit task panicked: {e}")),
    }
}

fn edit_blocking(
    path: &Path,
    old_string: &str,
    new_string: &str,
    replace_all: bool,
) -> Value {
    let meta = match std::fs::symlink_metadata(path) {
        Ok(m) => m,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
            return error_response(format!("File not found: {}", path.display()));
        }
        Err(e) => return error_response(e.to_string()),
    };
    if !meta.is_file() {
        return error_response(format!("File not found: {}", path.display()));
    }
    let size = meta.len() as usize;
    if size > MAX_FILE_BYTES {
        return error_response(format!(
            "File too large: {size} bytes (max {} MB)",
            MAX_FILE_BYTES / 1024 / 1024
        ));
    }

    let bytes = match std::fs::read(path) {
        Ok(b) => b,
        Err(e) => return error_response(e.to_string()),
    };
    let content = match String::from_utf8(bytes) {
        Ok(s) => s,
        Err(_) => {
            return error_response(format!("File is not valid UTF-8: {}", path.display()));
        }
    };

    let count = content.matches(old_string).count();
    if count == 0 {
        let candidates = nearest_candidates(&content, old_string);
        if candidates.is_empty() {
            return error_response(format!(
                "old_string not found in {} (no near matches).",
                path.display()
            ));
        }
        let hints = candidates
            .iter()
            .map(|(ln, line)| format!("  L{ln}: {}", format_candidate(line)))
            .collect::<Vec<_>>()
            .join("\n");
        return error_response(format!(
            "old_string not found in {}. Nearest candidates:\n{hints}",
            path.display()
        ));
    }
    if !replace_all && count > 1 {
        let line_numbers = match_line_numbers(&content, old_string);
        let mut preview = line_numbers
            .iter()
            .map(|n| n.to_string())
            .collect::<Vec<_>>()
            .join(", ");
        if count > line_numbers.len() {
            preview.push_str(&format!(", … ({} more)", count - line_numbers.len()));
        }
        return error_response(format!(
            "old_string is not unique — found {count} occurrences in {}: lines {preview}. \
             Provide more surrounding context to make it unique, or set replace_all=true.",
            path.display()
        ));
    }

    let new_content = if replace_all {
        content.replace(old_string, new_string)
    } else {
        content.replacen(old_string, new_string, 1)
    };
    if let Err(e) = std::fs::write(path, new_content.as_bytes()) {
        return error_response(e.to_string());
    }
    let replacements = if replace_all { count } else { 1 };
    json!({
        "success": true,
        "path": path.to_string_lossy(),
        "replacements": replacements,
    })
}

/// Return 1-based line numbers where `needle` first occurs, capped at
/// `MATCH_LINES_CAP` so the error stays bounded.
fn match_line_numbers(content: &str, needle: &str) -> Vec<usize> {
    if needle.is_empty() {
        return Vec::new();
    }
    let mut out = Vec::new();
    let mut pos = 0;
    let step = needle.len().max(1);
    while out.len() < MATCH_LINES_CAP {
        let Some(idx) = content[pos..].find(needle) else {
            break;
        };
        let abs = pos + idx;
        let line_no = content[..abs].matches('\n').count() + 1;
        out.push(line_no);
        pos = abs + step;
    }
    out
}

/// Find the best-matching lines in `content` for the first non-empty
/// line of `needle`. Approximation of Python's
/// `difflib.get_close_matches(needle_first, content_lines, n=3, cutoff=0.4)`.
fn nearest_candidates(content: &str, needle: &str) -> Vec<(usize, String)> {
    let needle_first = needle
        .lines()
        .find(|l| !l.trim().is_empty())
        .unwrap_or_else(|| needle.trim())
        .to_string();
    if needle_first.is_empty() {
        return Vec::new();
    }
    let mut numbered: Vec<(usize, &str)> = content
        .lines()
        .enumerate()
        .filter(|(_, l)| !l.trim().is_empty())
        .map(|(i, l)| (i + 1, l))
        .collect();
    if numbered.is_empty() {
        return Vec::new();
    }
    numbered.sort_by(|a, b| {
        let sa = strsim::normalized_levenshtein(&needle_first, a.1);
        let sb = strsim::normalized_levenshtein(&needle_first, b.1);
        sb.partial_cmp(&sa).unwrap_or(std::cmp::Ordering::Equal)
    });
    numbered
        .into_iter()
        .filter(|(_, l)| {
            strsim::normalized_levenshtein(&needle_first, l) >= NEAREST_CUTOFF
        })
        .take(NEAREST_TOP_K)
        .map(|(n, l)| (n, l.to_string()))
        .collect()
}

fn format_candidate(line: &str) -> String {
    let mut s = line.replace('\t', "    ");
    while s.ends_with('\r') || s.ends_with('\n') {
        s.pop();
    }
    if s.chars().count() > CANDIDATE_DISPLAY_LEN {
        // Char-aware truncate to avoid splitting multibyte sequences.
        let truncated: String = s.chars().take(CANDIDATE_DISPLAY_LEN).collect();
        return format!("{truncated}…");
    }
    s
}

fn error_response(msg: impl Into<String>) -> Value {
    json!({
        "success": false,
        "error": msg.into(),
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
    async fn edit_unique_replacement() {
        let d = tmp();
        fs::write(d.path().join("f.txt"), "hello world\nfoo bar\n").unwrap();
        let v = handle_edit_file(json!({
            "path": "f.txt",
            "cwd": cwd_str(&d),
            "old_string": "foo bar",
            "new_string": "FOO BAR",
        }))
        .await;
        assert_eq!(v["success"], true);
        assert_eq!(v["replacements"], 1);
        assert_eq!(
            fs::read_to_string(d.path().join("f.txt")).unwrap(),
            "hello world\nFOO BAR\n"
        );
    }

    #[tokio::test]
    async fn edit_ambiguous_without_replace_all_rejected() {
        let d = tmp();
        fs::write(
            d.path().join("dup.txt"),
            "x\nfoo\ny\nfoo\nz\n",
        )
        .unwrap();
        let v = handle_edit_file(json!({
            "path": "dup.txt",
            "cwd": cwd_str(&d),
            "old_string": "foo",
            "new_string": "BAR",
        }))
        .await;
        assert_eq!(v["success"], false);
        let err = v["error"].as_str().unwrap();
        assert!(err.contains("not unique"), "err={err}");
        assert!(err.contains("found 2"), "err={err}");
    }

    #[tokio::test]
    async fn edit_replace_all() {
        let d = tmp();
        fs::write(d.path().join("dup.txt"), "x\nfoo\ny\nfoo\nz\n").unwrap();
        let v = handle_edit_file(json!({
            "path": "dup.txt",
            "cwd": cwd_str(&d),
            "old_string": "foo",
            "new_string": "BAR",
            "replace_all": true,
        }))
        .await;
        assert_eq!(v["success"], true);
        assert_eq!(v["replacements"], 2);
        assert_eq!(
            fs::read_to_string(d.path().join("dup.txt")).unwrap(),
            "x\nBAR\ny\nBAR\nz\n"
        );
    }

    #[tokio::test]
    async fn edit_no_match_with_near_candidates() {
        let d = tmp();
        fs::write(d.path().join("close.txt"), "let foo = 1;\nlet bar = 2;\n")
            .unwrap();
        let v = handle_edit_file(json!({
            "path": "close.txt",
            "cwd": cwd_str(&d),
            "old_string": "let foo = 100;",
            "new_string": "let foo = 9;",
        }))
        .await;
        assert_eq!(v["success"], false);
        let err = v["error"].as_str().unwrap();
        assert!(err.contains("Nearest candidates"), "err={err}");
        assert!(err.contains("L1: let foo = 1;"), "err={err}");
    }

    #[tokio::test]
    async fn edit_no_match_no_candidates() {
        let d = tmp();
        fs::write(d.path().join("nope.txt"), "abc\ndef\n").unwrap();
        let v = handle_edit_file(json!({
            "path": "nope.txt",
            "cwd": cwd_str(&d),
            "old_string": "completely-unrelated-text-1234567890",
            "new_string": "x",
        }))
        .await;
        assert_eq!(v["success"], false);
        let err = v["error"].as_str().unwrap();
        assert!(err.contains("not found") || err.contains("Nearest candidates"));
    }

    #[tokio::test]
    async fn edit_old_string_required() {
        let d = tmp();
        fs::write(d.path().join("f.txt"), "x").unwrap();
        let v = handle_edit_file(json!({
            "path": "f.txt",
            "cwd": cwd_str(&d),
            "old_string": "",
            "new_string": "y",
        }))
        .await;
        assert_eq!(v["success"], false);
        assert!(v["error"]
            .as_str()
            .unwrap()
            .contains("old_string is required"));
    }

    #[tokio::test]
    async fn edit_old_eq_new_rejected() {
        let d = tmp();
        fs::write(d.path().join("f.txt"), "abc").unwrap();
        let v = handle_edit_file(json!({
            "path": "f.txt",
            "cwd": cwd_str(&d),
            "old_string": "abc",
            "new_string": "abc",
        }))
        .await;
        assert_eq!(v["success"], false);
        assert!(v["error"].as_str().unwrap().contains("must differ"));
    }

    #[tokio::test]
    async fn edit_invalid_utf8_rejected() {
        let d = tmp();
        fs::write(d.path().join("bad.txt"), [0xff, b'a', b'b']).unwrap();
        let v = handle_edit_file(json!({
            "path": "bad.txt",
            "cwd": cwd_str(&d),
            "old_string": "ab",
            "new_string": "xy",
        }))
        .await;
        assert_eq!(v["success"], false);
        assert!(v["error"].as_str().unwrap().contains("not valid UTF-8"));
    }

    #[tokio::test]
    async fn edit_traversal_rejected() {
        let d = tmp();
        let v = handle_edit_file(json!({
            "path": "../escape.txt",
            "cwd": cwd_str(&d),
            "old_string": "x",
            "new_string": "y",
        }))
        .await;
        assert_eq!(v["success"], false);
        assert!(v["error"]
            .as_str()
            .unwrap()
            .to_lowercase()
            .contains("traversal"));
    }
}
