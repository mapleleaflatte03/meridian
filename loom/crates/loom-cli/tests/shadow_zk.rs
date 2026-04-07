use ed25519_dalek::{Signature, Signer, SigningKey};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::fs;
use std::io::{Read, Write};
use std::net::TcpListener;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};
use std::sync::atomic::{AtomicU64, Ordering};
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

static TEST_COUNTER: AtomicU64 = AtomicU64::new(0);

fn unique_temp_dir(label: &str) -> PathBuf {
    let n = TEST_COUNTER.fetch_add(1, Ordering::SeqCst);
    let dir = std::env::temp_dir().join(format!(
        "loom_shadow_zk_{}_{}_{}",
        label,
        std::process::id(),
        n
    ));
    let _ = fs::remove_dir_all(&dir);
    fs::create_dir_all(&dir).expect("create temp dir");
    dir
}

struct Harness {
    home: PathBuf,
    root: PathBuf,
    kernel: PathBuf,
}

impl Harness {
    fn new(label: &str) -> Self {
        let home = unique_temp_dir(label);
        let root = home.join(".local/share/meridian-loom/runtime/default");
        let kernel = home.join("kernel");
        scaffold_kernel_fixture(&kernel, false);
        let harness = Self { home, root, kernel };
        harness.run_ok(&[
            "init",
            "--mode",
            "embedded",
            "--root",
            harness.root_str(),
            "--kernel-path",
            harness.kernel_str(),
            "--org-id",
            "org_demo",
        ]);
        harness
    }

    fn with_settlement_restriction(label: &str) -> Self {
        let home = unique_temp_dir(label);
        let root = home.join(".local/share/meridian-loom/runtime/default");
        let kernel = home.join("kernel");
        scaffold_kernel_fixture(&kernel, true);
        let harness = Self { home, root, kernel };
        harness.run_ok(&[
            "init",
            "--mode",
            "embedded",
            "--root",
            harness.root_str(),
            "--kernel-path",
            harness.kernel_str(),
            "--org-id",
            "org_demo",
        ]);
        harness
    }

    fn root_str(&self) -> &str {
        self.root.to_str().expect("root str")
    }

    fn kernel_str(&self) -> &str {
        self.kernel.to_str().expect("kernel str")
    }

    fn config_home(&self) -> PathBuf {
        self.home.join(".config")
    }

    fn binary(&self) -> &'static str {
        env!("CARGO_BIN_EXE_loom")
    }

    fn base_command(&self) -> Command {
        let mut command = Command::new(self.binary());
        command.env("HOME", &self.home);
        command.env("XDG_CONFIG_HOME", self.config_home());
        command
    }

    fn run_output(&self, args: &[&str]) -> Output {
        self.base_command()
            .args(args)
            .output()
            .expect("run loom command")
    }

    fn run_output_with_env(&self, args: &[&str], envs: &[(&str, &str)]) -> Output {
        let mut command = self.base_command();
        for (name, value) in envs {
            command.env(name, value);
        }
        command
            .args(args)
            .output()
            .expect("run loom command with env")
    }

    fn run_ok(&self, args: &[&str]) -> String {
        let output = self.run_output(args);
        assert_success(args, &output);
        String::from_utf8_lossy(&output.stdout).to_string()
    }

    fn json_ok(&self, args: &[&str]) -> Value {
        let output = self.run_output(args);
        assert_success(args, &output);
        serde_json::from_slice(&output.stdout).expect("parse json")
    }

    fn json_ok_with_env(&self, args: &[&str], envs: &[(&str, &str)]) -> Value {
        let output = self.run_output_with_env(args, envs);
        assert_success(args, &output);
        serde_json::from_slice(&output.stdout).expect("parse json")
    }
}

fn assert_success(args: &[&str], output: &Output) {
    assert!(
        output.status.success(),
        "command {:?} failed\nstatus: {:?}\nstdout:\n{}\nstderr:\n{}",
        args,
        output.status.code(),
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
    );
}

fn scaffold_kernel_fixture(root: &Path, restrict_settle: bool) {
    let kernel_dir = root.join("kernel");
    fs::create_dir_all(&kernel_dir).expect("kernel dir");
    fs::write(
        kernel_dir.join("runtimes.json"),
        "{\n  \"runtimes\": {\n    \"local_kernel\": {\"id\": \"local_kernel\", \"label\": \"Local Kernel Runtime\"},\n    \"loom_native\": {\"status\": \"official\", \"notes\": \"shadow zk fixture\", \"contract_compliance\": {\"agent_identity\": true, \"action_envelope\": true, \"cost_attribution\": true, \"approval_hook\": true, \"audit_emission\": true, \"sanction_controls\": true, \"budget_gate\": true}}\n  }\n}\n",
    )
    .expect("write runtimes");
    fs::write(
        kernel_dir.join("agent_registry.py"),
        "import json, sys\nagent_id = sys.argv[sys.argv.index('--agent_id') + 1]\norg_id = sys.argv[sys.argv.index('--org_id') + 1] if '--org_id' in sys.argv else 'org_demo'\nprint(json.dumps({'id': agent_id, 'name': 'Atlas', 'org_id': org_id, 'role': 'analyst', 'economy_key': 'atlas', 'approval_required': False, 'budget': {'max_per_run_usd': 1.0}, 'runtime_binding': {'runtime_id': 'local_kernel', 'runtime_label': 'Local Kernel Runtime', 'bound_org_id': org_id, 'boundary_name': 'workspace', 'identity_model': 'session', 'runtime_registered': True, 'registration_status': 'registered'}}, indent=2))\n",
    )
    .expect("write registry");
    let restrictions = if restrict_settle { "['settle']" } else { "[]" };
    fs::write(
        kernel_dir.join("court.py"),
        format!(
            "def get_restrictions(agent_id, org_id=None):\n    return {}\n",
            restrictions
        ),
    )
    .expect("write court");
    fs::write(
        kernel_dir.join("authority.py"),
        "def check_authority(agent_id, action, org_id=None):\n    return True, 'ok'\n",
    )
    .expect("write authority");
    fs::write(
        kernel_dir.join("treasury.py"),
        "def check_budget(agent_id, cost_usd, org_id=None):\n    return True, 'ok'\n\ndef reserve_runtime_budget(agent_id, estimated_cost, org_id=None, action='', resource='', context=None, policy_ref=''):\n    return {'allowed': True, 'reservation_id': 'bud_shadow', 'reason': 'ok'}\n\ndef commit_runtime_budget(reservation_id, actual_cost_usd, note=''):\n    return {'reservation_id': reservation_id, 'status': 'committed', 'commit_reason': note}\n\ndef release_runtime_budget(reservation_id, reason=''):\n    return {'reservation_id': reservation_id, 'status': 'released', 'release_reason': reason}\n",
    )
    .expect("write treasury");
}

