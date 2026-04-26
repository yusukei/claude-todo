//! Hard limits shared across handlers. Numbers mirror `agent/main.py:45-53`
//! verbatim — changing them here without coordinating with the Python
//! side breaks parity tests in `agent-rs/08`.

/// Per-stream truncation limit for `exec` stdout/stderr (2 MB).
pub const MAX_OUTPUT_BYTES: usize = 2 * 1024 * 1024;

/// Maximum file size accepted by `read_file` / `write_file` (5 MB).
pub const MAX_FILE_BYTES: usize = 5 * 1024 * 1024;

/// Maximum number of directory entries returned by `list_dir`.
pub const MAX_DIR_ENTRIES: usize = 1000;

/// Maximum number of glob matches returned (used by `agent-rs/04`).
pub const MAX_GLOB_RESULTS: usize = 1000;

/// Default `grep` match cap (used by `agent-rs/05`).
pub const MAX_GREP_RESULTS_DEFAULT: usize = 200;

/// `tree` handler caps (used by `agent-rs/04b`).
pub const MAX_TREE_ENTRIES: usize = 500;
pub const MAX_TREE_DEPTH: usize = 10;

/// Default exec timeout (60s) and hard ceiling (3600s = 1h). Mirrors
/// `agent/main.py:471` (`min(msg.get("timeout", 60), 3600)`).
pub const DEFAULT_EXEC_TIMEOUT_SECS: u64 = 60;
pub const MAX_EXEC_TIMEOUT_SECS: u64 = 3600;
