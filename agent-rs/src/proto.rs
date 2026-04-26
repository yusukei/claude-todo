//! Wire format for the agent ↔ backend WebSocket.
//!
//! The Python agent's frames are the contract; serde shapes here must
//! match what `backend/app/api/v1/endpoints/workspaces/websocket.py`
//! parses. Tests pin the JSON shape so any drift fails locally.
//!
//! ## Envelope shape (since 2026-04-08)
//!
//! Both request and response frames carry `{type, request_id, payload}`
//! where `payload` is an arbitrary JSON object. Putting handler data
//! under `payload` (rather than at the top level) is what guarantees
//! handlers can never shadow envelope fields like `type` or
//! `request_id`. See `agent/main.py:_run_handler` (line ~2619) for the
//! Python equivalent.
//!
//! ## Scope
//! - outgoing: `auth`, `agent_info`, `ping`, `<response_type>` (handler reply)
//! - incoming: `auth_ok`, `auth_error`, `pong`, `update_available`,
//!   `<request_type>` handler RPC (mapped to [`Incoming::Request`]).

use serde::{Deserialize, Serialize};
use serde_json::Value;

/// Frames the agent sends to the backend. Type-tagged on the `type`
/// field, with payload fields flattened to the top of the JSON object
/// (matches Python's `json.dumps({"type": ..., **fields})` shape).
#[derive(Debug, Clone, Serialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum Outgoing {
    Auth {
        token: String,
    },
    AgentInfo {
        hostname: String,
        host_id: String,
        /// `win32` / `linux` / `darwin` (matches Python `sys.platform`).
        os: String,
        shells: Vec<String>,
        agent_version: String,
    },
    Ping,
}

/// Handler response envelope. Serialized as `{type, request_id, payload}`
/// to match Python's dispatcher (`_run_handler` in `agent/main.py`).
/// Kept separate from [`Outgoing`] because the `type` field here is
/// dynamic (per-handler), not a fixed enum variant — serde's tagged
/// enum can't model that directly.
#[derive(Debug, Clone, Serialize)]
pub struct Response<'a> {
    #[serde(rename = "type")]
    pub response_type: &'a str,
    pub request_id: Option<String>,
    pub payload: Value,
}

/// Frames the agent receives from the backend.
#[derive(Debug, Clone, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum Incoming {
    AuthOk {
        agent_id: String,
    },
    AuthError {
        #[serde(default)]
        message: Option<String>,
    },
    Pong,
    /// Pushed by the backend when a newer release is available for
    /// this agent's OS/arch/channel. Handled in agent-rs/07.
    UpdateAvailable {
        #[serde(default)]
        version: Option<String>,
        #[serde(default)]
        download_url: Option<String>,
        #[serde(default)]
        sha256: Option<String>,
    },
    /// Anything else (handler RPCs etc.). PoC just logs and skips —
    /// concrete handlers land in 03..07.
    #[serde(other)]
    Other,
}

/// Generic request envelope used by handler RPCs. Captured separately
/// from [`Incoming`] because `Incoming`'s `#[serde(other)]` arm is
/// field-free — we need the original `type`, `request_id`, and
/// `payload` to dispatch. The two layers are tried in order on each
/// inbound frame: typed `Incoming` first (auth/heartbeat/update),
/// falling back to [`RequestEnvelope`] for handler RPCs.
#[derive(Debug, Clone, Deserialize)]
pub struct RequestEnvelope {
    #[serde(rename = "type")]
    pub request_type: String,
    #[serde(default)]
    pub request_id: Option<String>,
    /// Inner data dict. Defaults to `{}` so handlers don't need to
    /// special-case missing payload.
    #[serde(default = "empty_object")]
    pub payload: Value,
}

