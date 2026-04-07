use std::io::IsTerminal;
use std::path::{Path, PathBuf};

use crate::*;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

const EXTENSION_CONTRACT_SCHEMA: &str = "meridian.extension.contract.v1";
const EXTENSION_REGISTRY_SCHEMA: &str = "meridian.extension.registry.v1";
const EXTENSION_RECEIPT_SCHEMA: &str = "meridian.extension.rollback_receipt.v1";
const DEFAULT_EXTENSION_REGISTRY_PATH: &str = "state/extensions/registry.json";
const DEFAULT_EXTENSION_MANIFESTS_DIR: &str = "state/extensions/manifests";
const DEFAULT_EXTENSION_ROLLBACK_DIR: &str = "state/extensions/rollback";
const DEFAULT_EXTENSION_RECEIPTS_DIR: &str = "artifacts/extensions/receipts";
const DEFAULT_EXTENSION_LATEST_ARTIFACT_PATH: &str = "artifacts/extensions/latest.json";

pub(crate) fn handle_extension(args: &[String]) -> LoomResult<()> {
    if args.is_empty()
        || matches!(
            args.first().map(String::as_str),
            Some("help" | "--help" | "-h")
        )
    {
        print_extension_help();
        return Ok(());
    }
    match args.first().map(String::as_str) {
        Some("validate") => handle_extension_validate(&args[1..]),
        Some("install") => handle_extension_install(&args[1..]),
        Some("remove") => handle_extension_remove(&args[1..]),
        Some("export") => handle_extension_export(&args[1..]),
        _ => Err("extension supports 'validate', 'install', 'remove', and 'export'".to_string()),
    }
}

fn print_extension_help() {
    println!(
        "Meridian Loom // EXTENSION

Validate and manage extension contracts with rollback receipts.

USAGE: loom extension <COMMAND> [OPTIONS]

COMMANDS:
  validate --manifest PATH [--root ROOT] [--format human|json]
  install  --manifest PATH [--root ROOT] [--format human|json]
  remove   --extension-id ID [--root ROOT] [--format human|json]
  export   --extension-id ID --out PATH [--root ROOT] [--format human|json]"
    );
}

fn handle_extension_validate(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = output_format(args);
    let manifest_path = required_flag(args, "--manifest")?;
    let manifest_path_buf = PathBuf::from(manifest_path);
    let manifest = load_manifest(&manifest_path_buf)?;
    let errors = validate_manifest(&manifest);
    if !errors.is_empty() {
        return Err(format!(
            "extension contract invalid:\n- {}",
            errors.join("\n- ")
        ));
    }
    let extension_id = manifest
        .get("extension_id")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let payload = json!({
        "status": "extension_contract_valid",
        "schema_version": EXTENSION_CONTRACT_SCHEMA,
        "extension_id": extension_id,
        "manifest_path": manifest_path_buf.display().to_string(),
        "registry_path": extension_registry_path(&root).display().to_string(),
        "governance_guards": governance_guards_from_manifest(&manifest),
        "provider_mode": manifest.pointer("/provider_config/mode").and_then(Value::as_str).unwrap_or(""),
        "note": "extension contract validated for agnostic provider routing and governed execution boundary",
    });
    print_extension_payload(&payload, &format)
}