fn overwrite_alias_only_registry_and_strict_treasury(root: &Path) {
    let kernel_dir = root.join("kernel");
    fs::write(
        kernel_dir.join("agent_registry.py"),
        "import json, sys\nagent_id = sys.argv[sys.argv.index('--agent_id') + 1]\norg_id = sys.argv[sys.argv.index('--org_id') + 1] if '--org_id' in sys.argv else 'org_demo'\nif agent_id == 'agent_atlas':\n    print(json.dumps({'id': 'agent_atlas', 'name': 'Atlas', 'org_id': org_id, 'role': 'analyst', 'economy_key': 'atlas', 'approval_required': False, 'budget': {'max_per_run_usd': 1.0}, 'runtime_binding': {'runtime_id': 'local_kernel', 'runtime_label': 'Local Kernel Runtime', 'bound_org_id': org_id, 'boundary_name': 'workspace', 'identity_model': 'session', 'runtime_registered': True, 'registration_status': 'registered'}}, indent=2))\nelse:\n    print(f'Not found: {agent_id}')\n",
    )
    .expect("write alias-only registry");
    fs::write(
        kernel_dir.join("treasury.py"),
        "def check_budget(agent_id, cost_usd, org_id=None):\n    return True, 'ok'\n\ndef reserve_runtime_budget(agent_id, estimated_cost, org_id=None, action='', resource='', context=None, policy_ref=''):\n    if agent_id != 'agent_atlas':\n        return {'allowed': False, 'reason': 'Agent not found', 'reservation_id': None}\n    return {'allowed': True, 'reservation_id': 'bud_shadow_alias', 'reason': 'ok'}\n\ndef commit_runtime_budget(reservation_id, actual_cost_usd, note=''):\n    return {'reservation_id': reservation_id, 'status': 'committed', 'commit_reason': note}\n\ndef release_runtime_budget(reservation_id, reason=''):\n    return {'reservation_id': reservation_id, 'status': 'released', 'release_reason': reason}\n",
    )
    .expect("write strict treasury");
}

fn epoch_ms_now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

fn warrant_message(id: [u8; 32], scope_cbor: &[u8], expiry_epoch_ms: u64) -> Vec<u8> {
    let scope_hash: [u8; 32] = Sha256::digest(scope_cbor).into();
    let mut message = Vec::with_capacity(32 + 32 + 8);
    message.extend_from_slice(&id);
    message.extend_from_slice(&scope_hash);
    message.extend_from_slice(&expiry_epoch_ms.to_be_bytes());
    message
}

fn write_signed_warrant(path: &Path) {
    let signer = SigningKey::from_bytes(&[11u8; 32]);
    let mut id = [0u8; 32];
    for (index, slot) in id.iter_mut().enumerate() {
        *slot = (index as u8).wrapping_mul(5).wrapping_add(3);
    }
    let scope_cbor = vec![0xA1, 0x66, b's', b'h', b'a', b'd', b'o', b'w', 0xF5];
    let expiry_epoch_ms = epoch_ms_now() + 60_000;
    let signature: Signature = signer.sign(&warrant_message(id, &scope_cbor, expiry_epoch_ms));
    let payload = json!({
        "id_hex": hex::encode(id),
        "scope_cbor_hex": hex::encode(scope_cbor),
        "expiry_epoch_ms": expiry_epoch_ms,
        "kernel_sig_hex": hex::encode(signature.to_bytes()),
        "kernel_pub_hex": hex::encode(signer.verifying_key().to_bytes()),
    });
    fs::write(
        path,
        serde_json::to_string_pretty(&payload).expect("warrant json"),
    )
    .expect("write warrant");
}

fn write_grpcurl_shim(script_path: &Path) {
    let script = r#"#!/usr/bin/env bash
set -euo pipefail
capture_path="${LOOM_GRPC_SHIM_CAPTURE:-}"
payload='{}'
target=''
rpc=''
proto_count=0
protoset_count=0
import_path_count=0
authority=''
plaintext=false
allow_unknown_fields=false
max_time_seconds=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    -d)
      payload="$2"
      shift 2
      ;;
    -proto)
      proto_count=$((proto_count + 1))
      shift 2
      ;;
    -import-path)
      import_path_count=$((import_path_count + 1))
      shift 2
      ;;
    -protoset)
      protoset_count=$((protoset_count + 1))
      shift 2
      ;;
    -authority)
      authority="$2"
      shift 2
      ;;
    -max-time)
      max_time_seconds="$2"
      shift 2
      ;;
    -H)
      shift 2
      ;;
    -plaintext)
      plaintext=true
      shift
      ;;
    -allow-unknown-fields)
      allow_unknown_fields=true
      shift
      ;;
    *)
      if [[ -z "$target" ]]; then
        target="$1"
      elif [[ -z "$rpc" ]]; then
        rpc="$1"
      fi
      shift
      ;;
  esac
done
if [[ -n "$capture_path" ]]; then
  printf '{"target":"%s","rpc":"%s","payload":%s,"proto_count":%d,"protoset_count":%d,"import_path_count":%d,"authority":"%s","plaintext":%s,"allow_unknown_fields":%s,"max_time_seconds":%s}\n' "$target" "$rpc" "$payload" "$proto_count" "$protoset_count" "$import_path_count" "$authority" "$plaintext" "$allow_unknown_fields" "$max_time_seconds" > "$capture_path"
fi
printf '{"status":"ok","transport":"grpc","rpc":"%s"}\n' "$rpc"
"#;
    fs::write(script_path, script).expect("write grpcurl shim");
    let mut permissions = fs::metadata(script_path)
        .expect("grpcurl shim metadata")
        .permissions();
    permissions.set_mode(0o755);
    fs::set_permissions(script_path, permissions).expect("chmod grpcurl shim");
}

fn spawn_http_fixture_server(
    method: &'static str,
    path: &'static str,
    expected_body: Option<&'static str>,
) -> (String, thread::JoinHandle<()>) {
    let listener = TcpListener::bind("127.0.0.1:0").expect("bind http listener");
    let url = format!(
        "http://{}{}",
        listener.local_addr().expect("listener addr"),
        path
    );
    let handle = thread::spawn(move || {
        let (mut stream, _) = listener.accept().expect("accept http connection");
        stream
            .set_read_timeout(Some(Duration::from_secs(2)))
            .expect("set read timeout");
        let mut raw = Vec::new();
        let mut buf = [0_u8; 1024];
        loop {
            match stream.read(&mut buf) {
                Ok(0) => break,
                Ok(n) => {
                    raw.extend_from_slice(&buf[..n]);
                    if let Some(header_end) =
                        raw.windows(4).position(|window| window == b"\r\n\r\n")
                    {
                        let header_bytes = &raw[..header_end + 4];
                        let header_text = String::from_utf8_lossy(header_bytes);
                        let content_length = header_text
                            .lines()
                            .find_map(|line| {
                                line.split_once(':').and_then(|(name, value)| {
                                    if name.trim().eq_ignore_ascii_case("content-length") {
                                        value.trim().parse::<usize>().ok()
                                    } else {
                                        None
                                    }
                                })
                            })
                            .unwrap_or(0);
                        let total_len = header_end + 4 + content_length;
                        if raw.len() >= total_len {
                            break;
                        }
                    }
                }
                Err(error) => panic!("read request: {}", error),
            }
        }
        let request = String::from_utf8_lossy(&raw).to_string();
        assert!(
            request.starts_with(&format!("{} {} HTTP/1.1", method, path)),
            "{}",
            request
        );
        assert!(request.contains("x-shadow-test: enabled"), "{}", request);
        if let Some(body) = expected_body {
            assert!(
                request.contains("content-type: application/json"),
                "{}",
                request
            );
            assert!(
                request.contains(&format!("content-length: {}", body.len())),
                "{}",
                request
            );
        }
        let response =
            "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 17\r\nConnection: close\r\n\r\n{\"status\":\"ok\"}";
        stream
            .write_all(response.as_bytes())
            .expect("write response");
    });
    (url, handle)
}

