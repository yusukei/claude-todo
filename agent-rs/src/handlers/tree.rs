//! `tree` — bounded recursive directory listing with default vendored-dir
//! exclusion. Mirrors `agent/main.py:1005-1075` (handler) and
//! `_tree_collect_children` (recursive walker).
//!
//! Hard caps:
//! - `depth ≤ MAX_TREE_DEPTH` (10)
//! - `max_entries ≤ MAX_TREE_ENTRIES` (500)
//!
//! Default `exclude` is `GREP_SKIP_DIRS` (.git / node_modules / .venv /
//! target / etc) so a `tree` on a real project doesn't drown in
//! vendored crap. Caller can extend with extra dir names.

use std::collections::HashSet;
use std::path::{Path, PathBuf};

use serde_json::{json, Value};

use super::constants::{MAX_TREE_DEPTH, MAX_TREE_ENTRIES};
use super::error_payload;
use crate::path_safety::{resolve_safe_path, PathSafetyError};

/// Universally-vendored directory names. Mirrors `GREP_SKIP_DIRS`
/// at `agent/main.py:1321-1330`.
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

pub async fn handle_tree(payload: Value) -> Value {
    let path_input = payload.get("path").and_then(Value::as_str).unwrap_or(".");
    let cwd_input = payload.get("cwd").and_then(Value::as_str);
    let depth_in = payload.get("depth").and_then(Value::as_i64).unwrap_or(2);
    if depth_in < 0 {
        return error_payload("depth must be >= 0");
    }
    let depth = (depth_in as usize).min(MAX_TREE_DEPTH);

    let max_entries_in = payload
        .get("max_entries")
        .and_then(Value::as_i64)
        .unwrap_or(MAX_TREE_ENTRIES as i64);
    if max_entries_in <= 0 {
        return error_payload("max_entries must be > 0");
    }
    let max_entries = (max_entries_in as usize).min(MAX_TREE_ENTRIES);
    let show_sizes = payload
        .get("show_sizes")
        .and_then(Value::as_bool)
        .unwrap_or(false);

    let mut exclude_set: HashSet<String> =
        SKIP_DIRS.iter().map(|s| (*s).to_string()).collect();
    match payload.get("exclude") {
        None | Some(Value::Null) => {}
        Some(Value::Array(arr)) => {
            for v in arr {
                if let Some(s) = v.as_str() {
                    exclude_set.insert(s.to_string());
                }
            }
        }
        Some(_) => return error_payload("exclude must be a list of strings"),
    }

    let base = match resolve_safe_path(path_input, cwd_input) {
        Ok(p) => p,
        Err(e) => return error_payload(format_path_error(e)),
    };

    let result = tokio::task::spawn_blocking(move || {
        tree_blocking(base, depth, max_entries, exclude_set, show_sizes)
    })
    .await;
    match result {
        Ok(v) => v,
        Err(e) => error_payload(format!("tree task panicked: {e}")),
    }
}

fn tree_blocking(
    base: PathBuf,
    depth: usize,
    max_entries: usize,
    exclude: HashSet<String>,
    show_sizes: bool,
) -> Value {
    if !base.is_dir() {
        return error_payload(format!("Directory not found: {}", base.display()));
    }
    let mut counter = 0usize;
    let mut truncated = false;
    let root_name = base
        .file_name()
        .map(|n| n.to_string_lossy().into_owned())
        .unwrap_or_else(|| base.to_string_lossy().into_owned());
    let mut root = json!({"name": root_name, "type": "dir"});
    let children = collect_children(
        &base,
        depth,
        max_entries,
        &exclude,
        show_sizes,
        &mut counter,
        &mut truncated,
    );
    if !children.is_empty() {
        root.as_object_mut()
            .unwrap()
            .insert("children".into(), Value::Array(children));
    }
    json!({
        "root": root,
        "path": base.to_string_lossy(),
        "depth": depth,
        "total_entries": counter,
        "truncated": truncated,
    })
}

