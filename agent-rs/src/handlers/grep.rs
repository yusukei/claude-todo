//! `grep` — regex search across the workspace.
//!
//! The big technical win of the Rust port: we link in ripgrep's own
//! search libraries (`grep-searcher` + `grep-regex` + `ignore`) so the
//! agent no longer needs an external `rg` binary on PATH. Python could
//! only shell out, which forced operators to install ripgrep separately
//! (and was the source of "rg: not found" errors in production).
//!
//! Behaviour matches `agent/main.py:_grep_with_rg`:
//! - `respect_gitignore=false` (default): `.gitignore` is ignored, but
//!   `GREP_SKIP_DIRS` (vendored dirs like `.git` / `node_modules` / `.venv`)
//!   are pruned via `OverrideBuilder` blacklist.
//! - `respect_gitignore=true`: standard ignore filters apply (.gitignore
//!   etc.); the skip-dir override is not added.
//! - `glob` (e.g. `*.py`) becomes a positive include override.
//! - `case_insensitive` toggles the regex matcher.
//! - `max_results` (1–2000) caps total matches; truncated reported.
//! - `--max-filesize 10M` enforced via `WalkBuilder::max_filesize`.
//!
//! Output JSON shape is preserved from Python (`engine: "ripgrep"` is
//! kept for wire compatibility even though it's now an embedded library).

use std::path::Path;
use std::sync::{Arc, Mutex};

use grep_regex::{RegexMatcher, RegexMatcherBuilder};
use grep_searcher::{Searcher, SearcherBuilder, Sink, SinkMatch};
use ignore::overrides::OverrideBuilder;
use ignore::WalkBuilder;
use serde_json::{json, Value};

use super::constants::MAX_GREP_RESULTS_DEFAULT;
use super::error_payload;
use crate::path_safety::{resolve_safe_path, PathSafetyError};

const HARD_MAX_RESULTS: usize = 2000;
const MAX_FILESIZE: u64 = 10 * 1024 * 1024;
const LINE_TRUNC: usize = 500;

/// Vendored / generated directory names pruned by default. Mirrors
/// `GREP_SKIP_DIRS` at `agent/main.py:1321-1330`.
const SKIP_DIRS: &[&str] = &[
    ".git", ".hg", ".svn",
    "node_modules", "bower_components",
    ".venv", "venv", "env", ".env",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "dist", "build", "target", "out",
    ".next", ".nuxt", ".cache", ".parcel-cache",
    ".idea", ".vscode",
    "coverage", ".nyc_output",
];

pub async fn handle_grep(payload: Value) -> Value {
    let pattern = payload
        .get("pattern")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    let path_input = payload.get("path").and_then(Value::as_str).unwrap_or(".");
    let cwd_input = payload.get("cwd").and_then(Value::as_str);
    let glob_filter = payload
        .get("glob")
        .and_then(Value::as_str)
        .map(str::to_owned);
    let case_insensitive = payload
        .get("case_insensitive")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    let respect_gitignore = payload
        .get("respect_gitignore")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    let max_results = payload
        .get("max_results")
        .and_then(Value::as_u64)
        .unwrap_or(MAX_GREP_RESULTS_DEFAULT as u64) as usize;
    let max_results = max_results.clamp(1, HARD_MAX_RESULTS);

    if pattern.is_empty() {
        return error_payload("pattern is required");
    }
    let base = match resolve_safe_path(path_input, cwd_input) {
        Ok(p) => p,
        Err(e) => return error_payload(format_path_error(e)),
    };
    if !base.exists() {
        return error_payload(format!("Not a directory: {}", base.display()));
    }
    let result = tokio::task::spawn_blocking(move || {
        grep_blocking(
            &base,
            &pattern,
            glob_filter.as_deref(),
            case_insensitive,
            respect_gitignore,
            max_results,
        )
    })
    .await;
    match result {
        Ok(v) => v,
        Err(e) => error_payload(format!("grep task panicked: {e}")),
    }
}

#[derive(Debug, Clone)]
struct Match {
    file: String,
    line: u64,
    text: String,
}