#[test]
fn shadow_run_wasmtime_requires_warrant_file() {
    let harness = Harness::new("shadow_requires_warrant");
    let output = harness.run_output(&[
        "shadow",
        "run",
        "--backend",
        "wasmtime",
        "--root",
        harness.root_str(),
        "--kernel-path",
        harness.kernel_str(),
        "--agent-id",
        "agent_atlas",
        "--org-id",
        "org_demo",
        "--module",
        "builtin:system.info",
        "--format",
        "json",
    ]);
    assert!(
        !output.status.success(),
        "shadow run should require warrant file"
    );
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(stderr.contains("--warrant-file"), "stderr was: {}", stderr);
}

#[test]
fn shadow_run_wasmtime_writes_verified_warrant_and_report_artifacts() {
    let harness = Harness::new("shadow_run_verified");
    let warrant_path = harness.home.join("shadow-warrant.json");
    write_signed_warrant(&warrant_path);

    let capture = harness.json_ok(&[
        "shadow",
        "run",
        "--backend",
        "wasmtime",
        "--root",
        harness.root_str(),
        "--kernel-path",
        harness.kernel_str(),
        "--agent-id",
        "agent_atlas",
        "--org-id",
        "org_demo",
        "--action-type",
        "research",
        "--resource",
        "system_info",
        "--module",
        "builtin:system.info",
        "--warrant-file",
        warrant_path.to_str().expect("warrant path"),
        "--format",
        "json",
    ]);
    assert_eq!(
        capture.get("status").and_then(Value::as_str),
        Some("shadow_run_captured")
    );
    assert_eq!(
        capture
            .get("warrant_binding_status")
            .and_then(Value::as_str),
        Some("verified")
    );
    assert!(capture
        .get("poge_merkle_root_hex")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .starts_with("0x"));
    assert!(
        capture
            .get("poge_trace_len")
            .and_then(Value::as_u64)
            .unwrap_or_default()
            >= 1
    );

    let shadow_report = harness.run_ok(&["shadow", "report", "--root", harness.root_str()]);
    assert!(shadow_report.contains("Runtime execution"));
    assert!(shadow_report.contains("verified"));

    let parity_report = harness.run_ok(&["parity", "report", "--root", harness.root_str()]);
    assert!(parity_report.contains("Parity latest"));
    assert!(parity_report.contains("poge_merkle_root_hex"));
}

#[test]
fn job_settle_zk_prepares_artifacts_from_latest_shadow_run() {
    let harness = Harness::new("shadow_settle_ready");
    let warrant_path = harness.home.join("shadow-warrant.json");
    write_signed_warrant(&warrant_path);
    harness.run_ok(&[
        "shadow",
        "run",
        "--backend",
        "wasmtime",
        "--root",
        harness.root_str(),
        "--kernel-path",
        harness.kernel_str(),
        "--agent-id",
        "agent_atlas",
        "--org-id",
        "org_demo",
        "--action-type",
        "research",
        "--resource",
        "system_info",
        "--module",
        "builtin:system.info",
        "--warrant-file",
        warrant_path.to_str().expect("warrant path"),
        "--format",
        "json",
    ]);

    let settlement = harness.json_ok(&[
        "job",
        "settle",
        "--zk",
        "--root",
        harness.root_str(),
        "--kernel-path",
        harness.kernel_str(),
        "--actual-cost-usd",
        "0.05",
        "--format",
        "json",
    ]);
    assert_eq!(
        settlement.get("status").and_then(Value::as_str),
        Some("zk_settlement_captured")
    );
    assert_eq!(
        settlement.get("court_status").and_then(Value::as_str),
        Some("clear")
    );
    assert_eq!(
        settlement.get("treasury_status").and_then(Value::as_str),
        Some("committed")
    );
    assert_eq!(
        settlement.get("proof_backend").and_then(Value::as_str),
        Some("sp1")
    );
    assert!(settlement
        .get("witness_digest_hex")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .starts_with("0x"));

    let shadow_report = harness.run_ok(&["shadow", "report", "--root", harness.root_str()]);
    assert!(shadow_report.contains("ZK proof latest"));
    assert!(shadow_report.contains("Settlement latest"));
}

#[test]
fn acceptance_shadow_zk_one_command_lane() {
    let harness = Harness::new("shadow_zk_acceptance_lane");
    let warrant_path = harness.home.join("shadow-warrant.json");
    write_signed_warrant(&warrant_path);

    let capture = harness.json_ok(&[
        "shadow",
        "run",
        "--backend",
        "wasmtime",
        "--root",
        harness.root_str(),
        "--kernel-path",
        harness.kernel_str(),
        "--agent-id",
        "agent_atlas",
        "--org-id",
        "org_demo",
        "--action-type",
        "research",
        "--resource",
        "system_info",
        "--module",
        "builtin:system.info",
        "--warrant-file",
        warrant_path.to_str().expect("warrant path"),
        "--format",
        "json",
    ]);
    assert_eq!(
        capture.get("status").and_then(Value::as_str),
        Some("shadow_run_captured")
    );
    assert_eq!(
        capture
            .get("warrant_binding_status")
            .and_then(Value::as_str),
        Some("verified")
    );

    let settlement = harness.json_ok(&[
        "job",
        "settle",
        "--zk",
        "--zk-backend",
        "sp1",
        "--root",
        harness.root_str(),
        "--kernel-path",
        harness.kernel_str(),
        "--actual-cost-usd",
        "0.05",
        "--format",
        "json",
    ]);
    assert_eq!(
        settlement.get("status").and_then(Value::as_str),
        Some("zk_settlement_captured")
    );
    assert_eq!(
        settlement.get("settlement_status").and_then(Value::as_str),
        Some("prepared")
    );
    assert_eq!(
        settlement.get("treasury_status").and_then(Value::as_str),
        Some("committed")
    );
    assert!(settlement
        .get("proof_id")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .starts_with("zkp_"));

    let shadow_report = harness.run_ok(&["shadow", "report", "--root", harness.root_str()]);
    assert!(
        shadow_report.contains("Runtime execution"),
        "{}",
        shadow_report
    );
    assert!(
        shadow_report.contains("warrant:     verified"),
        "{}",
        shadow_report
    );
    assert!(
        shadow_report.contains("ZK proof latest"),
        "{}",
        shadow_report
    );
    assert!(
        shadow_report.contains("Settlement latest"),
        "{}",
        shadow_report
    );

    let parity_report = harness.run_ok(&["parity", "report", "--root", harness.root_str()]);
    assert!(parity_report.contains("Parity latest"), "{}", parity_report);
    assert!(
        parity_report.contains("Action parity summary"),
        "{}",
        parity_report
    );
    assert!(
        parity_report.contains("ZK proof latest"),
        "{}",
        parity_report
    );
    assert!(
        parity_report.contains("Settlement latest"),
        "{}",
        parity_report
    );

    assert!(harness.root.join("artifacts/zk/latest.json").exists());
    assert!(harness
        .root
        .join("artifacts/settlement/latest.json")
        .exists());
}