fn empty_object() -> Value {
    Value::Object(Default::default())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn auth_serializes_with_type_field() {
        let s = serde_json::to_string(&Outgoing::Auth { token: "tok".into() }).unwrap();
        let v: serde_json::Value = serde_json::from_str(&s).unwrap();
        assert_eq!(v["type"], "auth");
        assert_eq!(v["token"], "tok");
    }

    #[test]
    fn ping_serializes_to_type_only() {
        let s = serde_json::to_string(&Outgoing::Ping).unwrap();
        assert_eq!(s, r#"{"type":"ping"}"#);
    }

    #[test]
    fn agent_info_fields_at_top_level() {
        let frame = Outgoing::AgentInfo {
            hostname: "h".into(),
            host_id: "abc1234567890def".into(),
            os: "darwin".into(),
            shells: vec!["bash".into(), "zsh".into()],
            agent_version: "0.6.0-dev".into(),
        };
        let v: serde_json::Value = serde_json::to_value(&frame).unwrap();
        assert_eq!(v["type"], "agent_info");
        assert_eq!(v["hostname"], "h");
        assert_eq!(v["host_id"], "abc1234567890def");
        assert_eq!(v["os"], "darwin");
        assert_eq!(v["shells"], json!(["bash", "zsh"]));
        assert_eq!(v["agent_version"], "0.6.0-dev");
    }

    #[test]
    fn response_envelope_shape() {
        // The dispatcher sends responses as {type, request_id, payload}
        // — pin that shape so handler refactors don't accidentally
        // flatten the payload into the envelope (which would shadow
        // request_id when a handler returns a "request_id" key).
        let resp = Response {
            response_type: "exec_result",
            request_id: Some("r1".into()),
            payload: json!({"exit_code": 0, "stdout": "hi"}),
        };
        let v = serde_json::to_value(&resp).unwrap();
        assert_eq!(v["type"], "exec_result");
        assert_eq!(v["request_id"], "r1");
        assert_eq!(v["payload"]["exit_code"], 0);
        assert_eq!(v["payload"]["stdout"], "hi");
    }

    #[test]
    fn auth_ok_deserializes() {
        let v: Incoming =
            serde_json::from_str(r#"{"type":"auth_ok","agent_id":"abc"}"#).unwrap();
        match v {
            Incoming::AuthOk { agent_id } => assert_eq!(agent_id, "abc"),
            other => panic!("expected AuthOk, got {other:?}"),
        }
    }

    #[test]
    fn auth_error_deserializes_with_optional_message() {
        let v: Incoming = serde_json::from_str(r#"{"type":"auth_error"}"#).unwrap();
        assert!(matches!(v, Incoming::AuthError { message: None }));

        let v: Incoming =
            serde_json::from_str(r#"{"type":"auth_error","message":"nope"}"#).unwrap();
        match v {
            Incoming::AuthError { message: Some(m) } => assert_eq!(m, "nope"),
            other => panic!("expected AuthError, got {other:?}"),
        }
    }

    #[test]
    fn pong_deserializes() {
        let v: Incoming = serde_json::from_str(r#"{"type":"pong"}"#).unwrap();
        assert!(matches!(v, Incoming::Pong));
    }

    #[test]
    fn update_available_deserializes_with_partial_fields() {
        let v: Incoming = serde_json::from_str(r#"{"type":"update_available"}"#).unwrap();
        assert!(matches!(
            v,
            Incoming::UpdateAvailable {
                version: None,
                download_url: None,
                sha256: None
            }
        ));
    }

    #[test]
    fn unknown_type_falls_through_to_other() {
        let v: Incoming = serde_json::from_str(
            r#"{"type":"exec","payload":{"cmd":"ls"},"request_id":"r1"}"#,
        )
        .unwrap();
        assert!(matches!(v, Incoming::Other));
    }

    #[test]
    fn request_envelope_captures_type_and_payload() {
        let raw = r#"{"type":"read_file","request_id":"r1","payload":{"path":"foo.txt","cwd":"/tmp"}}"#;
        let env: RequestEnvelope = serde_json::from_str(raw).unwrap();
        assert_eq!(env.request_type, "read_file");
        assert_eq!(env.request_id.as_deref(), Some("r1"));
        assert_eq!(env.payload["path"], "foo.txt");
        assert_eq!(env.payload["cwd"], "/tmp");
    }

    #[test]
    fn request_envelope_defaults_missing_payload_to_object() {
        let raw = r#"{"type":"stat","request_id":"r2"}"#;
        let env: RequestEnvelope = serde_json::from_str(raw).unwrap();
        assert_eq!(env.request_type, "stat");
        assert!(env.payload.is_object());
        assert_eq!(env.payload.as_object().unwrap().len(), 0);
    }
}