fn handle_extension_install(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = output_format(args);
    let manifest_path = required_flag(args, "--manifest")?;
    let manifest_path_buf = PathBuf::from(manifest_path);
    let manifest = load_manifest(&manifest_path_buf)?;
    let errors = validate_manifest(&manifest);
    if !errors.is_empty() {
        return Err(format!(
            "extension contract invalid:\n- {}",
            errors.join("\n- ")
        ));
    }
    let extension_id = manifest
        .get("extension_id")
        .and_then(Value::as_str)
        .ok_or_else(|| "extension manifest missing extension_id".to_string())?
        .to_string();
    let now = chrono_like_timestamp();
    let receipt_id = format!(
        "extrcpt_{}_install_{}",
        now,
        sanitize_token(extension_id.as_str())
    );
    let mut registry = load_extension_registry(&root)?;
    let pre_registry_snapshot_path =
        write_registry_snapshot(&root, receipt_id.as_str(), "install_pre", &registry)?;
    let mode = if find_extension(&registry, extension_id.as_str()).is_some() {
        "updated"
    } else {
        "created"
    };
    let manifest_store_path = extension_manifest_path(&root, extension_id.as_str());
    if let Some(parent) = manifest_store_path.parent() {
        std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }

    let mut rollback_action = "remove".to_string();
    let mut rollback_manifest_backup_path = String::new();
    if mode == "updated" && manifest_store_path.exists() {
        let backup_path =
            extension_rollback_manifest_path(&root, receipt_id.as_str(), extension_id.as_str());
        if let Some(parent) = backup_path.parent() {
            std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
        }
        std::fs::copy(&manifest_store_path, &backup_path).map_err(|error| error.to_string())?;
        rollback_action = "restore_manifest".to_string();
        rollback_manifest_backup_path = backup_path.display().to_string();
    }

    let manifest_text =
        serde_json::to_string_pretty(&manifest).map_err(|error| error.to_string())? + "\n";
    std::fs::write(&manifest_store_path, manifest_text.as_bytes())
        .map_err(|error| error.to_string())?;
    let checksum_sha256 = sha256_hex(manifest_text.as_bytes());

    upsert_registry_entry(
        &mut registry,
        json!({
            "extension_id": extension_id,
            "name": manifest.get("name").and_then(Value::as_str).unwrap_or(""),
            "version": manifest.get("version").and_then(Value::as_str).unwrap_or(""),
            "status": "installed",
            "installed_at": now,
            "updated_at": now,
            "manifest_path": manifest_store_path.display().to_string(),
            "checksum_sha256": checksum_sha256,
            "governance_guards": governance_guards_from_manifest(&manifest),
        }),
    )?;
    persist_extension_registry(&root, &registry)?;

    let rollback_command = if rollback_action == "restore_manifest" {
        format!(
            "loom extension install --manifest \"{}\" --root \"{}\" --format json",
            rollback_manifest_backup_path,
            root.display()
        )
    } else {
        format!(
            "loom extension remove --extension-id {} --root \"{}\" --format json",
            extension_id,
            root.display()
        )
    };
    let receipt_payload = json!({
        "schema_version": EXTENSION_RECEIPT_SCHEMA,
        "receipt_id": receipt_id,
        "timestamp": now,
        "operation": "install",
        "mode": mode,
        "extension_id": extension_id,
        "manifest_store_path": manifest_store_path.display().to_string(),
        "registry_path": extension_registry_path(&root).display().to_string(),
        "governance_guards": governance_guards_from_manifest(&manifest),
        "rollback": {
            "action": rollback_action,
            "command": rollback_command,
            "restore_manifest_path": rollback_manifest_backup_path,
            "registry_snapshot_path": pre_registry_snapshot_path.display().to_string(),
        },
    });
    let receipt_path = write_receipt(&root, receipt_id.as_str(), &receipt_payload)?;
    write_latest_artifact(&root, &receipt_payload)?;

    let payload = json!({
        "status": "extension_installed",
        "mode": mode,
        "extension_id": extension_id,
        "manifest_store_path": manifest_store_path.display().to_string(),
        "registry_path": extension_registry_path(&root).display().to_string(),
        "receipt_path": receipt_path.display().to_string(),
        "rollback_action": receipt_payload.pointer("/rollback/action").and_then(Value::as_str).unwrap_or(""),
        "note": "extension installed with rollback receipt under governed extension contract v1",
    });
    print_extension_payload(&payload, &format)
}