#[test]
fn job_settle_zk_rejects_unknown_backend() {
    let harness = Harness::new("shadow_settle_unknown_backend");
    let warrant_path = harness.home.join("shadow-warrant.json");
    write_signed_warrant(&warrant_path);
    harness.run_ok(&[
        "shadow",
        "run",
        "--backend",
        "wasmtime",
        "--root",
        harness.root_str(),
        "--kernel-path",
        harness.kernel_str(),
        "--agent-id",
        "agent_atlas",
        "--org-id",
        "org_demo",
        "--action-type",
        "research",
        "--resource",
        "system_info",
        "--module",
        "builtin:system.info",
        "--warrant-file",
        warrant_path.to_str().expect("warrant path"),
        "--format",
        "json",
    ]);

    let output = harness.run_output(&[
        "job",
        "settle",
        "--zk",
        "--zk-backend",
        "risc0",
        "--root",
        harness.root_str(),
        "--kernel-path",
        harness.kernel_str(),
        "--actual-cost-usd",
        "0.05",
        "--format",
        "json",
    ]);
    assert!(
        !output.status.success(),
        "job settle should reject unknown --zk-backend"
    );
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains("invalid --zk-backend") && stderr.contains("supported backends: sp1"),
        "stderr was: {}",
        stderr
    );
}

#[test]
fn job_settle_zk_blocks_when_court_restricts_settle() {
    let harness = Harness::with_settlement_restriction("shadow_settle_blocked");
    let warrant_path = harness.home.join("shadow-warrant.json");
    write_signed_warrant(&warrant_path);
    harness.run_ok(&[
        "shadow",
        "run",
        "--backend",
        "wasmtime",
        "--root",
        harness.root_str(),
        "--kernel-path",
        harness.kernel_str(),
        "--agent-id",
        "agent_atlas",
        "--org-id",
        "org_demo",
        "--action-type",
        "research",
        "--resource",
        "system_info",
        "--module",
        "builtin:system.info",
        "--warrant-file",
        warrant_path.to_str().expect("warrant path"),
        "--format",
        "json",
    ]);

    let settlement = harness.json_ok(&[
        "job",
        "settle",
        "--zk",
        "--root",
        harness.root_str(),
        "--kernel-path",
        harness.kernel_str(),
        "--actual-cost-usd",
        "0.05",
        "--format",
        "json",
    ]);
    assert_eq!(
        settlement.get("court_status").and_then(Value::as_str),
        Some("blocked")
    );
    assert_eq!(
        settlement.get("settlement_status").and_then(Value::as_str),
        Some("blocked_by_court")
    );
}

#[test]
fn job_settle_zk_canonicalizes_alias_agent_ref_before_treasury() {
    let harness = Harness::new("shadow_settle_alias_ref");
    overwrite_alias_only_registry_and_strict_treasury(&harness.kernel);

    let warrant_path = harness.home.join("shadow-warrant.json");
    write_signed_warrant(&warrant_path);
    harness.run_ok(&[
        "shadow",
        "run",
        "--backend",
        "wasmtime",
        "--root",
        harness.root_str(),
        "--kernel-path",
        harness.kernel_str(),
        "--agent-id",
        "agent_atlas",
        "--org-id",
        "org_demo",
        "--action-type",
        "research",
        "--resource",
        "system_info",
        "--module",
        "builtin:system.info",
        "--warrant-file",
        warrant_path.to_str().expect("warrant path"),
        "--format",
        "json",
    ]);

    let execution_path = harness.root.join("state/runtime/last_execution.json");
    let mut execution: Value =
        serde_json::from_slice(&fs::read(&execution_path).expect("read last execution"))
            .expect("parse last execution");
    execution["agent_id"] = Value::String("atlas".to_string());
    fs::write(
        &execution_path,
        serde_json::to_string_pretty(&execution).expect("serialize last execution"),
    )
    .expect("write rewritten execution");

    let settlement = harness.json_ok(&[
        "job",
        "settle",
        "--zk",
        "--root",
        harness.root_str(),
        "--kernel-path",
        harness.kernel_str(),
        "--actual-cost-usd",
        "0.05",
        "--format",
        "json",
    ]);
    assert_eq!(
        settlement.get("treasury_status").and_then(Value::as_str),
        Some("committed")
    );
    assert_eq!(
        settlement.get("reservation_id").and_then(Value::as_str),
        Some("bud_shadow_alias")
    );
    assert_eq!(
        settlement
            .get("requested_agent_ref")
            .and_then(Value::as_str),
        Some("atlas")
    );
    assert_eq!(
        settlement.get("agent_id").and_then(Value::as_str),
        Some("agent_atlas")
    );
    assert_eq!(
        settlement.get("treasury_agent_ref").and_then(Value::as_str),
        Some("agent_atlas")
    );
}

#[test]
fn shadow_run_command_backend_writes_typed_report_artifacts() {
    let harness = Harness::new("shadow_run_command");
    let warrant_path = harness.home.join("shadow-command-warrant.json");
    write_signed_warrant(&warrant_path);

    let capture = harness.json_ok(&[
        "shadow",
        "run",
        "--backend",
        "command",
        "--root",
        harness.root_str(),
        "--kernel-path",
        harness.kernel_str(),
        "--agent-id",
        "agent_atlas",
        "--org-id",
        "org_demo",
        "--action-type",
        "shadow_command",
        "--resource",
        "external_process",
        "--warrant-file",
        warrant_path.to_str().expect("warrant path"),
        "--command",
        "/bin/echo",
        "--arg",
        "shadow-command",
        "--format",
        "json",
    ]);

    assert_eq!(
        capture.get("status").and_then(Value::as_str),
        Some("shadow_run_captured")
    );
    assert_eq!(
        capture.get("backend").and_then(Value::as_str),
        Some("command")
    );
    assert_eq!(
        capture.get("host_backend").and_then(Value::as_str),
        Some("external_command")
    );
    assert_eq!(
        capture
            .get("warrant_binding_status")
            .and_then(Value::as_str),
        Some("verified")
    );
    assert_eq!(
        capture.get("entrypoint_result").and_then(Value::as_i64),
        Some(0)
    );
    assert!(capture
        .get("poge_merkle_root_hex")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .starts_with("0x"));

    let shadow_report = harness.run_ok(&["shadow", "report", "--root", harness.root_str()]);
    assert!(
        shadow_report.contains("source: typed shadow capture"),
        "shadow report should prefer typed shadow capture\n{}",
        shadow_report
    );
    assert!(
        shadow_report.contains("backend:     command"),
        "shadow report should include command backend\n{}",
        shadow_report
    );
    assert!(
        shadow_report.contains("host_backend:external_command"),
        "shadow report should include external command host backend\n{}",
        shadow_report
    );

    let parity_report = harness.run_ok(&["parity", "report", "--root", harness.root_str()]);
    assert!(
        parity_report.contains("source: typed parity capture"),
        "parity report should include typed parity summary\n{}",
        parity_report
    );
    assert!(
        parity_report.contains("backend:     command"),
        "parity report should reflect command backend\n{}",
        parity_report
    );
}