fn grep_blocking(
    base: &Path,
    pattern: &str,
    glob_filter: Option<&str>,
    case_insensitive: bool,
    respect_gitignore: bool,
    max_results: usize,
) -> Value {
    let matcher = match RegexMatcherBuilder::new()
        .case_insensitive(case_insensitive)
        .build(pattern)
    {
        Ok(m) => m,
        Err(e) => return error_payload(format!("Invalid regex: {e}")),
    };

    let mut wb = WalkBuilder::new(base);
    wb.max_filesize(Some(MAX_FILESIZE));
    if respect_gitignore {
        // Default is standard_filters(true) which honours .gitignore, .ignore,
        // hidden files, etc. Same as ripgrep's default.
        if let Some(g) = glob_filter {
            let mut ovb = OverrideBuilder::new(base);
            // Best-effort: ignore pattern errors so a malformed glob
            // surfaces only as "no matches" rather than a hard failure.
            let _ = ovb.add(g);
            if let Ok(o) = ovb.build() {
                wb.overrides(o);
            }
        }
    } else {
        // Skip the standard filters but explicitly prune vendored dirs.
        wb.standard_filters(false);
        let mut ovb = OverrideBuilder::new(base);
        for skip in SKIP_DIRS {
            let _ = ovb.add(&format!("!{skip}"));
            let _ = ovb.add(&format!("!**/{skip}/**"));
        }
        if let Some(g) = glob_filter {
            let _ = ovb.add(g);
        }
        if let Ok(o) = ovb.build() {
            wb.overrides(o);
        }
    }

    let matches: Arc<Mutex<Vec<Match>>> = Arc::new(Mutex::new(Vec::new()));
    let files_scanned = Arc::new(Mutex::new(0usize));
    let truncated_flag = Arc::new(Mutex::new(false));

    for entry in wb.build().flatten() {
        let path = entry.path().to_path_buf();
        // Skip directories; only files contribute matches.
        let is_file = entry
            .file_type()
            .map(|t| t.is_file())
            .unwrap_or(false);
        if !is_file {
            continue;
        }
        // Note: even if we go on to truncate, we still count files we
        // *would* have scanned so the operator sees coverage.
        *files_scanned.lock().unwrap() += 1;

        // Early exit if we've already reached the cap.
        if matches.lock().unwrap().len() >= max_results {
            *truncated_flag.lock().unwrap() = true;
            break;
        }

        if let Err(e) = search_one_file(&matcher, &path, &matches, max_results, &truncated_flag)
        {
            tracing::debug!(error = %e, path = %path.display(), "grep search_one failed");
        }
    }

    let mut matches = Arc::try_unwrap(matches)
        .unwrap_or_else(|arc| Mutex::new(arc.lock().unwrap().clone()))
        .into_inner()
        .unwrap();
    matches.sort_by(|a, b| a.file.cmp(&b.file).then_with(|| a.line.cmp(&b.line)));

    let count = matches.len();
    let files_scanned = *files_scanned.lock().unwrap();
    let truncated = *truncated_flag.lock().unwrap();

    let mat_json: Vec<Value> = matches
        .into_iter()
        .map(|m| {
            // Use `file` (relative to base where possible) for parity
            // with ripgrep's --json shape, which prints the path the
            // walker yielded.
            json!({
                "file": m.file,
                "line": m.line,
                "text": m.text,
            })
        })
        .collect();

    json!({
        "matches": mat_json,
        "count": count,
        "files_scanned": files_scanned,
        "truncated": truncated,
        // Wire-compat: stays "ripgrep" so MCP clients depending on the
        // engine string don't break. The library is the same code as
        // the rg binary, just statically linked.
        "engine": "ripgrep",
    })
}

fn search_one_file(
    matcher: &RegexMatcher,
    path: &Path,
    matches: &Arc<Mutex<Vec<Match>>>,
    max_results: usize,
    truncated_flag: &Arc<Mutex<bool>>,
) -> std::io::Result<()> {
    let mut searcher = SearcherBuilder::new().line_number(true).build();
    let path_str = path.to_string_lossy().into_owned();
    let mut sink = CollectSink {
        matches: matches.clone(),
        truncated_flag: truncated_flag.clone(),
        max_results,
        file_path: path_str,
    };
    searcher.search_path(matcher, path, &mut sink)?;
    Ok(())
}

struct CollectSink {
    matches: Arc<Mutex<Vec<Match>>>,
    truncated_flag: Arc<Mutex<bool>>,
    max_results: usize,
    file_path: String,
}

impl Sink for CollectSink {
    type Error = std::io::Error;