fn collect_children(
    path: &Path,
    remaining_depth: usize,
    max_entries: usize,
    exclude: &HashSet<String>,
    show_sizes: bool,
    counter: &mut usize,
    truncated: &mut bool,
) -> Vec<Value> {
    if remaining_depth == 0 {
        return Vec::new();
    }
    let mut entries: Vec<std::fs::DirEntry> = match std::fs::read_dir(path) {
        Ok(rd) => rd.filter_map(Result::ok).collect(),
        Err(_) => return Vec::new(),
    };
    // Dirs first, then by lowercased name.
    entries.sort_by(|a, b| {
        let a_dir = a.file_type().map(|t| t.is_dir()).unwrap_or(false);
        let b_dir = b.file_type().map(|t| t.is_dir()).unwrap_or(false);
        match (a_dir, b_dir) {
            (true, false) => std::cmp::Ordering::Less,
            (false, true) => std::cmp::Ordering::Greater,
            _ => a
                .file_name()
                .to_string_lossy()
                .to_lowercase()
                .cmp(&b.file_name().to_string_lossy().to_lowercase()),
        }
    });

    let mut children = Vec::new();
    for entry in entries {
        if *counter >= max_entries {
            *truncated = true;
            break;
        }
        let name = entry.file_name().to_string_lossy().into_owned();
        if exclude.contains(&name) {
            continue;
        }
        *counter += 1;
        let ftype = match entry.file_type() {
            Ok(t) => t,
            Err(_) => continue,
        };
        if ftype.is_dir() {
            let mut node = json!({"name": name, "type": "dir"});
            let grand = collect_children(
                &entry.path(),
                remaining_depth - 1,
                max_entries,
                exclude,
                show_sizes,
                counter,
                truncated,
            );
            if !grand.is_empty() {
                node.as_object_mut()
                    .unwrap()
                    .insert("children".into(), Value::Array(grand));
            }
            children.push(node);
        } else {
            let typ = if ftype.is_symlink() { "symlink" } else { "file" };
            let mut node = json!({"name": name, "type": typ});
            if show_sizes && !ftype.is_symlink() {
                if let Ok(meta) = entry.metadata() {
                    node.as_object_mut()
                        .unwrap()
                        .insert("size".into(), json!(meta.len()));
                }
            }
            children.push(node);
        }
    }
    children
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

    fn build_tree(d: &TempDir) {
        fs::create_dir(d.path().join("sub")).unwrap();
        fs::write(d.path().join("sub").join("a.txt"), "1").unwrap();
        fs::create_dir(d.path().join("sub").join("nest")).unwrap();
        fs::write(d.path().join("sub").join("nest").join("b.txt"), "2").unwrap();
        fs::write(d.path().join("top.txt"), "x").unwrap();
        // Vendored dirs that should be skipped by default.
        fs::create_dir(d.path().join(".git")).unwrap();
        fs::write(d.path().join(".git").join("HEAD"), "ref").unwrap();
        fs::create_dir(d.path().join("node_modules")).unwrap();
        fs::write(
            d.path().join("node_modules").join("pkg.json"),
            "{}",
        )
        .unwrap();
    }

    #[tokio::test]
    async fn tree_default_depth_2_skips_vendored() {
        let d = tmp();
        build_tree(&d);
        let v = handle_tree(json!({"path": ".", "cwd": cwd_str(&d)})).await;
        // depth=2 should reach sub/a.txt and sub/nest/, but not into nest's children.
        let root = &v["root"];
        assert_eq!(root["type"], "dir");
        let names: Vec<String> = root["children"]
            .as_array()
            .unwrap()
            .iter()
            .map(|c| c["name"].as_str().unwrap().to_string())
            .collect();
        // Vendored dirs filtered out
        assert!(!names.iter().any(|n| n == ".git"));
        assert!(!names.iter().any(|n| n == "node_modules"));
        // Real entries present
        assert!(names.contains(&"sub".to_string()));
        assert!(names.contains(&"top.txt".to_string()));
    }

    #[tokio::test]
    async fn tree_depth_one_no_descent() {
        let d = tmp();
        build_tree(&d);
        let v = handle_tree(json!({
            "path": ".",
            "cwd": cwd_str(&d),
            "depth": 1,
        }))
        .await;
        let sub_node = v["root"]["children"]
            .as_array()
            .unwrap()
            .iter()
            .find(|c| c["name"] == "sub")
            .unwrap()
            .clone();
        // depth=1 → "sub" is included but its children not expanded
        assert_eq!(sub_node["type"], "dir");
        assert!(sub_node.get("children").is_none());
    }

    #[tokio::test]
    async fn tree_depth_three_descends_fully() {
        let d = tmp();
        build_tree(&d);
        let v = handle_tree(json!({
            "path": ".",
            "cwd": cwd_str(&d),
            "depth": 3,
        }))
        .await;
        let sub_node = v["root"]["children"]
            .as_array()
            .unwrap()
            .iter()
            .find(|c| c["name"] == "sub")
            .unwrap()
            .clone();
        let nest = sub_node["children"]
            .as_array()
            .unwrap()
            .iter()
            .find(|c| c["name"] == "nest")
            .unwrap()
            .clone();
        assert_eq!(nest["children"][0]["name"], "b.txt");
    }

    #[tokio::test]
    async fn tree_extra_exclude() {
        let d = tmp();
        build_tree(&d);
        let v = handle_tree(json!({
            "path": ".",
            "cwd": cwd_str(&d),
            "exclude": ["sub"],
        }))
        .await;
        let names: Vec<&str> = v["root"]["children"]
            .as_array()
            .unwrap()
            .iter()
            .map(|c| c["name"].as_str().unwrap())
            .collect();
        assert!(!names.contains(&"sub"));
        assert!(names.contains(&"top.txt"));
    }

    #[tokio::test]
    async fn tree_max_entries_truncates() {
        let d = tmp();
        for i in 0..10 {
            fs::write(d.path().join(format!("f{i:02}.txt")), "x").unwrap();
        }
        let v = handle_tree(json!({
            "path": ".",
            "cwd": cwd_str(&d),
            "max_entries": 3,
        }))
        .await;
        assert_eq!(v["truncated"], true);
        assert_eq!(v["total_entries"], 3);
    }

    #[tokio::test]
    async fn tree_show_sizes() {
        let d = tmp();
        fs::write(d.path().join("size.txt"), "12345").unwrap();
        let v = handle_tree(json!({
            "path": ".",
            "cwd": cwd_str(&d),
            "show_sizes": true,
        }))
        .await;
        let file = v["root"]["children"]
            .as_array()
            .unwrap()
            .iter()
            .find(|c| c["name"] == "size.txt")
            .unwrap()
            .clone();
        assert_eq!(file["size"], 5);
    }

    #[tokio::test]
    async fn tree_dirs_first_then_alpha() {
        let d = tmp();
        fs::create_dir(d.path().join("zz_dir")).unwrap();
        fs::write(d.path().join("aa.txt"), "x").unwrap();
        fs::write(d.path().join("bb.txt"), "x").unwrap();
        let v = handle_tree(json!({"path": ".", "cwd": cwd_str(&d)})).await;
        let names: Vec<&str> = v["root"]["children"]
            .as_array()
            .unwrap()
            .iter()
            .map(|c| c["name"].as_str().unwrap())
            .collect();
        assert_eq!(names, vec!["zz_dir", "aa.txt", "bb.txt"]);
    }

    #[tokio::test]
    async fn tree_traversal_rejected() {
        let d = tmp();
        let sub = d.path().join("sub");
        fs::create_dir(&sub).unwrap();
        let v = handle_tree(json!({
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
}