#[test]
fn shadow_run_http_backend_writes_typed_report_artifacts() {
    let harness = Harness::new("shadow_run_http");
    let warrant_path = harness.home.join("shadow-http-warrant.json");
    write_signed_warrant(&warrant_path);
    let (http_url, server) =
        spawn_http_fixture_server("POST", "/shadow-http", Some("{\"task\":\"shadow-http\"}"));

    let capture = harness.json_ok(&[
        "shadow",
        "run",
        "--backend",
        "http",
        "--root",
        harness.root_str(),
        "--kernel-path",
        harness.kernel_str(),
        "--agent-id",
        "agent_atlas",
        "--org-id",
        "org_demo",
        "--action-type",
        "shadow_http",
        "--resource",
        "external_http",
        "--warrant-file",
        warrant_path.to_str().expect("warrant path"),
        "--url",
        &http_url,
        "--method",
        "POST",
        "--header",
        "x-shadow-test: enabled",
        "--body-json",
        "{\"task\":\"shadow-http\"}",
        "--format",
        "json",
    ]);

    server.join().expect("join http fixture");

    assert_eq!(
        capture.get("status").and_then(Value::as_str),
        Some("shadow_run_captured")
    );
    assert_eq!(capture.get("backend").and_then(Value::as_str), Some("http"));
    assert_eq!(
        capture.get("host_backend").and_then(Value::as_str),
        Some("external_http")
    );
    assert_eq!(
        capture.get("entrypoint_result").and_then(Value::as_i64),
        Some(200)
    );
    assert_eq!(
        capture
            .get("warrant_binding_status")
            .and_then(Value::as_str),
        Some("verified")
    );
    assert!(capture
        .get("host_response_json")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .contains("\"http_status\": 200"));

    let shadow_report = harness.run_ok(&["shadow", "report", "--root", harness.root_str()]);
    assert!(
        shadow_report.contains("source: typed shadow capture"),
        "shadow report should prefer typed shadow capture\n{}",
        shadow_report
    );
    assert!(
        shadow_report.contains("backend:     http"),
        "shadow report should include http backend\n{}",
        shadow_report
    );
    assert!(
        shadow_report.contains("host_backend:external_http"),
        "shadow report should include external http host backend\n{}",
        shadow_report
    );
}

#[test]
fn shadow_run_mcp_backend_writes_typed_report_artifacts() {
    let harness = Harness::new("shadow_run_mcp");
    let warrant_path = harness.home.join("shadow-mcp-warrant.json");
    write_signed_warrant(&warrant_path);
    let expected_body =
        "{\"jsonrpc\":\"2.0\",\"id\":\"shadow-mcp-test\",\"method\":\"tools/list\",\"params\":{}}";
    let (http_url, server) = spawn_http_fixture_server("POST", "/shadow-mcp", Some(expected_body));

    let capture = harness.json_ok(&[
        "shadow",
        "run",
        "--backend",
        "mcp",
        "--root",
        harness.root_str(),
        "--kernel-path",
        harness.kernel_str(),
        "--agent-id",
        "agent_atlas",
        "--org-id",
        "org_demo",
        "--action-type",
        "shadow_mcp",
        "--resource",
        "external_mcp",
        "--warrant-file",
        warrant_path.to_str().expect("warrant path"),
        "--url",
        &http_url,
        "--header",
        "x-shadow-test: enabled",
        "--mcp-method",
        "tools/list",
        "--mcp-request-id",
        "shadow-mcp-test",
        "--mcp-params-json",
        "{}",
        "--format",
        "json",
    ]);

    server.join().expect("join mcp fixture");

    assert_eq!(
        capture.get("status").and_then(Value::as_str),
        Some("shadow_run_captured")
    );
    assert_eq!(capture.get("backend").and_then(Value::as_str), Some("mcp"));
    assert_eq!(
        capture.get("host_backend").and_then(Value::as_str),
        Some("external_mcp")
    );
    assert_eq!(
        capture.get("entrypoint_result").and_then(Value::as_i64),
        Some(200)
    );
    assert_eq!(
        capture
            .get("warrant_binding_status")
            .and_then(Value::as_str),
        Some("verified")
    );
    assert_eq!(
        capture
            .get("host_calls")
            .and_then(Value::as_array)
            .and_then(|calls| calls.first())
            .and_then(Value::as_str),
        Some("mcp.call")
    );
    assert!(capture
        .get("host_response_json")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .contains("\"mcp_method\": \"tools/list\""));

    let shadow_report = harness.run_ok(&["shadow", "report", "--root", harness.root_str()]);
    assert!(
        shadow_report.contains("backend:     mcp"),
        "shadow report should include mcp backend\n{}",
        shadow_report
    );
    assert!(
        shadow_report.contains("host_backend:external_mcp"),
        "shadow report should include external mcp host backend\n{}",
        shadow_report
    );
}

#[test]
fn shadow_run_a2a_backend_writes_typed_report_artifacts() {
    let harness = Harness::new("shadow_run_a2a");
    let warrant_path = harness.home.join("shadow-a2a-warrant.json");
    write_signed_warrant(&warrant_path);
    let expected_body =
        "{\"jsonrpc\":\"2.0\",\"id\":\"shadow-a2a-test\",\"method\":\"message/send\",\"params\":{\"skill\":\"loom_submit\"}}";
    let (http_url, server) = spawn_http_fixture_server("POST", "/shadow-a2a", Some(expected_body));

    let capture = harness.json_ok(&[
        "shadow",
        "run",
        "--backend",
        "a2a",
        "--root",
        harness.root_str(),
        "--kernel-path",
        harness.kernel_str(),
        "--agent-id",
        "agent_atlas",
        "--org-id",
        "org_demo",
        "--action-type",
        "shadow_a2a",
        "--resource",
        "external_a2a",
        "--warrant-file",
        warrant_path.to_str().expect("warrant path"),
        "--url",
        &http_url,
        "--header",
        "x-shadow-test: enabled",
        "--a2a-method",
        "message/send",
        "--a2a-request-id",
        "shadow-a2a-test",
        "--a2a-params-json",
        "{}",
        "--a2a-skill",
        "loom_submit",
        "--format",
        "json",
    ]);

    server.join().expect("join a2a fixture");

    assert_eq!(
        capture.get("status").and_then(Value::as_str),
        Some("shadow_run_captured")
    );
    assert_eq!(capture.get("backend").and_then(Value::as_str), Some("a2a"));
    assert_eq!(
        capture.get("host_backend").and_then(Value::as_str),
        Some("external_a2a")
    );
    assert_eq!(
        capture.get("entrypoint_result").and_then(Value::as_i64),
        Some(200)
    );
    assert_eq!(
        capture
            .get("warrant_binding_status")
            .and_then(Value::as_str),
        Some("verified")
    );
    assert_eq!(
        capture
            .get("host_calls")
            .and_then(Value::as_array)
            .and_then(|calls| calls.first())
            .and_then(Value::as_str),
        Some("a2a.message")
    );
    assert!(capture
        .get("host_response_json")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .contains("\"a2a_method\": \"message/send\""));

    let shadow_report = harness.run_ok(&["shadow", "report", "--root", harness.root_str()]);
    assert!(
        shadow_report.contains("backend:     a2a"),
        "shadow report should include a2a backend\n{}",
        shadow_report
    );
    assert!(
        shadow_report.contains("host_backend:external_a2a"),
        "shadow report should include external a2a host backend\n{}",
        shadow_report
    );
}