fn handle_extension_remove(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = output_format(args);
    let extension_id = required_flag(args, "--extension-id")?;
    let now = chrono_like_timestamp();
    let receipt_id = format!(
        "extrcpt_{}_remove_{}",
        now,
        sanitize_token(extension_id.as_str())
    );
    let mut registry = load_extension_registry(&root)?;
    let existing = find_extension(&registry, extension_id.as_str())
        .cloned()
        .ok_or_else(|| format!("extension '{}' is not installed", extension_id))?;
    let pre_registry_snapshot_path =
        write_registry_snapshot(&root, receipt_id.as_str(), "remove_pre", &registry)?;
    let manifest_path = existing
        .get("manifest_path")
        .and_then(Value::as_str)
        .map(PathBuf::from)
        .unwrap_or_else(|| extension_manifest_path(&root, extension_id.as_str()));
    if !manifest_path.exists() {
        return Err(format!(
            "installed manifest is missing for extension '{}': {}",
            extension_id,
            manifest_path.display()
        ));
    }

    let rollback_manifest_backup_path =
        extension_rollback_manifest_path(&root, receipt_id.as_str(), extension_id.as_str());
    if let Some(parent) = rollback_manifest_backup_path.parent() {
        std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    std::fs::copy(&manifest_path, &rollback_manifest_backup_path)
        .map_err(|error| error.to_string())?;
    std::fs::remove_file(&manifest_path).map_err(|error| error.to_string())?;

    remove_registry_entry(&mut registry, extension_id.as_str())?;
    persist_extension_registry(&root, &registry)?;

    let rollback_command = format!(
        "loom extension install --manifest \"{}\" --root \"{}\" --format json",
        rollback_manifest_backup_path.display(),
        root.display()
    );
    let receipt_payload = json!({
        "schema_version": EXTENSION_RECEIPT_SCHEMA,
        "receipt_id": receipt_id,
        "timestamp": now,
        "operation": "remove",
        "extension_id": extension_id,
        "removed_manifest_path": manifest_path.display().to_string(),
        "registry_path": extension_registry_path(&root).display().to_string(),
        "rollback": {
            "action": "reinstall_from_backup",
            "command": rollback_command,
            "restore_manifest_path": rollback_manifest_backup_path.display().to_string(),
            "registry_snapshot_path": pre_registry_snapshot_path.display().to_string(),
        },
    });
    let receipt_path = write_receipt(&root, receipt_id.as_str(), &receipt_payload)?;
    write_latest_artifact(&root, &receipt_payload)?;

    let payload = json!({
        "status": "extension_removed",
        "extension_id": extension_id,
        "registry_path": extension_registry_path(&root).display().to_string(),
        "receipt_path": receipt_path.display().to_string(),
        "rollback_action": "reinstall_from_backup",
        "note": "extension removed with rollback manifest backup",
    });
    print_extension_payload(&payload, &format)
}

fn handle_extension_export(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = output_format(args);
    let extension_id = required_flag(args, "--extension-id")?;
    let out_path = required_flag(args, "--out")?;
    let registry = load_extension_registry(&root)?;
    let existing = find_extension(&registry, extension_id.as_str())
        .ok_or_else(|| format!("extension '{}' is not installed", extension_id))?;
    let manifest_path = existing
        .get("manifest_path")
        .and_then(Value::as_str)
        .map(PathBuf::from)
        .unwrap_or_else(|| extension_manifest_path(&root, extension_id.as_str()));
    let manifest = load_manifest(&manifest_path)?;
    let out_path_buf = PathBuf::from(out_path);
    if let Some(parent) = out_path_buf.parent() {
        std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    std::fs::write(
        &out_path_buf,
        serde_json::to_string_pretty(&manifest).map_err(|error| error.to_string())? + "\n",
    )
    .map_err(|error| error.to_string())?;
    let payload = json!({
        "status": "extension_exported",
        "extension_id": extension_id,
        "manifest_path": manifest_path.display().to_string(),
        "out_path": out_path_buf.display().to_string(),
        "schema_version": manifest.get("schema_version").and_then(Value::as_str).unwrap_or(""),
    });
    print_extension_payload(&payload, &format)
}

fn print_extension_payload(payload: &Value, format: &str) -> LoomResult<()> {
    match format {
        "human" => {
            print_startup_banner();
            let mut lines = vec![format!(
                "status:              {}",
                payload
                    .get("status")
                    .and_then(Value::as_str)
                    .unwrap_or("unknown")
            )];
            if let Some(mode) = payload.get("mode").and_then(Value::as_str) {
                lines.push(format!("mode:                {}", mode));
            }
            if let Some(extension_id) = payload.get("extension_id").and_then(Value::as_str) {
                lines.push(format!("extension_id:        {}", extension_id));
            }
            if let Some(path) = payload.get("manifest_path").and_then(Value::as_str) {
                lines.push(format!("manifest_path:       {}", path));
            }
            if let Some(path) = payload.get("manifest_store_path").and_then(Value::as_str) {
                lines.push(format!("manifest_store_path: {}", path));
            }
            if let Some(path) = payload.get("registry_path").and_then(Value::as_str) {
                lines.push(format!("registry_path:       {}", path));
            }
            if let Some(path) = payload.get("receipt_path").and_then(Value::as_str) {
                lines.push(format!("receipt_path:        {}", path));
            }
            if let Some(path) = payload.get("out_path").and_then(Value::as_str) {
                lines.push(format!("out_path:            {}", path));
            }
            if let Some(action) = payload.get("rollback_action").and_then(Value::as_str) {
                lines.push(format!("rollback_action:     {}", action));
            }
            if let Some(note) = payload.get("note").and_then(Value::as_str) {
                lines.push(format!("note:                {}", note));
            }
            print_human(&(lines.join("\n") + "\n"));
        }
        _ => println!(
            "{}",
            serde_json::to_string_pretty(payload).map_err(|error| error.to_string())?
        ),
    }
    Ok(())
}

fn output_format(args: &[String]) -> String {
    take_value(args, "--format").unwrap_or_else(|| {
        if std::io::stdout().is_terminal() {
            "human".to_string()
        } else {
            "json".to_string()
        }
    })
}

fn load_manifest(path: &Path) -> LoomResult<Value> {
    let raw = std::fs::read_to_string(path).map_err(|error| {
        format!(
            "failed to read extension manifest {}: {error}",
            path.display()
        )
    })?;
    serde_json::from_str::<Value>(&raw).map_err(|error| {
        format!(
            "invalid extension manifest json {}: {error}",
            path.display()
        )
    })
}

fn governance_guards_from_manifest(manifest: &Value) -> Value {
    json!({
        "requires_warrant": manifest.pointer("/permissions/governance/requires_warrant").and_then(Value::as_bool).unwrap_or(false),
        "requires_authority_check": manifest.pointer("/permissions/governance/requires_authority_check").and_then(Value::as_bool).unwrap_or(false),
        "requires_court_check": manifest.pointer("/permissions/governance/requires_court_check").and_then(Value::as_bool).unwrap_or(false),
        "requires_treasury_gate": manifest.pointer("/permissions/governance/requires_treasury_gate").and_then(Value::as_bool).unwrap_or(false),
    })
}

fn validate_manifest(manifest: &Value) -> Vec<String> {
    let mut errors = Vec::new();
    if !manifest.is_object() {
        errors.push("manifest must be a JSON object".to_string());
        return errors;
    }
    if manifest
        .get("schema_version")
        .and_then(Value::as_str)
        .unwrap_or_default()
        != EXTENSION_CONTRACT_SCHEMA
    {
        errors.push(format!(
            "schema_version must be '{}'",
            EXTENSION_CONTRACT_SCHEMA
        ));
    }
    let extension_id = manifest
        .get("extension_id")
        .and_then(Value::as_str)
        .unwrap_or_default();
    if extension_id.is_empty() {
        errors.push("extension_id is required".to_string());
    } else if sanitize_token(extension_id) != extension_id {
        errors
            .push("extension_id must be lowercase token form (letters/digits/hyphen)".to_string());
    }
    if manifest
        .get("name")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .trim()
        .is_empty()
    {
        errors.push("name is required".to_string());
    }
    if manifest
        .get("version")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .trim()
        .is_empty()
    {
        errors.push("version is required".to_string());
    }
    if manifest
        .pointer("/entrypoint/kind")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .trim()
        .is_empty()
    {
        errors.push("entrypoint.kind is required".to_string());
    }
    if manifest
        .pointer("/entrypoint/path")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .trim()
        .is_empty()
    {
        errors.push("entrypoint.path is required".to_string());
    }
    if !manifest
        .get("capabilities")
        .map(Value::is_array)
        .unwrap_or(false)
    {
        errors.push("capabilities must be an array".to_string());
    }
    if manifest
        .pointer("/provider_config/mode")
        .and_then(Value::as_str)
        .unwrap_or_default()
        != "agnostic"
    {
        errors.push("provider_config.mode must be 'agnostic'".to_string());
    }
    let guard_paths = [
        "permissions.governance.requires_warrant",
        "permissions.governance.requires_authority_check",
        "permissions.governance.requires_court_check",
        "permissions.governance.requires_treasury_gate",
    ];
    for path in guard_paths {
        let pointer = format!("/{}", path.replace('.', "/"));
        match manifest.pointer(pointer.as_str()).and_then(Value::as_bool) {
            Some(true) => {}
            _ => errors.push(format!("{} must be true", path)),
        }
    }
    errors
}

fn extension_registry_path(root: &Path) -> PathBuf {
    root.join(DEFAULT_EXTENSION_REGISTRY_PATH)
}

fn extension_manifests_dir(root: &Path) -> PathBuf {
    root.join(DEFAULT_EXTENSION_MANIFESTS_DIR)
}

fn extension_manifest_path(root: &Path, extension_id: &str) -> PathBuf {
    extension_manifests_dir(root).join(format!("{}.json", extension_id))
}

fn extension_rollback_dir(root: &Path) -> PathBuf {
    root.join(DEFAULT_EXTENSION_ROLLBACK_DIR)
}

fn extension_rollback_manifest_path(root: &Path, receipt_id: &str, extension_id: &str) -> PathBuf {
    extension_rollback_dir(root).join(format!(
        "{}_{}_manifest.json",
        receipt_id,
        sanitize_token(extension_id)
    ))
}

fn extension_receipts_dir(root: &Path) -> PathBuf {
    root.join(DEFAULT_EXTENSION_RECEIPTS_DIR)
}

fn extension_latest_artifact_path(root: &Path) -> PathBuf {
    root.join(DEFAULT_EXTENSION_LATEST_ARTIFACT_PATH)
}

fn write_registry_snapshot(
    root: &Path,
    receipt_id: &str,
    suffix: &str,
    registry: &Value,
) -> LoomResult<PathBuf> {
    let path =
        extension_rollback_dir(root).join(format!("{}_{}_registry.json", receipt_id, suffix));
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    std::fs::write(
        &path,
        serde_json::to_string_pretty(registry).map_err(|error| error.to_string())? + "\n",
    )
    .map_err(|error| error.to_string())?;
    Ok(path)
}

fn write_receipt(root: &Path, receipt_id: &str, payload: &Value) -> LoomResult<PathBuf> {
    let path = extension_receipts_dir(root).join(format!("{}.json", receipt_id));
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    std::fs::write(
        &path,
        serde_json::to_string_pretty(payload).map_err(|error| error.to_string())? + "\n",
    )
    .map_err(|error| error.to_string())?;
    Ok(path)
}

fn write_latest_artifact(root: &Path, payload: &Value) -> LoomResult<()> {
    let path = extension_latest_artifact_path(root);
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    std::fs::write(
        path,
        serde_json::to_string_pretty(payload).map_err(|error| error.to_string())? + "\n",
    )
    .map_err(|error| error.to_string())
}

fn load_extension_registry(root: &Path) -> LoomResult<Value> {
    let path = extension_registry_path(root);
    if !path.exists() {
        return Ok(default_extension_registry());
    }
    let raw = std::fs::read_to_string(path).map_err(|error| error.to_string())?;
    let mut value: Value = serde_json::from_str(&raw)
        .map_err(|error| format!("invalid extension registry json: {error}"))?;
    normalize_registry(&mut value);
    Ok(value)
}

fn persist_extension_registry(root: &Path, registry: &Value) -> LoomResult<()> {
    let path = extension_registry_path(root);
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    std::fs::write(
        path,
        serde_json::to_string_pretty(registry).map_err(|error| error.to_string())? + "\n",
    )
    .map_err(|error| error.to_string())
}

fn default_extension_registry() -> Value {
    json!({
        "schema_version": EXTENSION_REGISTRY_SCHEMA,
        "extensions": [],
    })
}

fn normalize_registry(registry: &mut Value) {
    if !registry.is_object() {
        *registry = default_extension_registry();
        return;
    }
    if registry
        .get("schema_version")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .is_empty()
    {
        registry["schema_version"] = Value::String(EXTENSION_REGISTRY_SCHEMA.to_string());
    }
    if !registry
        .get("extensions")
        .map(Value::is_array)
        .unwrap_or(false)
    {
        registry["extensions"] = Value::Array(Vec::new());
    }
    if let Some(items) = registry.get_mut("extensions").and_then(Value::as_array_mut) {
        items.sort_by(|left, right| {
            value_string(left.get("extension_id")).cmp(value_string(right.get("extension_id")))
        });
    }
}

fn find_extension<'a>(registry: &'a Value, extension_id: &str) -> Option<&'a Value> {
    registry
        .get("extensions")
        .and_then(Value::as_array)
        .and_then(|items| {
            items.iter().find(|item| {
                item.get("extension_id")
                    .and_then(Value::as_str)
                    .map(|value| value == extension_id)
                    .unwrap_or(false)
            })
        })
}

