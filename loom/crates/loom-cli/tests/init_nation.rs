use serde_json::Value;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};
use std::sync::atomic::{AtomicU64, Ordering};

static TEST_COUNTER: AtomicU64 = AtomicU64::new(0);

fn unique_temp_dir(label: &str) -> PathBuf {
    let n = TEST_COUNTER.fetch_add(1, Ordering::SeqCst);
    let dir = std::env::temp_dir().join(format!(
        "loom_init_nation_{}_{}_{}",
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
        scaffold_kernel_fixture(&kernel);
        Self { home, root, kernel }
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

    fn json_ok(&self, args: &[&str]) -> Value {
        let output = self.run_output(args);
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

fn write_file(path: &Path, contents: &str) {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).expect("parent dir");
    }
    fs::write(path, contents).expect("write file");
}

fn scaffold_kernel_fixture(root: &Path) {
    let kernel_dir = root.join("kernel");
    fs::create_dir_all(&kernel_dir).expect("kernel dir");
    write_file(
        &kernel_dir.join("runtimes.json"),
        "{\n  \"runtimes\": {\n    \"local_kernel\": {\"id\": \"local_kernel\", \"label\": \"Local Kernel Runtime\"},\n    \"loom_native\": {\"status\": \"official\", \"notes\": \"init nation fixture\", \"contract_compliance\": {\"agent_identity\": true, \"action_envelope\": true, \"cost_attribution\": true, \"approval_hook\": true, \"audit_emission\": true, \"sanction_controls\": true, \"budget_gate\": true}}\n  }\n}\n",
    );

    write_file(
        &kernel_dir.join("organizations.py"),
        r#"import json
import pathlib
import time

STORE = pathlib.Path(__file__).resolve().parent / "_organizations.json"

def _now():
    return str(int(time.time()))

def load_orgs():
    if STORE.exists():
        return json.loads(STORE.read_text())
    return {"organizations": {}}

def save_orgs(data):
    STORE.write_text(json.dumps(data, indent=2) + "\n")
"#,
    );

    write_file(
        &kernel_dir.join("agent_registry.py"),
        r#"import json
import pathlib

STORE = pathlib.Path(__file__).resolve().parent / "_agents.json"

def _load():
    if STORE.exists():
        return json.loads(STORE.read_text())
    return {"agents": {}}

def _save(data):
    STORE.write_text(json.dumps(data, indent=2) + "\n")

def list_agents(org_id=None, include_disabled=False):
    data = _load()
    agents = list(data.get("agents", {}).values())
    if org_id:
        agents = [a for a in agents if a.get("org_id") == org_id]
    return agents

def get_agent(agent_id, org_id=None):
    data = _load()
    agent = data.get("agents", {}).get(agent_id)
    if not agent:
        return None
    if org_id and agent.get("org_id") != org_id:
        return None
    return agent
"#,
    );

    write_file(
        &kernel_dir.join("bootstrap.py"),
        r#"import json
import pathlib
import time
from organizations import load_orgs, save_orgs
import agent_registry

SEED = [
    ("Manager", "manager"),
    ("Atlas", "analyst"),
    ("Sentinel", "verifier"),
    ("Forge", "executor"),
    ("Quill", "writer"),
    ("Aegis", "qa_gate"),
    ("Pulse", "compressor"),
]

AGENTS_STORE = pathlib.Path(__file__).resolve().parent / "_agents.json"

def _now():
    return str(int(time.time()))

def _slugify(value):
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-") or "nation"

def _load_agents():
    if AGENTS_STORE.exists():
        return json.loads(AGENTS_STORE.read_text())
    return {"agents": {}}

def _save_agents(data):
    AGENTS_STORE.write_text(json.dumps(data, indent=2) + "\n")

def bootstrap(name=None, owner_id=None, slug=None, charter=None, plan="enterprise"):
    org_name = (name or "Demo Org").strip() or "Demo Org"
    org_owner = (owner_id or "user_owner").strip() or "user_owner"
    org_slug = (slug or _slugify(org_name)).strip() or "nation"
    org_charter = (charter or "Default charter").strip() or "Default charter"

    orgs = load_orgs()
    organizations = orgs.setdefault("organizations", {})
    org_id = None
    for oid, org in organizations.items():
        if org.get("slug") == org_slug:
            org_id = oid
            break
    if org_id is None:
        org_id = f"org_{org_slug.replace('-', '_')}"
        organizations[org_id] = {
            "id": org_id,
            "name": org_name,
            "slug": org_slug,
            "owner_id": org_owner,
            "plan": plan,
            "status": "active",
            "charter": org_charter,
            "created_at": _now(),
            "updated_at": _now(),
        }
    else:
        organizations[org_id]["charter"] = org_charter
        organizations[org_id]["updated_at"] = _now()
    save_orgs(orgs)

    agents_data = _load_agents()
    agents = agents_data.setdefault("agents", {})
    for name, role in SEED:
        found = None
        for existing in agents.values():
            if existing.get("org_id") == org_id and existing.get("name") == name:
                found = existing
                break
        if found:
            continue
        agent_id = f"agent_{name.lower()}_{org_id[-6:]}"
        agents[agent_id] = {
            "id": agent_id,
            "org_id": org_id,
            "name": name,
            "role": role,
            "runtime_binding": {"runtime_id": "loom_native", "runtime_label": "Loom Native Runtime"},
            "rollout_state": "active",
        }
    _save_agents(agents_data)
"#,
    );

    write_file(
        &kernel_dir.join("treasury.py"),
        r#"import json
import pathlib

WALLETS_STORE = pathlib.Path(__file__).resolve().parent / "_wallets.json"
ACCOUNTS_STORE = pathlib.Path(__file__).resolve().parent / "_accounts.json"

def _load(path):
    if path.exists():
        return json.loads(path.read_text())
    return {}

def _save(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")

def get_wallet(wallet_id, org_id=None):
    wallets = _load(WALLETS_STORE)
    wallet = wallets.get(wallet_id)
    if not wallet:
        return None
    if org_id and wallet.get("org_id") != org_id:
        return None
    return wallet

def get_treasury_account(account_id, org_id=None):
    accounts = _load(ACCOUNTS_STORE)
    account = accounts.get(account_id)
    if not account:
        return None
    if org_id and account.get("org_id") != org_id:
        return None
    return account

def register_wallet(wallet_id, address, *, actor_id="", org_id=None, label="", **kwargs):
    wallets = _load(WALLETS_STORE)
    if wallet_id in wallets:
        raise ValueError("wallet exists")
    wallets[wallet_id] = {
        "wallet_id": wallet_id,
        "org_id": org_id,
        "address": address,
        "label": label,
        "actor_id": actor_id,
    }
    _save(WALLETS_STORE, wallets)
    return wallets[wallet_id]

def register_treasury_account(account_id, *, wallet_id="", actor_id="", org_id=None, label="", **kwargs):
    accounts = _load(ACCOUNTS_STORE)
    if account_id in accounts:
        raise ValueError("account exists")
    accounts[account_id] = {
        "account_id": account_id,
        "wallet_id": wallet_id,
        "org_id": org_id,
        "label": label,
        "actor_id": actor_id,
    }
    _save(ACCOUNTS_STORE, accounts)
    return accounts[account_id]
"#,
    );

    write_file(
        &root.join("ops_provision_hot_wallet.py"),
        r#"#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
KERNEL = ROOT / "kernel"
sys.path.insert(0, str(KERNEL))
import treasury

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--org_id", default=None)
    parser.add_argument("--wallet_id", required=True)
    parser.add_argument("--account_id", required=True)
    parser.add_argument("--actor_id", default="ops:test")
    parser.add_argument("--secret_dir", default=".hot-wallet-secrets")
    parser.add_argument("--wallet_label", default="Hot Wallet")
    parser.add_argument("--account_label", default="Settlement Account")
    parser.add_argument("--account_purpose", default="settlement")
    parser.add_argument("--reserve_floor_usd", type=float, default=0.0)
    return parser.parse_args()

def main():
    args = parse_args()
    if treasury.get_wallet(args.wallet_id, args.org_id):
        raise SystemExit("Wallet already exists")
    if treasury.get_treasury_account(args.account_id, args.org_id):
        raise SystemExit("Treasury account already exists")

    digest = hashlib.sha256(args.wallet_id.encode("utf-8")).hexdigest()[:40]
    address = "0x" + digest
    wallet = treasury.register_wallet(
        args.wallet_id,
        address,
        actor_id=args.actor_id,
        org_id=args.org_id,
        label=args.wallet_label,
    )
    account = treasury.register_treasury_account(
        args.account_id,
        wallet_id=args.wallet_id,
        actor_id=args.actor_id,
        org_id=args.org_id,
        label=args.account_label,
    )
    secret_root = pathlib.Path(args.secret_dir)
    if not secret_root.is_absolute():
        secret_root = ROOT / secret_root
    secret_root.mkdir(parents=True, exist_ok=True)
    secret_path = secret_root / f"{args.wallet_id}.json"
    secret_path.write_text(json.dumps({"wallet_id": args.wallet_id, "address": address}, indent=2) + "\n")
    os.chmod(secret_path, 0o600)
    print(json.dumps({
        "wallet": wallet,
        "account": account,
        "address": address,
        "secret_path": str(secret_path),
        "secret_file_mode": "0o600",
    }, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
"#,
    );
}

#[test]
fn init_nation_one_command_bootstraps_vertical_slice() {
    let harness = Harness::new("init_nation_bootstrap");
    let output = harness.json_ok(&[
        "init-nation",
        "--charter",
        "My Company",
        "--root",
        harness.root_str(),
        "--kernel-path",
        harness.kernel_str(),
        "--org-id",
        "my_company",
        "--format",
        "json",
    ]);
    assert_eq!(
        output.get("status").and_then(Value::as_str),
        Some("init_nation_ready")
    );
    assert_eq!(
        output.get("seed_agents_count").and_then(Value::as_u64),
        Some(7)
    );
    assert!(harness.root.join("loom.toml").exists());
    assert!(harness.root.join("state/gateway/registry.json").exists());
    assert!(harness.root.join("state/nation/init_last.json").exists());
}

#[test]
fn init_nation_is_idempotent_on_second_run() {
    let harness = Harness::new("init_nation_idempotent");
    let _first = harness.json_ok(&[
        "init-nation",
        "--charter",
        "My Company",
        "--root",
        harness.root_str(),
        "--kernel-path",
        harness.kernel_str(),
        "--org-id",
        "my_company",
        "--format",
        "json",
    ]);
    let second = harness.json_ok(&[
        "init-nation",
        "--charter",
        "My Company",
        "--root",
        harness.root_str(),
        "--kernel-path",
        harness.kernel_str(),
        "--org-id",
        "my_company",
        "--format",
        "json",
    ]);
    assert_eq!(
        second.get("status").and_then(Value::as_str),
        Some("init_nation_ready")
    );
    assert_eq!(
        second.get("seed_agents_count").and_then(Value::as_u64),
        Some(7)
    );
    assert_eq!(
        second.get("hot_wallet_status").and_then(Value::as_str),
        Some("reused")
    );
}