#[test]
fn shadow_run_a2a_action_backend_writes_typed_report_artifacts() {
    let harness = Harness::new("shadow_run_a2a_action");
    let warrant_path = harness.home.join("shadow-a2a-action-warrant.json");
    write_signed_warrant(&warrant_path);
    let expected_body = "{\"action\":{\"kind\":\"research.deliver\",\"objective\":\"deliver trust-op summary\",\"skill\":\"loom_submit\"},\"actor\":{\"agent_id\":\"agent_atlas\",\"org_id\":\"org_demo\"},\"constraints\":{},\"context\":{},\"governance\":{\"proof_required\":true,\"settlement_mode\":\"treasury_gated\",\"warrant_id_hex\":\"0x03080d12171c21262b30353a3f44494e53585d62676c71767b80858a8f94999e\"},\"memory\":{\"recall_refs\":[]},\"request_id\":\"shadow-a2a-action-test\",\"schema\":\"meridian.a2a.action.v1\"}";
    let (http_url, server) =
        spawn_http_fixture_server("POST", "/shadow-a2a-action", Some(expected_body));

    let capture = harness.json_ok(&[
        "shadow",
        "run",
        "--backend",
        "a2a_action",
        "--root",
        harness.root_str(),
        "--kernel-path",
        harness.kernel_str(),
        "--agent-id",
        "agent_atlas",
        "--org-id",
        "org_demo",
        "--action-type",
        "shadow_a2a_action",
        "--resource",
        "external_a2a_action",
        "--warrant-file",
        warrant_path.to_str().expect("warrant path"),
        "--url",
        &http_url,
        "--header",
        "x-shadow-test: enabled",
        "--a2a-action-request-id",
        "shadow-a2a-action-test",
        "--a2a-action-kind",
        "research.deliver",
        "--a2a-action-objective",
        "deliver trust-op summary",
        "--a2a-skill",
        "loom_submit",
        "--a2a-context-json",
        "{}",
        "--a2a-constraints-json",
        "{}",
        "--a2a-memory-json",
        "[]",
        "--format",
        "json",
    ]);

    server.join().expect("join a2a action fixture");

    assert_eq!(
        capture.get("status").and_then(Value::as_str),
        Some("shadow_run_captured")
    );
    assert_eq!(
        capture.get("backend").and_then(Value::as_str),
        Some("a2a_action")
    );
    assert_eq!(
        capture.get("host_backend").and_then(Value::as_str),
        Some("external_a2a_action")
    );
    assert_eq!(
        capture.get("entrypoint_result").and_then(Value::as_i64),
        Some(200)
    );
    assert_eq!(
        capture
            .get("warrant_binding_status")
            .and_then(Value::as_str),
        Some("verified")
    );
    assert_eq!(
        capture
            .get("host_calls")
            .and_then(Value::as_array)
            .and_then(|calls| calls.first())
            .and_then(Value::as_str),
        Some("a2a.action.submit")
    );
    assert!(capture
        .get("host_response_json")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .contains("\"a2a_action_kind\": \"research.deliver\""));

    let shadow_report = harness.run_ok(&["shadow", "report", "--root", harness.root_str()]);
    assert!(
        shadow_report.contains("backend:     a2a_action"),
        "shadow report should include a2a_action backend\n{}",
        shadow_report
    );
    assert!(
        shadow_report.contains("host_backend:external_a2a_action"),
        "shadow report should include external a2a_action host backend\n{}",
        shadow_report
    );
}