fn upsert_registry_entry(registry: &mut Value, entry: Value) -> LoomResult<()> {
    normalize_registry(registry);
    let extension_id = entry
        .get("extension_id")
        .and_then(Value::as_str)
        .ok_or_else(|| "registry entry missing extension_id".to_string())?
        .to_string();
    let items = registry
        .get_mut("extensions")
        .and_then(Value::as_array_mut)
        .ok_or_else(|| "registry missing extensions array".to_string())?;
    if let Some(existing) = items.iter_mut().find(|item| {
        item.get("extension_id")
            .and_then(Value::as_str)
            .map(|value| value == extension_id)
            .unwrap_or(false)
    }) {
        *existing = entry;
    } else {
        items.push(entry);
    }
    items.sort_by(|left, right| {
        value_string(left.get("extension_id")).cmp(value_string(right.get("extension_id")))
    });
    Ok(())
}

fn remove_registry_entry(registry: &mut Value, extension_id: &str) -> LoomResult<()> {
    normalize_registry(registry);
    let items = registry
        .get_mut("extensions")
        .and_then(Value::as_array_mut)
        .ok_or_else(|| "registry missing extensions array".to_string())?;
    let before = items.len();
    items.retain(|item| {
        item.get("extension_id")
            .and_then(Value::as_str)
            .map(|value| value != extension_id)
            .unwrap_or(true)
    });
    if items.len() == before {
        return Err(format!("extension '{}' is not installed", extension_id));
    }
    Ok(())
}

fn value_string(value: Option<&Value>) -> &str {
    value.and_then(Value::as_str).unwrap_or("")
}

fn sha256_hex(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    let digest = hasher.finalize();
    hex::encode(digest)
}