    fn matched(
        &mut self,
        _searcher: &Searcher,
        m: &SinkMatch,
    ) -> Result<bool, std::io::Error> {
        let mut guard = self.matches.lock().unwrap();
        if guard.len() >= self.max_results {
            *self.truncated_flag.lock().unwrap() = true;
            return Ok(false); // stop searching this file
        }
        let line = m.line_number().unwrap_or(0);
        // Bytes may be invalid UTF-8 — lossy decode + truncate to 500
        // chars (Python parity). Strip trailing \r\n.
        let raw = m.bytes();
        let lossy = String::from_utf8_lossy(raw);
        let trimmed = lossy.trim_end_matches(['\r', '\n']);
        let text = if trimmed.chars().count() > LINE_TRUNC {
            let truncated: String = trimmed.chars().take(LINE_TRUNC).collect();
            truncated
        } else {
            trimmed.to_string()
        };
        guard.push(Match {
            file: self.file_path.clone(),
            line,
            text,
        });
        Ok(true)
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

    fn build_repo(d: &TempDir) {
        fs::write(d.path().join("a.py"), "import os\nprint('hello world')\n").unwrap();
        fs::write(d.path().join("b.rs"), "fn main() { println!(\"hello\"); }\n").unwrap();
        fs::write(d.path().join("notes.txt"), "todo: nothing\n").unwrap();
        fs::create_dir(d.path().join("sub")).unwrap();
        fs::write(d.path().join("sub").join("nested.py"), "print('nested')\n").unwrap();
        // Vendored dirs that should be skipped by default.
        fs::create_dir(d.path().join(".git")).unwrap();
        fs::write(
            d.path().join(".git").join("HEAD"),
            "ref: refs/heads/main\n",
        )
        .unwrap();
        fs::create_dir(d.path().join("node_modules")).unwrap();
        fs::write(
            d.path().join("node_modules").join("pkg"),
            "secret-token-found\n",
        )
        .unwrap();
    }

    #[tokio::test]
    async fn grep_basic_match() {
        let d = tmp();
        build_repo(&d);
        let v = handle_grep(json!({
            "pattern": "hello",
            "path": ".",
            "cwd": cwd_str(&d),
        }))
        .await;
        let count = v["count"].as_u64().unwrap();
        assert!(count >= 2, "expected ≥2 matches, got {count}: {v:?}");
        let files: Vec<&str> = v["matches"]
            .as_array()
            .unwrap()
            .iter()
            .map(|m| m["file"].as_str().unwrap())
            .collect();
        assert!(files.iter().any(|f| f.ends_with("a.py")));
        assert!(files.iter().any(|f| f.ends_with("b.rs")));
        assert_eq!(v["engine"], "ripgrep");
    }

    #[tokio::test]
    async fn grep_skips_vendored_dirs_by_default() {
        let d = tmp();
        build_repo(&d);
        let v = handle_grep(json!({
            "pattern": "secret-token",
            "path": ".",
            "cwd": cwd_str(&d),
        }))
        .await;
        // node_modules should be excluded → no match
        assert_eq!(v["count"], 0, "{v:?}");
    }

    #[tokio::test]
    async fn grep_glob_filter() {
        let d = tmp();
        build_repo(&d);
        let v = handle_grep(json!({
            "pattern": "hello",
            "path": ".",
            "cwd": cwd_str(&d),
            "glob": "*.py",
        }))
        .await;
        // a.py contains "hello world", b.rs not via glob
        let files: Vec<&str> = v["matches"]
            .as_array()
            .unwrap()
            .iter()
            .map(|m| m["file"].as_str().unwrap())
            .collect();
        assert!(files.iter().any(|f| f.ends_with("a.py")));
        assert!(!files.iter().any(|f| f.ends_with("b.rs")));
    }

    #[tokio::test]
    async fn grep_case_insensitive() {
        let d = tmp();
        fs::write(d.path().join("c.txt"), "FOO\nbar\nFoo\n").unwrap();
        let v = handle_grep(json!({
            "pattern": "foo",
            "path": ".",
            "cwd": cwd_str(&d),
            "case_insensitive": true,
        }))
        .await;
        assert_eq!(v["count"], 2);
    }

    #[tokio::test]
    async fn grep_max_results_truncates() {
        let d = tmp();
        // 50 lines, all containing "x"
        let content: String =
            std::iter::repeat("x line\n").take(50).collect();
        fs::write(d.path().join("many.txt"), content).unwrap();
        let v = handle_grep(json!({
            "pattern": "x",
            "path": ".",
            "cwd": cwd_str(&d),
            "max_results": 10,
        }))
        .await;
        assert_eq!(v["count"], 10);
        assert_eq!(v["truncated"], true);
    }

    #[tokio::test]
    async fn grep_invalid_regex_rejected() {
        let d = tmp();
        let v = handle_grep(json!({
            "pattern": "[invalid(",
            "path": ".",
            "cwd": cwd_str(&d),
        }))
        .await;
        assert!(v["error"]
            .as_str()
            .unwrap_or("")
            .contains("Invalid regex"));
    }

    #[tokio::test]
    async fn grep_pattern_required() {
        let d = tmp();
        let v = handle_grep(json!({
            "pattern": "",
            "path": ".",
            "cwd": cwd_str(&d),
        }))
        .await;
        assert!(v["error"]
            .as_str()
            .unwrap_or("")
            .contains("required"));
    }

    #[tokio::test]
    async fn grep_traversal_rejected() {
        let d = tmp();
        let sub = d.path().join("sub");
        fs::create_dir(&sub).unwrap();
        let v = handle_grep(json!({
            "pattern": "x",
            "path": "..",
            "cwd": sub.to_string_lossy(),
        }))
        .await;
        assert!(v["error"]
            .as_str()
            .unwrap_or("")
            .to_lowercase()
            .contains("traversal"));
    }

    #[tokio::test]
    async fn grep_invalid_utf8_does_not_crash() {
        let d = tmp();
        // Mix of ASCII + invalid bytes around the match.
        let mut content = b"prefix\n".to_vec();
        content.extend_from_slice(b"FOOBAR\xff\xfe\n");
        content.extend_from_slice(b"suffix\n");
        fs::write(d.path().join("bad.bin"), &content).unwrap();
        let v = handle_grep(json!({
            "pattern": "FOOBAR",
            "path": ".",
            "cwd": cwd_str(&d),
        }))
        .await;
        // Either the file is searched and matched, or skipped due to
        // binary detection. Both are acceptable; what we don't accept
        // is a panic.
        assert!(v.get("matches").is_some());
    }
}