#[test]
fn shadow_run_grpc_action_backend_writes_typed_report_artifacts() {
    let harness = Harness::new("shadow_run_grpc_action");
    let warrant_path = harness.home.join("shadow-grpc-action-warrant.json");
    write_signed_warrant(&warrant_path);
    let grpcurl_shim = harness.home.join("grpcurl-shim.sh");
    let shim_capture = harness.home.join("grpc-shim-capture.json");
    write_grpcurl_shim(&grpcurl_shim);

    let grpcurl_shim_str = grpcurl_shim.to_str().expect("grpcurl shim path");
    let shim_capture_str = shim_capture.to_str().expect("shim capture path");
    let capture = harness.json_ok_with_env(
        &[
            "shadow",
            "run",
            "--backend",
            "grpc_action",
            "--root",
            harness.root_str(),
            "--kernel-path",
            harness.kernel_str(),
            "--agent-id",
            "agent_atlas",
            "--org-id",
            "org_demo",
            "--action-type",
            "shadow_grpc_action",
            "--resource",
            "external_grpc_action",
            "--warrant-file",
            warrant_path.to_str().expect("warrant path"),
            "--url",
            "127.0.0.1:50051",
            "--header",
            "x-shadow-test: enabled",
            "--grpc-service",
            "meridian.runtime.v1.ActionService",
            "--grpc-method",
            "SubmitAction",
            "--grpc-authority",
            "runtime.meridian.internal",
            "--grpc-plaintext",
            "--grpc-allow-unknown-fields",
            "--grpc-timeout-seconds",
            "7",
            "--grpc-import-path",
            ".",
            "--grpc-proto",
            "meridian/runtime/v1/action_service.proto",
            "--grpc-protoset",
            "meridian/runtime/v1/action_service.protoset",
            "--grpc-action-request-id",
            "shadow-grpc-action-test",
            "--grpc-action-kind",
            "research.deliver",
            "--grpc-action-objective",
            "deliver trust-op summary",
            "--grpc-skill",
            "loom_submit",
            "--grpc-context-json",
            "{}",
            "--grpc-constraints-json",
            "{}",
            "--grpc-memory-json",
            "[]",
            "--format",
            "json",
        ],
        &[
            ("LOOM_SHADOW_GRPCURL_BIN", grpcurl_shim_str),
            ("LOOM_GRPC_SHIM_CAPTURE", shim_capture_str),
        ],
    );

    assert_eq!(
        capture.get("status").and_then(Value::as_str),
        Some("shadow_run_captured")
    );
    assert_eq!(
        capture.get("backend").and_then(Value::as_str),
        Some("grpc_action")
    );
    assert_eq!(
        capture.get("host_backend").and_then(Value::as_str),
        Some("external_grpc_action")
    );
    assert_eq!(
        capture
            .get("warrant_binding_status")
            .and_then(Value::as_str),
        Some("verified")
    );
    assert_eq!(
        capture
            .get("host_calls")
            .and_then(Value::as_array)
            .and_then(|calls| calls.first())
            .and_then(Value::as_str),
        Some("grpc.action.submit")
    );
    assert!(capture
        .get("host_response_json")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .contains("\"grpc_rpc\": \"meridian.runtime.v1.ActionService/SubmitAction\""));

    let shim_json: Value =
        serde_json::from_slice(&fs::read(&shim_capture).expect("read shim capture"))
            .expect("parse shim capture");
    assert_eq!(
        shim_json.get("target").and_then(Value::as_str),
        Some("127.0.0.1:50051")
    );
    assert_eq!(
        shim_json.get("proto_count").and_then(Value::as_u64),
        Some(1)
    );
    assert_eq!(
        shim_json.get("import_path_count").and_then(Value::as_u64),
        Some(1)
    );
    assert_eq!(
        shim_json.get("protoset_count").and_then(Value::as_u64),
        Some(1)
    );
    assert_eq!(
        shim_json.get("authority").and_then(Value::as_str),
        Some("runtime.meridian.internal")
    );
    assert_eq!(
        shim_json.get("plaintext").and_then(Value::as_bool),
        Some(true)
    );
    assert_eq!(
        shim_json
            .get("allow_unknown_fields")
            .and_then(Value::as_bool),
        Some(true)
    );
    assert_eq!(
        shim_json.get("max_time_seconds").and_then(Value::as_u64),
        Some(7)
    );
    assert_eq!(
        shim_json.get("rpc").and_then(Value::as_str),
        Some("meridian.runtime.v1.ActionService/SubmitAction")
    );
    assert_eq!(
        shim_json
            .get("payload")
            .and_then(|payload| payload.get("schema"))
            .and_then(Value::as_str),
        Some("meridian.a2a.action.v1")
    );
    assert_eq!(
        shim_json
            .get("payload")
            .and_then(|payload| payload.get("action"))
            .and_then(|action| action.get("kind"))
            .and_then(Value::as_str),
        Some("research.deliver")
    );

    let diagnostics_path = harness
        .root
        .join("artifacts")
        .join("shadow")
        .join("grpc_action")
        .join("latest.json");
    assert!(
        diagnostics_path.exists(),
        "grpc diagnostics latest should exist at {}",
        diagnostics_path.display()
    );
    let diagnostics_json: Value =
        serde_json::from_slice(&fs::read(&diagnostics_path).expect("read grpc diagnostics latest"))
            .expect("parse grpc diagnostics latest");
    assert_eq!(
        diagnostics_json.get("grpc_target").and_then(Value::as_str),
        Some("127.0.0.1:50051")
    );
    assert_eq!(
        diagnostics_json
            .get("grpc_protoset_count")
            .and_then(Value::as_u64),
        Some(1)
    );

    let shadow_report = harness.run_ok(&["shadow", "report", "--root", harness.root_str()]);
    assert!(
        shadow_report.contains("backend:     grpc_action"),
        "shadow report should include grpc_action backend\n{}",
        shadow_report
    );
    assert!(
        shadow_report.contains("host_backend:external_grpc_action"),
        "shadow report should include external grpc_action host backend\n{}",
        shadow_report
    );
    assert!(
        shadow_report.contains("grpc_rpc:    meridian.runtime.v1.ActionService/SubmitAction"),
        "shadow report should include grpc rpc diagnostics\n{}",
        shadow_report
    );
    assert!(
        shadow_report.contains("grpc_protoset_count: 1"),
        "shadow report should include grpc protoset diagnostics\n{}",
        shadow_report
    );
    assert!(
        shadow_report.contains("source: typed grpc diagnostics"),
        "shadow report should include typed grpc diagnostics section\n{}",
        shadow_report
    );

    let parity_report = harness.run_ok(&["parity", "report", "--root", harness.root_str()]);
    assert!(
        parity_report.contains("source: typed grpc diagnostics"),
        "parity report should include typed grpc diagnostics section\n{}",
        parity_report
    );
    assert!(
        parity_report
            .contains("grpc_rpc:                meridian.runtime.v1.ActionService/SubmitAction"),
        "parity report should include grpc rpc diagnostics section\n{}",
        parity_report
    );

    let diagnostics_report = harness.run_ok(&[
        "shadow",
        "grpc-diagnostics",
        "--root",
        harness.root_str(),
        "--limit",
        "5",
    ]);
    assert!(
        diagnostics_report.contains("SHADOW GRPC DIAGNOSTICS"),
        "shadow grpc diagnostics report should render header\n{}",
        diagnostics_report
    );
    assert!(
        diagnostics_report.contains("entry[0]:"),
        "shadow grpc diagnostics report should render stream entries\n{}",
        diagnostics_report
    );
    let diagnostics_operator_json = harness.json_ok(&[
        "shadow",
        "grpc-diagnostics",
        "--root",
        harness.root_str(),
        "--limit",
        "5",
        "--format",
        "json",
    ]);
    assert_eq!(
        diagnostics_operator_json
            .get("status")
            .and_then(Value::as_str),
        Some("ok")
    );
    assert!(
        diagnostics_operator_json
            .get("recent")
            .and_then(Value::as_array)
            .map(|entries| !entries.is_empty())
            .unwrap_or(false),
        "shadow grpc diagnostics json should include recent entries: {}",
        diagnostics_operator_json
    );
}

#[test]
fn shadow_run_grpc_action_rejects_conflicting_transport_flags() {
    let harness = Harness::new("shadow_run_grpc_action_conflict");
    let warrant_path = harness
        .home
        .join("shadow-grpc-action-conflict-warrant.json");
    write_signed_warrant(&warrant_path);
    let output = harness.run_output(&[
        "shadow",
        "run",
        "--backend",
        "grpc_action",
        "--root",
        harness.root_str(),
        "--kernel-path",
        harness.kernel_str(),
        "--agent-id",
        "agent_atlas",
        "--org-id",
        "org_demo",
        "--action-type",
        "shadow_grpc_action",
        "--resource",
        "external_grpc_action",
        "--warrant-file",
        warrant_path.to_str().expect("warrant path"),
        "--url",
        "127.0.0.1:50051",
        "--grpc-plaintext",
        "--grpc-tls",
        "--format",
        "json",
    ]);
    assert!(
        !output.status.success(),
        "grpc_action should reject conflicting transport flags"
    );
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains("does not allow both --grpc-plaintext and --grpc-tls"),
        "stderr was: {}",
        stderr
    );
}

#[test]
fn shadow_run_grpc_action_reports_missing_grpcurl_binary() {
    let harness = Harness::new("shadow_run_grpc_action_missing_grpcurl");
    let warrant_path = harness.home.join("shadow-grpc-action-missing-warrant.json");
    write_signed_warrant(&warrant_path);
    let output = harness.run_output_with_env(
        &[
            "shadow",
            "run",
            "--backend",
            "grpc_action",
            "--root",
            harness.root_str(),
            "--kernel-path",
            harness.kernel_str(),
            "--agent-id",
            "agent_atlas",
            "--org-id",
            "org_demo",
            "--action-type",
            "shadow_grpc_action",
            "--resource",
            "external_grpc_action",
            "--warrant-file",
            warrant_path.to_str().expect("warrant path"),
            "--url",
            "127.0.0.1:50051",
            "--grpc-service",
            "meridian.runtime.v1.ActionService",
            "--grpc-method",
            "SubmitAction",
            "--grpc-action-request-id",
            "shadow-grpc-action-missing-bin",
            "--grpc-action-kind",
            "research.deliver",
            "--grpc-action-objective",
            "deliver trust-op summary",
            "--grpc-context-json",
            "{}",
            "--grpc-constraints-json",
            "{}",
            "--grpc-memory-json",
            "[]",
            "--format",
            "json",
        ],
        &[("LOOM_SHADOW_GRPCURL_BIN", "/tmp/does-not-exist-grpcurl")],
    );
    assert!(
        !output.status.success(),
        "grpc_action should fail when grpcurl binary is missing"
    );
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains("not found") && stderr.contains("LOOM_SHADOW_GRPCURL_BIN"),
        "stderr was: {}",
        stderr
    );
}

#[test]
fn shadow_run_grpc_action_rejects_invalid_rpc_shape() {
    let harness = Harness::new("shadow_run_grpc_action_invalid_rpc");
    let warrant_path = harness
        .home
        .join("shadow-grpc-action-invalid-rpc-warrant.json");
    write_signed_warrant(&warrant_path);
    let grpcurl_shim = harness.home.join("grpcurl-shim.sh");
    write_grpcurl_shim(&grpcurl_shim);

    let output = harness.run_output_with_env(
        &[
            "shadow",
            "run",
            "--backend",
            "grpc_action",
            "--root",
            harness.root_str(),
            "--kernel-path",
            harness.kernel_str(),
            "--agent-id",
            "agent_atlas",
            "--org-id",
            "org_demo",
            "--action-type",
            "shadow_grpc_action",
            "--resource",
            "external_grpc_action",
            "--warrant-file",
            warrant_path.to_str().expect("warrant path"),
            "--url",
            "127.0.0.1:50051",
            "--grpc-service",
            "meridian.runtime.v1.ActionService",
            "--grpc-method",
            "SubmitAction/Bad",
            "--grpc-action-request-id",
            "shadow-grpc-action-invalid-rpc",
            "--grpc-action-kind",
            "research.deliver",
            "--grpc-action-objective",
            "deliver trust-op summary",
            "--grpc-context-json",
            "{}",
            "--grpc-constraints-json",
            "{}",
            "--grpc-memory-json",
            "[]",
            "--format",
            "json",
        ],
        &[(
            "LOOM_SHADOW_GRPCURL_BIN",
            grpcurl_shim.to_str().expect("shim path"),
        )],
    );
    assert!(
        !output.status.success(),
        "grpc_action should reject invalid rpc shape"
    );
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains("invalid grpc_action rpc"),
        "stderr was: {}",
        stderr
    );
}

#[test]
fn shadow_run_grpc_action_rejects_empty_protoset_flag() {
    let harness = Harness::new("shadow_run_grpc_action_empty_protoset");
    let warrant_path = harness
        .home
        .join("shadow-grpc-action-empty-protoset-warrant.json");
    write_signed_warrant(&warrant_path);

    let output = harness.run_output(&[
        "shadow",
        "run",
        "--backend",
        "grpc_action",
        "--root",
        harness.root_str(),
        "--kernel-path",
        harness.kernel_str(),
        "--agent-id",
        "agent_atlas",
        "--org-id",
        "org_demo",
        "--action-type",
        "shadow_grpc_action",
        "--resource",
        "external_grpc_action",
        "--warrant-file",
        warrant_path.to_str().expect("warrant path"),
        "--url",
        "127.0.0.1:50051",
        "--grpc-service",
        "meridian.runtime.v1.ActionService",
        "--grpc-method",
        "SubmitAction",
        "--grpc-protoset",
        "   ",
        "--format",
        "json",
    ]);
    assert!(
        !output.status.success(),
        "grpc_action should reject empty --grpc-protoset"
    );
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains("received empty --grpc-protoset"),
        "stderr was: {}",
        stderr
    );
}

#[test]
fn job_settle_zk_prepares_artifacts_from_command_shadow_run() {
    let harness = Harness::new("shadow_command_settle_ready");
    let warrant_path = harness.home.join("shadow-command-warrant.json");
    write_signed_warrant(&warrant_path);
    harness.run_ok(&[
        "shadow",
        "run",
        "--backend",
        "command",
        "--root",
        harness.root_str(),
        "--kernel-path",
        harness.kernel_str(),
        "--agent-id",
        "agent_atlas",
        "--org-id",
        "org_demo",
        "--action-type",
        "shadow_command",
        "--resource",
        "external_process",
        "--warrant-file",
        warrant_path.to_str().expect("warrant path"),
        "--command",
        "/bin/echo",
        "--arg",
        "shadow-command",
        "--format",
        "json",
    ]);

    let settlement = harness.json_ok(&[
        "job",
        "settle",
        "--zk",
        "--root",
        harness.root_str(),
        "--kernel-path",
        harness.kernel_str(),
        "--actual-cost-usd",
        "0.05",
        "--format",
        "json",
    ]);
    assert_eq!(
        settlement.get("status").and_then(Value::as_str),
        Some("zk_settlement_captured")
    );
    assert_eq!(
        settlement.get("court_status").and_then(Value::as_str),
        Some("clear")
    );
    assert_eq!(
        settlement.get("treasury_status").and_then(Value::as_str),
        Some("committed")
    );
    assert_eq!(
        settlement.get("proof_backend").and_then(Value::as_str),
        Some("sp1")
    );

    let shadow_report = harness.run_ok(&["shadow", "report", "--root", harness.root_str()]);
    assert!(
        shadow_report.contains("source: typed zk proof"),
        "shadow report should render typed zk proof\n{}",
        shadow_report
    );
    assert!(
        shadow_report.contains("source: typed settlement artifact"),
        "shadow report should render typed settlement artifact\n{}",
        shadow_report
    );

    let parity_report = harness.run_ok(&["parity", "report", "--root", harness.root_str()]);
    assert!(
        parity_report.contains("source: typed zk proof"),
        "parity report should render typed zk proof\n{}",
        parity_report
    );
    assert!(
        parity_report.contains("source: typed settlement artifact"),
        "parity report should render typed settlement artifact\n{}",
        parity_report
    );
    assert!(
        parity_report.contains("proof_backend:      sp1"),
        "parity report should include zk proof backend\n{}",
        parity_report
    );
}
