use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::{json, Value};

use crate::bindings::resolve_binding;
use crate::onboarding::{bind_host_for, load_onboard_manifest, OnboardManifest};
use crate::output_guard::{guard_user_visible_output, OutputGuardPolicy};

pub type LoomResult<T> = Result<T, String>;

pub const DEFAULT_CHANNEL_REGISTRY_PATH: &str = "state/channels/registry.json";
pub const DEFAULT_CHANNEL_DELIVERY_DIR: &str = "state/channels/delivery";
pub const DEFAULT_CHANNEL_INBOX_DIR: &str = "state/channels/inbox";
pub const DEFAULT_CHANNEL_HEALTH_DIR: &str = "state/channels/health";
pub const DEFAULT_CHANNEL_DIAGNOSTICS_DIR: &str = "state/channels/diagnostics";
pub const LEGACY_CHANNEL_ARCHIVE_AFTER_MS: u64 = 5 * 60 * 1000;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ChannelRecord {
    pub channel_id: String,
    pub kind: String,
    pub enabled: bool,
    pub endpoint: String,
    pub auth_mode: String,
    pub credential_ref: String,
    pub dm_policy: String,
    pub group_policy: String,
    pub streaming: String,
    pub note: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ChannelRuntimeOverview {
    pub registry_path: PathBuf,
    pub delivery_path: PathBuf,
    pub inbox_path: PathBuf,
    pub total_count: usize,
    pub enabled_count: usize,
    pub ingress_count: usize,
    pub active_delivery_count: usize,
    pub archived_delivery_count: usize,
    pub channel_ids: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ChannelHealthRecord {
    pub channel_id: String,
    pub kind: String,
    pub enabled: bool,
    pub ready: bool,
    pub health: String,
    pub status_detail: String,
    pub endpoint: String,
    pub latest_delivery_status: String,
    pub latest_delivery_at_unix_ms: u64,
    pub queued_count: usize,
    pub delivered_count: usize,
    pub failed_count: usize,
    pub blocked_count: usize,
    pub archived_delivery_count: usize,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ChannelHealthHistoryRecord {
    pub captured_at_unix_ms: u64,
    pub trigger: String,
    pub channel_id: String,
    pub health: String,
    pub ready: bool,
    pub status_detail: String,
    pub latest_delivery_status: String,
    pub latest_delivery_at_unix_ms: u64,
    pub queued_count: usize,
    pub delivered_count: usize,
    pub failed_count: usize,
    pub blocked_count: usize,
    pub archived_delivery_count: usize,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ChannelTestDiagnosticRecord {
    pub diagnostic_id: String,
    pub delivery_id: String,
    pub channel_id: String,
    pub recipient: String,
    pub submitted_at_unix_ms: u64,
    pub updated_at_unix_ms: u64,
    pub status: String,
    pub ready: bool,
    pub health: String,
    pub status_detail: String,
    pub note: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ChannelSyncResult {
    pub registry_path: PathBuf,
    pub total_count: usize,
    pub enabled_count: usize,
    pub channel_ids: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ChannelDeliveryRequest {
    pub channel_id: String,
    pub recipient: String,
    pub raw_text: String,
    pub allow_receipt_hashes: bool,
    pub allow_operator_diagnostics: bool,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ChannelDeliveryRecord {
    pub delivery_id: String,
    pub channel_id: String,
    pub recipient: String,
    pub submitted_at_unix_ms: u64,
    pub source_class: String,
    pub final_class: String,
    pub allowed: bool,
    pub status: String,
    pub completed_at_unix_ms: u64,
    pub external_ref: String,
    pub status_detail: String,
    pub display_text: String,
    pub deny_reason: String,
    pub redactions_applied: Vec<String>,
    pub detected_tokens: Vec<String>,
    pub quarantined: bool,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ChannelIngressRequest {
    pub channel_id: String,
    pub peer_id: String,
    pub thread_id: Option<String>,
    pub text: String,
    pub agent_override: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ChannelIngressRecord {
    pub ingress_id: String,
    pub channel_id: String,
    pub peer_id: String,
    pub thread_id: Option<String>,
    pub received_at_unix_ms: u64,
    pub binding_id: String,
    pub agent_id: String,
    pub session_key: String,
    pub route_kind: String,
    pub text: String,
}

pub fn channel_registry_path(root: &Path) -> PathBuf {
    root.join(DEFAULT_CHANNEL_REGISTRY_PATH)
}

pub fn channel_delivery_path(root: &Path) -> PathBuf {
    root.join(DEFAULT_CHANNEL_DELIVERY_DIR)
}

pub fn channel_inbox_path(root: &Path) -> PathBuf {
    root.join(DEFAULT_CHANNEL_INBOX_DIR)
}

pub fn channel_health_path(root: &Path) -> PathBuf {
    root.join(DEFAULT_CHANNEL_HEALTH_DIR)
}

pub fn channel_diagnostics_path(root: &Path) -> PathBuf {
    root.join(DEFAULT_CHANNEL_DIAGNOSTICS_DIR)
}

pub fn channel_health_history_path(root: &Path, channel_id: &str) -> PathBuf {
    channel_health_path(root).join(format!("{}.jsonl", safe_file_token(channel_id)))
}

pub fn channel_test_diagnostic_path(root: &Path, delivery_id: &str) -> PathBuf {
    channel_diagnostics_path(root).join(format!("{}.json", safe_file_token(delivery_id)))
}

pub fn ensure_channel_runtime_scaffold(root: &Path) -> LoomResult<PathBuf> {
    let registry_path = channel_registry_path(root);
    if let Some(parent) = registry_path.parent() {
        fs::create_dir_all(parent).map_err(io_err)?;
    }
    fs::create_dir_all(channel_delivery_path(root)).map_err(io_err)?;
    fs::create_dir_all(channel_inbox_path(root)).map_err(io_err)?;
    fs::create_dir_all(channel_health_path(root)).map_err(io_err)?;
    fs::create_dir_all(channel_diagnostics_path(root)).map_err(io_err)?;
    if !registry_path.exists() {
        sync_channel_registry(root)?;
    }
    Ok(registry_path)
}

pub fn sync_channel_registry(root: &Path) -> LoomResult<ChannelSyncResult> {
    let manifest = load_onboard_manifest(root)?;
    let records = channel_records_from_manifest(&manifest);
    persist_channel_registry(root, &records)?;
    Ok(ChannelSyncResult {
        registry_path: channel_registry_path(root),
        total_count: records.len(),
        enabled_count: records.iter().filter(|record| record.enabled).count(),
        channel_ids: records
            .iter()
            .map(|record| record.channel_id.clone())
            .collect(),
    })
}

pub fn load_channels(root: &Path) -> LoomResult<Vec<ChannelRecord>> {
    ensure_channel_runtime_scaffold(root)?;
    let raw = fs::read_to_string(channel_registry_path(root)).map_err(io_err)?;
    parse_channel_registry(&raw)
}

pub fn upsert_channel_record(root: &Path, record: &ChannelRecord) -> LoomResult<PathBuf> {
    let mut records = load_channels(root)?;
    if let Some(existing) = records
        .iter_mut()
        .find(|existing| existing.channel_id == record.channel_id)
    {
        *existing = record.clone();
    } else {
        records.push(record.clone());
        records.sort_by(|left, right| left.channel_id.cmp(&right.channel_id));
    }
    persist_channel_registry(root, &records)?;
    let _ = record_channel_health_snapshots(root, "channel_upsert");
    Ok(channel_registry_path(root))
}

pub fn channel_overview(root: &Path) -> LoomResult<ChannelRuntimeOverview> {
    let records = load_channels(root)?;
    let ingress_count = list_channel_ingress(root, 0)?.len();
    let deliveries = list_channel_deliveries_with_options(root, 0, true, false)?;
    let now = now_unix_ms();
    let archived_delivery_count = deliveries
        .iter()
        .filter(|record| channel_delivery_is_archived(record, now))
        .count();
    Ok(ChannelRuntimeOverview {
        registry_path: channel_registry_path(root),
        delivery_path: channel_delivery_path(root),
        inbox_path: channel_inbox_path(root),
        total_count: records.len(),
        enabled_count: records.iter().filter(|record| record.enabled).count(),
        ingress_count,
        active_delivery_count: deliveries.len().saturating_sub(archived_delivery_count),
        archived_delivery_count,
        channel_ids: records
            .iter()
            .map(|record| record.channel_id.clone())
            .collect(),
    })
}

pub fn list_channel_health(root: &Path) -> LoomResult<Vec<ChannelHealthRecord>> {
    let records = load_channels(root)?;
    let deliveries = list_channel_deliveries_with_options(root, 0, true, false)?;
    let now = now_unix_ms();
    let mut health = Vec::with_capacity(records.len());
    for record in records {
        let related = deliveries
            .iter()
            .filter(|delivery| delivery.channel_id == record.channel_id)
            .collect::<Vec<_>>();
        let queued_count = related
            .iter()
            .filter(|delivery| delivery.status == "queued")
            .count();
        let delivered_count = related
            .iter()
            .filter(|delivery| delivery.status == "delivered")
            .count();
        let failed_count = related
            .iter()
            .filter(|delivery| delivery.status == "failed")
            .count();
        let blocked_count = related
            .iter()
            .filter(|delivery| delivery.status == "blocked")
            .count();
        let archived_delivery_count = related
            .iter()
            .filter(|delivery| channel_delivery_is_archived(delivery, now))
            .count();
        let latest_delivery_status = related
            .first()
            .map(|delivery| delivery.status.clone())
            .unwrap_or_else(|| "none".to_string());
        let latest_delivery_at_unix_ms = related
            .first()
            .map(|delivery| delivery.submitted_at_unix_ms)
            .unwrap_or_default();
        let endpoint_ready = !record.endpoint.trim().is_empty();
        let auth_ready = channel_auth_ready(&record);
        let (health_label, status_detail) = if !record.enabled {
            ("disabled".to_string(), "channel disabled".to_string())
        } else if !endpoint_ready {
            ("degraded".to_string(), "missing endpoint".to_string())
        } else if !auth_ready {
            (
                "degraded".to_string(),
                format!("credential not ready ({})", record.auth_mode),
            )
        } else if failed_count > 0 {
            (
                "warning".to_string(),
                format!("{} failed delivery record(s)", failed_count),
            )
        } else if blocked_count > 0 {
            (
                "warning".to_string(),
                format!("{} blocked delivery record(s)", blocked_count),
            )
        } else if queued_count > 0 {
            (
                "active".to_string(),
                format!("{} queued delivery record(s)", queued_count),
            )
        } else {
            ("healthy".to_string(), "ready".to_string())
        };
        health.push(ChannelHealthRecord {
            channel_id: record.channel_id.clone(),
            kind: record.kind.clone(),
            enabled: record.enabled,
            ready: record.enabled && endpoint_ready && auth_ready,
            health: health_label,
            status_detail,
            endpoint: record.endpoint.clone(),
            latest_delivery_status,
            latest_delivery_at_unix_ms,
            queued_count,
            delivered_count,
            failed_count,
            blocked_count,
            archived_delivery_count,
        });
    }
    health.sort_by(|left, right| left.channel_id.cmp(&right.channel_id));
    Ok(health)
}

pub fn list_channel_health_history(
    root: &Path,
    channel_id: &str,
    limit: usize,
) -> LoomResult<Vec<ChannelHealthHistoryRecord>> {
    ensure_channel_runtime_scaffold(root)?;
    let path = channel_health_history_path(root, channel_id);
    if !path.exists() {
        return Ok(Vec::new());
    }
    let raw = fs::read_to_string(path).map_err(io_err)?;
    let mut records = raw
        .lines()
        .filter(|line| !line.trim().is_empty())
        .filter_map(|line| parse_channel_health_history_record(line).ok())
        .collect::<Vec<_>>();
    records.sort_by(|left, right| right.captured_at_unix_ms.cmp(&left.captured_at_unix_ms));
    if limit > 0 {
        records.truncate(limit);
    }
    Ok(records)
}

pub fn list_channel_test_diagnostics(
    root: &Path,
    channel_id: &str,
    limit: usize,
) -> LoomResult<Vec<ChannelTestDiagnosticRecord>> {
    ensure_channel_runtime_scaffold(root)?;
    let dir = channel_diagnostics_path(root);
    if !dir.exists() {
        return Ok(Vec::new());
    }
    let mut records = Vec::new();
    for entry in fs::read_dir(dir).map_err(io_err)? {
        let entry = entry.map_err(io_err)?;
        let path = entry.path();
        if !path.is_file() {
            continue;
        }
        let raw = fs::read_to_string(path).map_err(io_err)?;
        let record = parse_channel_test_diagnostic_record(&raw)?;
        if record.channel_id == channel_id {
            records.push(record);
        }
    }
    records.sort_by(|left, right| right.updated_at_unix_ms.cmp(&left.updated_at_unix_ms));
    if limit > 0 {
        records.truncate(limit);
    }
    Ok(records)
}

pub fn record_channel_test_diagnostic(
    root: &Path,
    delivery: &ChannelDeliveryRecord,
    note: &str,
) -> LoomResult<ChannelTestDiagnosticRecord> {
    ensure_channel_runtime_scaffold(root)?;
    let health = list_channel_health(root)?
        .into_iter()
        .find(|record| record.channel_id == delivery.channel_id);
    let now = now_unix_ms();
    let diagnostic = ChannelTestDiagnosticRecord {
        diagnostic_id: format!("diag-{}", delivery.delivery_id),
        delivery_id: delivery.delivery_id.clone(),
        channel_id: delivery.channel_id.clone(),
        recipient: delivery.recipient.clone(),
        submitted_at_unix_ms: delivery.submitted_at_unix_ms,
        updated_at_unix_ms: now,
        status: delivery.status.clone(),
        ready: health.as_ref().map(|record| record.ready).unwrap_or(false),
        health: health
            .as_ref()
            .map(|record| record.health.clone())
            .unwrap_or_else(|| "unknown".to_string()),
        status_detail: delivery.status_detail.clone(),
        note: note.trim().to_string(),
    };
    persist_channel_test_diagnostic(root, &diagnostic)?;
    Ok(diagnostic)
}

fn record_channel_health_snapshots(root: &Path, trigger: &str) -> LoomResult<()> {
    for record in list_channel_health(root)? {
        append_channel_health_snapshot(root, &record, trigger)?;
    }
    Ok(())
}

fn append_channel_health_snapshot(
    root: &Path,
    record: &ChannelHealthRecord,
    trigger: &str,
) -> LoomResult<()> {
    ensure_channel_runtime_scaffold(root)?;
    let history_path = channel_health_history_path(root, &record.channel_id);
    if let Some(parent) = history_path.parent() {
        fs::create_dir_all(parent).map_err(io_err)?;
    }
    let previous = list_channel_health_history(root, &record.channel_id, 1)?
        .into_iter()
        .next();
    let captured_at_unix_ms = previous.as_ref().map_or_else(now_unix_ms, |value| {
        now_unix_ms().max(value.captured_at_unix_ms.saturating_add(1))
    });
    let history_record = ChannelHealthHistoryRecord {
        captured_at_unix_ms,
        trigger: trigger.trim().to_string(),
        channel_id: record.channel_id.clone(),
        health: record.health.clone(),
        ready: record.ready,
        status_detail: record.status_detail.clone(),
        latest_delivery_status: record.latest_delivery_status.clone(),
        latest_delivery_at_unix_ms: record.latest_delivery_at_unix_ms,
        queued_count: record.queued_count,
        delivered_count: record.delivered_count,
        failed_count: record.failed_count,
        blocked_count: record.blocked_count,
        archived_delivery_count: record.archived_delivery_count,
    };
    if let Some(previous) = previous.as_ref() {
        if previous.health == history_record.health
            && previous.ready == history_record.ready
            && previous.status_detail == history_record.status_detail
            && previous.latest_delivery_status == history_record.latest_delivery_status
            && previous.queued_count == history_record.queued_count
            && previous.delivered_count == history_record.delivered_count
            && previous.failed_count == history_record.failed_count
            && previous.blocked_count == history_record.blocked_count
            && previous.archived_delivery_count == history_record.archived_delivery_count
        {
            return Ok(());
        }
    }
    let mut file = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(history_path)
        .map_err(io_err)?;
    let rendered = serde_json::to_string(&channel_health_history_json(&history_record))
        .map_err(|error| error.to_string())?;
    use std::io::Write;
    writeln!(file, "{}", rendered).map_err(io_err)
}

fn sync_channel_test_diagnostic(
    root: &Path,
    delivery: &ChannelDeliveryRecord,
) -> LoomResult<Option<ChannelTestDiagnosticRecord>> {
    let path = channel_test_diagnostic_path(root, &delivery.delivery_id);
    if !path.exists() {
        return Ok(None);
    }
    let raw = fs::read_to_string(&path).map_err(io_err)?;
    let mut diagnostic = parse_channel_test_diagnostic_record(&raw)?;
    let health = list_channel_health(root)?
        .into_iter()
        .find(|record| record.channel_id == delivery.channel_id);
    diagnostic.updated_at_unix_ms = now_unix_ms();
    diagnostic.status = delivery.status.clone();
    diagnostic.ready = health.as_ref().map(|record| record.ready).unwrap_or(false);
    diagnostic.health = health
        .as_ref()
        .map(|record| record.health.clone())
        .unwrap_or_else(|| "unknown".to_string());
    diagnostic.status_detail = if delivery.status_detail.trim().is_empty() {
        delivery.deny_reason.clone()
    } else {
        delivery.status_detail.clone()
    };
    persist_channel_test_diagnostic(root, &diagnostic)?;
    Ok(Some(diagnostic))
}

fn persist_channel_test_diagnostic(
    root: &Path,
    diagnostic: &ChannelTestDiagnosticRecord,
) -> LoomResult<PathBuf> {
    ensure_channel_runtime_scaffold(root)?;
    let path = channel_test_diagnostic_path(root, &diagnostic.delivery_id);
    let rendered = serde_json::to_string_pretty(&channel_test_diagnostic_json(diagnostic))
        .map_err(|error| error.to_string())?;
    atomic_write_text(&path, &format!("{}\n", rendered))?;
    Ok(path)
}

pub fn enqueue_channel_delivery(
    root: &Path,
    request: &ChannelDeliveryRequest,
) -> LoomResult<ChannelDeliveryRecord> {
    let channel_id = request.channel_id.trim();
    if channel_id.is_empty() {
        return Err("channel_id is required".to_string());
    }
    let recipient = request.recipient.trim();
    if recipient.is_empty() {
        return Err("recipient is required".to_string());
    }

    let channels = load_channels(root)?;
    let channel = channels
        .iter()
        .find(|record| record.channel_id == channel_id)
        .ok_or_else(|| format!("channel '{}' was not found", channel_id))?;

    let submitted_at_unix_ms = now_unix_ms();
    let delivery_id = format!("delivery-{}", unique_token());
    let mut delivery = if !channel.enabled {
        ChannelDeliveryRecord {
            delivery_id,
            channel_id: channel.channel_id.clone(),
            recipient: recipient.to_string(),
            submitted_at_unix_ms,
            source_class: "channel_disabled".to_string(),
            final_class: "blocked".to_string(),
            allowed: false,
            status: "blocked".to_string(),
            completed_at_unix_ms: 0,
            external_ref: String::new(),
            status_detail: String::new(),
            display_text: String::new(),
            deny_reason: format!("channel '{}' is disabled", channel.channel_id),
            redactions_applied: Vec::new(),
            detected_tokens: Vec::new(),
            quarantined: false,
        }
    } else {
        let guarded = guard_user_visible_output(
            &request.raw_text,
            &OutputGuardPolicy {
                allow_receipt_hashes: request.allow_receipt_hashes,
                allow_operator_diagnostics: request.allow_operator_diagnostics,
            },
        )?;
        ChannelDeliveryRecord {
            delivery_id,
            channel_id: channel.channel_id.clone(),
            recipient: recipient.to_string(),
            submitted_at_unix_ms,
            source_class: guarded.source_class,
            final_class: guarded.final_class,
            allowed: guarded.allowed,
            status: if guarded.allowed {
                "queued".to_string()
            } else {
                "blocked".to_string()
            },
            completed_at_unix_ms: 0,
            external_ref: String::new(),
            status_detail: String::new(),
            display_text: guarded.display_text,
            deny_reason: guarded.deny_reason.unwrap_or_default(),
            redactions_applied: guarded.redactions_applied,
            detected_tokens: guarded.detected_tokens,
            quarantined: false,
        }
    };

    persist_delivery_record(root, &delivery)?;
    let _ = record_channel_health_snapshots(root, "delivery_enqueued");
    delivery.display_text = delivery.display_text.trim().to_string();
    Ok(delivery)
}

pub fn update_channel_delivery(
    root: &Path,
    delivery_id: &str,
    status: &str,
    external_ref: Option<&str>,
    status_detail: Option<&str>,
) -> LoomResult<ChannelDeliveryRecord> {
    ensure_channel_runtime_scaffold(root)?;
    let delivery_id = delivery_id.trim();
    if delivery_id.is_empty() {
        return Err("delivery_id is required".to_string());
    }
    let status = status.trim();
    if status.is_empty() {
        return Err("status is required".to_string());
    }
    match status {
        "queued" | "delivered" | "failed" | "blocked" | "legacy_unclosed" => {}
        _ => return Err(format!("unsupported channel delivery status '{}'", status)),
    }

    let mut matched_path: Option<PathBuf> = None;
    let mut record: Option<ChannelDeliveryRecord> = None;
    for entry in fs::read_dir(channel_delivery_path(root)).map_err(io_err)? {
        let entry = entry.map_err(io_err)?;
        if !entry.file_type().map_err(io_err)?.is_file() {
            continue;
        }
        let path = entry.path();
        if path.extension().and_then(|value| value.to_str()) != Some("json") {
            continue;
        }
        let raw = fs::read_to_string(&path).map_err(io_err)?;
        let candidate = parse_delivery_record(&raw)?;
        if candidate.delivery_id == delivery_id {
            matched_path = Some(path);
            record = Some(candidate);
            break;
        }
    }

    let path = matched_path.ok_or_else(|| format!("delivery '{}' was not found", delivery_id))?;
    let mut record = record.expect("matched record");
    record.status = status.to_string();
    if matches!(status, "delivered" | "failed" | "blocked") {
        record.completed_at_unix_ms = now_unix_ms();
    } else {
        record.completed_at_unix_ms = 0;
    }
    if let Some(external_ref) = external_ref {
        record.external_ref = external_ref.trim().to_string();
    }
    if let Some(status_detail) = status_detail {
        record.status_detail = status_detail.trim().to_string();
    }
    persist_delivery_record_at_path(&path, &record)?;
    let _ = sync_channel_test_diagnostic(root, &record);
    let _ = record_channel_health_snapshots(root, "delivery_updated");
    Ok(record)
}

pub fn list_channel_deliveries(
    root: &Path,
    limit: usize,
) -> LoomResult<Vec<ChannelDeliveryRecord>> {
    list_channel_deliveries_with_options(root, limit, false, false)
}

pub fn list_channel_deliveries_with_options(
    root: &Path,
    limit: usize,
    include_archived: bool,
    archived_only: bool,
) -> LoomResult<Vec<ChannelDeliveryRecord>> {
    ensure_channel_runtime_scaffold(root)?;
    let mut records = Vec::new();
    for entry in fs::read_dir(channel_delivery_path(root)).map_err(io_err)? {
        let entry = entry.map_err(io_err)?;
        if !entry.file_type().map_err(io_err)?.is_file() {
            continue;
        }
        let path = entry.path();
        if path.extension().and_then(|value| value.to_str()) != Some("json") {
            continue;
        }
        let raw = fs::read_to_string(&path).map_err(io_err)?;
        records.push(parse_delivery_record(&raw)?);
    }
    records.sort_by(|left, right| {
        right
            .submitted_at_unix_ms
            .cmp(&left.submitted_at_unix_ms)
            .then_with(|| right.delivery_id.cmp(&left.delivery_id))
    });
    if archived_only {
        let now = now_unix_ms();
        records.retain(|record| channel_delivery_is_archived(record, now));
    } else if !include_archived {
        let now = now_unix_ms();
        records.retain(|record| !channel_delivery_is_archived(record, now));
    }
    if limit > 0 && records.len() > limit {
        records.truncate(limit);
    }
    Ok(records)
}

fn channel_delivery_is_archived(record: &ChannelDeliveryRecord, now_unix_ms: u64) -> bool {
    if record.quarantined {
        return true;
    }
    match record.status.as_str() {
        "legacy_unclosed" => true,
        "failed" | "blocked" => {
            let anchor = if record.completed_at_unix_ms > 0 {
                record.completed_at_unix_ms
            } else {
                record.submitted_at_unix_ms
            };
            anchor > 0 && now_unix_ms.saturating_sub(anchor) >= LEGACY_CHANNEL_ARCHIVE_AFTER_MS
        }
        _ => false,
    }
}

pub fn ingest_channel_message(
    root: &Path,
    request: &ChannelIngressRequest,
) -> LoomResult<ChannelIngressRecord> {
    let channel_id = request.channel_id.trim();
    if channel_id.is_empty() {
        return Err("channel_id is required".to_string());
    }
    let peer_id = request.peer_id.trim();
    if peer_id.is_empty() {
        return Err("peer_id is required".to_string());
    }
    let text = request.text.trim();
    if text.is_empty() {
        return Err("text is required".to_string());
    }

    let channels = load_channels(root)?;
    let channel = channels
        .iter()
        .find(|record| record.channel_id == channel_id)
        .ok_or_else(|| format!("channel '{}' was not found", channel_id))?;
    if !channel.enabled {
        return Err(format!("channel '{}' is disabled", channel.channel_id));
    }

    let resolution = resolve_binding(
        root,
        channel_id,
        peer_id,
        request.thread_id.as_deref(),
        request.agent_override.as_deref(),
    )?;
    let record = ChannelIngressRecord {
        ingress_id: format!("ingress-{}", unique_token()),
        channel_id: channel.channel_id.clone(),
        peer_id: peer_id.to_string(),
        thread_id: request
            .thread_id
            .as_deref()
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .map(|value| value.to_string()),
        received_at_unix_ms: now_unix_ms(),
        binding_id: resolution.binding_id,
        agent_id: resolution.agent_id,
        session_key: resolution.session_key,
        route_kind: resolution.route_kind,
        text: text.to_string(),
    };
    persist_ingress_record(root, &record)?;
    Ok(record)
}

pub fn list_channel_ingress(root: &Path, limit: usize) -> LoomResult<Vec<ChannelIngressRecord>> {
    ensure_channel_runtime_scaffold(root)?;
    let mut records = Vec::new();
    for entry in fs::read_dir(channel_inbox_path(root)).map_err(io_err)? {
        let entry = entry.map_err(io_err)?;
        if !entry.file_type().map_err(io_err)?.is_file() {
            continue;
        }
        let path = entry.path();
        if path.extension().and_then(|value| value.to_str()) != Some("json") {
            continue;
        }
        let raw = fs::read_to_string(&path).map_err(io_err)?;
        records.push(parse_ingress_record(&raw)?);
    }
    records.sort_by(|left, right| {
        right
            .received_at_unix_ms
            .cmp(&left.received_at_unix_ms)
            .then_with(|| right.ingress_id.cmp(&left.ingress_id))
    });
    if limit > 0 && records.len() > limit {
        records.truncate(limit);
    }
    Ok(records)
}

pub fn render_channel_overview_human(summary: &ChannelRuntimeOverview) -> String {
    format!(
        "registry_path:   {}\ndelivery_path:   {}\ninbox_path:      {}\ntotal_count:     {}\nenabled_count:   {}\ningress_count:   {}\nactive_delivery_count:   {}\narchived_delivery_count: {}\nchannels:        {}\n",
        summary.registry_path.display(),
        summary.delivery_path.display(),
        summary.inbox_path.display(),
        summary.total_count,
        summary.enabled_count,
        summary.ingress_count,
        summary.active_delivery_count,
        summary.archived_delivery_count,
        if summary.channel_ids.is_empty() {
            "(none)".to_string()
        } else {
            summary.channel_ids.join(",")
        }
    )
}

pub fn render_channel_overview_json(summary: &ChannelRuntimeOverview) -> String {
    serde_json::to_string_pretty(&json!({
        "registry_path": summary.registry_path.display().to_string(),
        "delivery_path": summary.delivery_path.display().to_string(),
        "inbox_path": summary.inbox_path.display().to_string(),
        "total_count": summary.total_count,
        "enabled_count": summary.enabled_count,
        "ingress_count": summary.ingress_count,
        "active_delivery_count": summary.active_delivery_count,
        "archived_delivery_count": summary.archived_delivery_count,
        "channel_ids": summary.channel_ids,
    }))
    .unwrap_or_else(|_| "{}".to_string())
        + "\n"
}

pub fn render_channel_sync_human(result: &ChannelSyncResult) -> String {
    format!(
        "registry_path:   {}\ntotal_count:     {}\nenabled_count:   {}\nchannels:        {}\n",
        result.registry_path.display(),
        result.total_count,
        result.enabled_count,
        if result.channel_ids.is_empty() {
            "(none)".to_string()
        } else {
            result.channel_ids.join(",")
        }
    )
}

pub fn render_channel_sync_json(result: &ChannelSyncResult) -> String {
    serde_json::to_string_pretty(&json!({
        "registry_path": result.registry_path.display().to_string(),
        "total_count": result.total_count,
        "enabled_count": result.enabled_count,
        "channel_ids": result.channel_ids,
    }))
    .unwrap_or_else(|_| "{}".to_string())
        + "\n"
}

pub fn render_channel_list_human(records: &[ChannelRecord]) -> String {
    if records.is_empty() {
        return "channel_count:     0\n".to_string();
    }
    let mut rendered = format!("channel_count:     {}\n", records.len());
    for record in records {
        rendered.push_str(&format!(
            "\n- {} kind={} enabled={} auth={} endpoint={} note={}\n",
            record.channel_id,
            record.kind,
            record.enabled,
            if record.auth_mode.trim().is_empty() {
                "none"
            } else {
                &record.auth_mode
            },
            if record.endpoint.trim().is_empty() {
                "(none)"
            } else {
                &record.endpoint
            },
            if record.note.trim().is_empty() {
                "(none)"
            } else {
                &record.note
            },
        ));
    }
    rendered
}

pub fn render_channel_list_json(records: &[ChannelRecord]) -> String {
    serde_json::to_string_pretty(&records.iter().map(channel_record_json).collect::<Vec<_>>())
        .unwrap_or_else(|_| "[]".to_string())
        + "\n"
}

pub fn render_channel_health_human(records: &[ChannelHealthRecord]) -> String {
    if records.is_empty() {
        return "channel_health_count: 0\n".to_string();
    }
    let mut rendered = format!("channel_health_count: {}\n", records.len());
    for record in records {
        rendered.push_str(&format!(
            "\n- {} kind={} health={} ready={} latest={} queued={} delivered={} failed={} blocked={} archived={} detail={}\n",
            record.channel_id,
            record.kind,
            record.health,
            record.ready,
            record.latest_delivery_status,
            record.queued_count,
            record.delivered_count,
            record.failed_count,
            record.blocked_count,
            record.archived_delivery_count,
            record.status_detail.replace('\n', "\\n"),
        ));
    }
    rendered
}

pub fn render_channel_health_json(records: &[ChannelHealthRecord]) -> String {
    serde_json::to_string_pretty(
        &records
            .iter()
            .map(|record| {
                json!({
                    "channel_id": record.channel_id,
                    "kind": record.kind,
                    "enabled": record.enabled,
                    "ready": record.ready,
                    "health": record.health,
                    "status_detail": record.status_detail,
                    "endpoint": record.endpoint,
                    "latest_delivery_status": record.latest_delivery_status,
                    "latest_delivery_at_unix_ms": record.latest_delivery_at_unix_ms,
                    "queued_count": record.queued_count,
                    "delivered_count": record.delivered_count,
                    "failed_count": record.failed_count,
                    "blocked_count": record.blocked_count,
                    "archived_delivery_count": record.archived_delivery_count,
                })
            })
            .collect::<Vec<_>>(),
    )
    .unwrap_or_else(|_| "[]".to_string())
        + "\n"
}

pub fn render_channel_delivery_human(record: &ChannelDeliveryRecord) -> String {
    format!(
        "delivery_id:        {}
channel_id:         {}
recipient:          {}
submitted_at:       {}
completed_at:       {}
allowed:            {}
status:             {}
external_ref:       {}
status_detail:      {}
source_class:       {}
final_class:        {}
deny_reason:        {}
redactions:         {}
detected_tokens:    {}
output:
{}
",
        record.delivery_id,
        record.channel_id,
        record.recipient,
        record.submitted_at_unix_ms,
        if record.completed_at_unix_ms == 0 {
            "(pending)".to_string()
        } else {
            record.completed_at_unix_ms.to_string()
        },
        record.allowed,
        record.status,
        if record.external_ref.is_empty() {
            "(none)".to_string()
        } else {
            record.external_ref.clone()
        },
        if record.status_detail.is_empty() {
            "(none)".to_string()
        } else {
            record.status_detail.clone()
        },
        record.source_class,
        record.final_class,
        if record.deny_reason.is_empty() {
            "(none)"
        } else {
            &record.deny_reason
        },
        if record.redactions_applied.is_empty() {
            "(none)".to_string()
        } else {
            record.redactions_applied.join(",")
        },
        if record.detected_tokens.is_empty() {
            "(none)".to_string()
        } else {
            record.detected_tokens.join(",")
        },
        if record.display_text.is_empty() {
            "(empty)".to_string()
        } else {
            record.display_text.clone()
        }
    )
}

pub fn render_channel_delivery_json(record: &ChannelDeliveryRecord) -> String {
    serde_json::to_string_pretty(&delivery_record_json(record)).unwrap_or_else(|_| "{}".to_string())
        + "\n"
}

pub fn render_channel_delivery_list_human(records: &[ChannelDeliveryRecord]) -> String {
    if records.is_empty() {
        return "delivery_count:    0\n".to_string();
    }
    let mut rendered = format!("delivery_count:    {}\n", records.len());
    for record in records {
        rendered.push_str(&format!(
            "\n- {} channel={} recipient={} status={} class={} submitted_at={}\n",
            record.delivery_id,
            record.channel_id,
            record.recipient,
            record.status,
            record.final_class,
            record.submitted_at_unix_ms,
        ));
    }
    rendered
}

pub fn render_channel_delivery_list_json(records: &[ChannelDeliveryRecord]) -> String {
    serde_json::to_string_pretty(&records.iter().map(delivery_record_json).collect::<Vec<_>>())
        .unwrap_or_else(|_| "[]".to_string())
        + "\n"
}

pub fn render_channel_ingress_human(record: &ChannelIngressRecord) -> String {
    format!(
        "ingress_id:         {}\nchannel_id:         {}\npeer_id:            {}\nthread_id:          {}\nreceived_at:        {}\nbinding_id:         {}\nagent_id:           {}\nsession_key:        {}\nroute_kind:         {}\ntext:\n{}\n",
        record.ingress_id,
        record.channel_id,
        record.peer_id,
        record.thread_id.as_deref().unwrap_or("(none)"),
        record.received_at_unix_ms,
        record.binding_id,
        record.agent_id,
        record.session_key,
        record.route_kind,
        record.text,
    )
}

pub fn render_channel_ingress_json(record: &ChannelIngressRecord) -> String {
    serde_json::to_string_pretty(&ingress_record_json(record)).unwrap_or_else(|_| "{}".to_string())
        + "\n"
}

pub fn render_channel_ingress_list_human(records: &[ChannelIngressRecord]) -> String {
    if records.is_empty() {
        return "ingress_count:     0\n".to_string();
    }
    let mut rendered = format!("ingress_count:     {}\n", records.len());
    for record in records {
        rendered.push_str(&format!(
            "\n- {} channel={} peer={} agent={} session={} received_at={}\n",
            record.ingress_id,
            record.channel_id,
            record.peer_id,
            record.agent_id,
            record.session_key,
            record.received_at_unix_ms,
        ));
    }
    rendered
}

pub fn render_channel_ingress_list_json(records: &[ChannelIngressRecord]) -> String {
    serde_json::to_string_pretty(&records.iter().map(ingress_record_json).collect::<Vec<_>>())
        .unwrap_or_else(|_| "[]".to_string())
        + "\n"
}

fn channel_records_from_manifest(manifest: &OnboardManifest) -> Vec<ChannelRecord> {
    vec![
        ChannelRecord {
            channel_id: "web_api".to_string(),
            kind: "web_api".to_string(),
            enabled: true,
            endpoint: format!(
                "http://{}:{}",
                bind_host_for(&manifest.gateway_bind),
                manifest.gateway_port
            ),
            auth_mode: manifest.gateway_auth_mode.clone(),
            credential_ref: manifest.gateway_token_env.clone(),
            dm_policy: manifest.session_dm_scope.clone(),
            group_policy: String::new(),
            streaming: "sync".to_string(),
            note: format!(
                "gateway={} remote={}",
                manifest.gateway_bind, manifest.remote_mode
            ),
        },
        ChannelRecord {
            channel_id: "telegram".to_string(),
            kind: "telegram".to_string(),
            enabled: manifest.telegram_enabled,
            endpoint: "telegram://bot".to_string(),
            auth_mode: "env_token".to_string(),
            credential_ref: manifest.telegram_token_env.clone(),
            dm_policy: manifest.telegram_dm_policy.clone(),
            group_policy: manifest.telegram_group_policy.clone(),
            streaming: manifest.telegram_streaming.clone(),
            note: format!(
                "dm={} group={}",
                manifest.telegram_dm_policy, manifest.telegram_group_policy
            ),
        },
    ]
}

fn parse_channel_registry(raw: &str) -> LoomResult<Vec<ChannelRecord>> {
    let value: Value = serde_json::from_str(raw)
        .map_err(|error| format!("invalid channel registry json: {error}"))?;
    let channels = value
        .get("channels")
        .and_then(Value::as_array)
        .ok_or_else(|| "channel registry must define a channels array".to_string())?;
    let mut records = Vec::with_capacity(channels.len());
    for channel in channels {
        records.push(parse_channel_record(channel)?);
    }
    Ok(records)
}

fn parse_channel_record(value: &Value) -> LoomResult<ChannelRecord> {
    Ok(ChannelRecord {
        channel_id: value_string(value.get("channel_id"), "channel_id")?,
        kind: value_string(value.get("kind"), "kind")?,
        enabled: value
            .get("enabled")
            .and_then(Value::as_bool)
            .unwrap_or(true),
        endpoint: value_string_or(value.get("endpoint"), ""),
        auth_mode: value_string_or(value.get("auth_mode"), "none"),
        credential_ref: value_string_or(value.get("credential_ref"), ""),
        dm_policy: value_string_or(value.get("dm_policy"), ""),
        group_policy: value_string_or(value.get("group_policy"), ""),
        streaming: value_string_or(value.get("streaming"), ""),
        note: value_string_or(value.get("note"), ""),
    })
}

fn atomic_write_text(path: &Path, contents: &str) -> LoomResult<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(io_err)?;
        let temp_path = parent.join(format!(
            ".{}.{}.{}.tmp",
            path.file_name()
                .and_then(|name| name.to_str())
                .unwrap_or("loom-channel"),
            now_unix_ms(),
            std::process::id()
        ));
        fs::write(&temp_path, contents).map_err(io_err)?;
        fs::rename(&temp_path, path).map_err(io_err)?;
        return Ok(());
    }
    fs::write(path, contents).map_err(io_err)
}

fn persist_channel_registry(root: &Path, records: &[ChannelRecord]) -> LoomResult<()> {
    let registry_path = channel_registry_path(root);
    let value = json!({
        "channels": records.iter().map(channel_record_json).collect::<Vec<_>>(),
    });
    let mut rendered = serde_json::to_string_pretty(&value).map_err(|error| error.to_string())?;
    rendered.push('\n');
    atomic_write_text(&registry_path, &rendered)
}

fn persist_delivery_record(root: &Path, record: &ChannelDeliveryRecord) -> LoomResult<()> {
    let file_name = format!(
        "{}-{}.json",
        record.submitted_at_unix_ms,
        safe_file_token(&record.delivery_id)
    );
    let path = channel_delivery_path(root).join(file_name);
    persist_delivery_record_at_path(&path, record)
}

fn persist_delivery_record_at_path(path: &Path, record: &ChannelDeliveryRecord) -> LoomResult<()> {
    let mut rendered = serde_json::to_string_pretty(&delivery_record_json(record))
        .map_err(|error| error.to_string())?;
    rendered.push('\n');
    atomic_write_text(path, &rendered)
}

fn persist_ingress_record(root: &Path, record: &ChannelIngressRecord) -> LoomResult<()> {
    let file_name = format!(
        "{}-{}.json",
        record.received_at_unix_ms,
        safe_file_token(&record.ingress_id)
    );
    let path = channel_inbox_path(root).join(file_name);
    let mut rendered = serde_json::to_string_pretty(&ingress_record_json(record))
        .map_err(|error| error.to_string())?;
    rendered.push('\n');
    atomic_write_text(&path, &rendered)
}

fn parse_channel_health_history_record(raw: &str) -> LoomResult<ChannelHealthHistoryRecord> {
    let value: Value = serde_json::from_str(raw)
        .map_err(|error| format!("invalid channel health history json: {error}"))?;
    Ok(ChannelHealthHistoryRecord {
        captured_at_unix_ms: value_u64(value.get("captured_at_unix_ms")).unwrap_or_default(),
        trigger: value_string_or(value.get("trigger"), "unknown"),
        channel_id: value_string(value.get("channel_id"), "channel_id")?,
        health: value_string_or(value.get("health"), "unknown"),
        ready: value.get("ready").and_then(Value::as_bool).unwrap_or(false),
        status_detail: value_string_or(value.get("status_detail"), ""),
        latest_delivery_status: value_string_or(value.get("latest_delivery_status"), "none"),
        latest_delivery_at_unix_ms: value_u64(value.get("latest_delivery_at_unix_ms"))
            .unwrap_or_default(),
        queued_count: value_u64(value.get("queued_count")).unwrap_or_default() as usize,
        delivered_count: value_u64(value.get("delivered_count")).unwrap_or_default() as usize,
        failed_count: value_u64(value.get("failed_count")).unwrap_or_default() as usize,
        blocked_count: value_u64(value.get("blocked_count")).unwrap_or_default() as usize,
        archived_delivery_count: value_u64(value.get("archived_delivery_count")).unwrap_or_default()
            as usize,
    })
}

fn parse_channel_test_diagnostic_record(raw: &str) -> LoomResult<ChannelTestDiagnosticRecord> {
    let value: Value = serde_json::from_str(raw)
        .map_err(|error| format!("invalid channel diagnostic json: {error}"))?;
    Ok(ChannelTestDiagnosticRecord {
        diagnostic_id: value_string(value.get("diagnostic_id"), "diagnostic_id")?,
        delivery_id: value_string(value.get("delivery_id"), "delivery_id")?,
        channel_id: value_string(value.get("channel_id"), "channel_id")?,
        recipient: value_string(value.get("recipient"), "recipient")?,
        submitted_at_unix_ms: value_u64(value.get("submitted_at_unix_ms")).unwrap_or_default(),
        updated_at_unix_ms: value_u64(value.get("updated_at_unix_ms")).unwrap_or_default(),
        status: value_string_or(value.get("status"), "queued"),
        ready: value.get("ready").and_then(Value::as_bool).unwrap_or(false),
        health: value_string_or(value.get("health"), "unknown"),
        status_detail: value_string_or(value.get("status_detail"), ""),
        note: value_string_or(value.get("note"), ""),
    })
}

fn parse_delivery_record(raw: &str) -> LoomResult<ChannelDeliveryRecord> {
    let value: Value = serde_json::from_str(raw)
        .map_err(|error| format!("invalid channel delivery json: {error}"))?;
    Ok(ChannelDeliveryRecord {
        delivery_id: value_string(value.get("delivery_id"), "delivery_id")?,
        channel_id: value_string(value.get("channel_id"), "channel_id")?,
        recipient: value_string(value.get("recipient"), "recipient")?,
        submitted_at_unix_ms: value_u64(value.get("submitted_at_unix_ms")).unwrap_or(0),
        source_class: value_string_or(value.get("source_class"), "user_visible"),
        final_class: value_string_or(value.get("final_class"), "user_visible"),
        allowed: value
            .get("allowed")
            .and_then(Value::as_bool)
            .unwrap_or(false),
        status: value_string_or(value.get("status"), "queued"),
        completed_at_unix_ms: value_u64(value.get("completed_at_unix_ms")).unwrap_or(0),
        external_ref: value_string_or(value.get("external_ref"), ""),
        status_detail: value_string_or(value.get("status_detail"), ""),
        display_text: value_string_or(value.get("display_text"), ""),
        deny_reason: value_string_or(value.get("deny_reason"), ""),
        redactions_applied: value_array_strings(value.get("redactions_applied")),
        detected_tokens: value_array_strings(value.get("detected_tokens")),
        quarantined: value
            .get("quarantined")
            .and_then(Value::as_bool)
            .unwrap_or(false),
    })
}

fn parse_ingress_record(raw: &str) -> LoomResult<ChannelIngressRecord> {
    let value: Value = serde_json::from_str(raw)
        .map_err(|error| format!("invalid channel ingress json: {error}"))?;
    Ok(ChannelIngressRecord {
        ingress_id: value_string(value.get("ingress_id"), "ingress_id")?,
        channel_id: value_string(value.get("channel_id"), "channel_id")?,
        peer_id: value_string(value.get("peer_id"), "peer_id")?,
        thread_id: value
            .get("thread_id")
            .and_then(Value::as_str)
            .map(|raw| raw.trim().to_string())
            .filter(|raw| !raw.is_empty()),
        received_at_unix_ms: value_u64(value.get("received_at_unix_ms")).unwrap_or(0),
        binding_id: value_string(value.get("binding_id"), "binding_id")?,
        agent_id: value_string(value.get("agent_id"), "agent_id")?,
        session_key: value_string(value.get("session_key"), "session_key")?,
        route_kind: value_string_or(value.get("route_kind"), "default_manager"),
        text: value_string(value.get("text"), "text")?,
    })
}

fn channel_health_history_json(record: &ChannelHealthHistoryRecord) -> Value {
    json!({
        "captured_at_unix_ms": record.captured_at_unix_ms,
        "trigger": record.trigger,
        "channel_id": record.channel_id,
        "health": record.health,
        "ready": record.ready,
        "status_detail": record.status_detail,
        "latest_delivery_status": record.latest_delivery_status,
        "latest_delivery_at_unix_ms": record.latest_delivery_at_unix_ms,
        "queued_count": record.queued_count,
        "delivered_count": record.delivered_count,
        "failed_count": record.failed_count,
        "blocked_count": record.blocked_count,
        "archived_delivery_count": record.archived_delivery_count,
    })
}

fn channel_test_diagnostic_json(record: &ChannelTestDiagnosticRecord) -> Value {
    json!({
        "diagnostic_id": record.diagnostic_id,
        "delivery_id": record.delivery_id,
        "channel_id": record.channel_id,
        "recipient": record.recipient,
        "submitted_at_unix_ms": record.submitted_at_unix_ms,
        "updated_at_unix_ms": record.updated_at_unix_ms,
        "status": record.status,
        "ready": record.ready,
        "health": record.health,
        "status_detail": record.status_detail,
        "note": record.note,
    })
}

fn channel_record_json(record: &ChannelRecord) -> Value {
    json!({
        "channel_id": record.channel_id,
        "kind": record.kind,
        "enabled": record.enabled,
        "endpoint": record.endpoint,
        "auth_mode": record.auth_mode,
        "credential_ref": record.credential_ref,
        "dm_policy": record.dm_policy,
        "group_policy": record.group_policy,
        "streaming": record.streaming,
        "note": record.note,
    })
}

fn delivery_record_json(record: &ChannelDeliveryRecord) -> Value {
    json!({
        "delivery_id": record.delivery_id,
        "channel_id": record.channel_id,
        "recipient": record.recipient,
        "submitted_at_unix_ms": record.submitted_at_unix_ms,
        "source_class": record.source_class,
        "final_class": record.final_class,
        "allowed": record.allowed,
        "status": record.status,
        "completed_at_unix_ms": record.completed_at_unix_ms,
        "external_ref": record.external_ref,
        "status_detail": record.status_detail,
        "display_text": record.display_text,
        "deny_reason": record.deny_reason,
        "redactions_applied": record.redactions_applied,
        "detected_tokens": record.detected_tokens,
        "quarantined": record.quarantined,
    })
}

fn ingress_record_json(record: &ChannelIngressRecord) -> Value {
    json!({
        "ingress_id": record.ingress_id,
        "channel_id": record.channel_id,
        "peer_id": record.peer_id,
        "thread_id": record.thread_id,
        "received_at_unix_ms": record.received_at_unix_ms,
        "binding_id": record.binding_id,
        "agent_id": record.agent_id,
        "session_key": record.session_key,
        "route_kind": record.route_kind,
        "text": record.text,
    })
}

fn value_string(value: Option<&Value>, label: &str) -> LoomResult<String> {
    value
        .and_then(Value::as_str)
        .map(|raw| raw.trim().to_string())
        .filter(|raw| !raw.is_empty())
        .ok_or_else(|| format!("{label} must not be empty"))
}

fn value_string_or(value: Option<&Value>, fallback: &str) -> String {
    value
        .and_then(Value::as_str)
        .map(|raw| raw.trim().to_string())
        .unwrap_or_else(|| fallback.to_string())
}

fn value_array_strings(value: Option<&Value>) -> Vec<String> {
    value
        .and_then(Value::as_array)
        .map(|entries| {
            entries
                .iter()
                .filter_map(Value::as_str)
                .map(|entry| entry.to_string())
                .collect::<Vec<_>>()
        })
        .unwrap_or_default()
}

fn value_u64(value: Option<&Value>) -> Option<u64> {
    value.and_then(Value::as_u64)
}

fn safe_file_token(input: &str) -> String {
    input
        .chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() {
                ch.to_ascii_lowercase()
            } else {
                '-'
            }
        })
        .collect::<String>()
        .trim_matches('-')
        .to_string()
}

fn channel_auth_ready(record: &ChannelRecord) -> bool {
    match record.auth_mode.trim() {
        "" | "none" => true,
        "env_token" => env::var(record.credential_ref.trim())
            .ok()
            .map(|value| !value.trim().is_empty())
            .unwrap_or(false),
        "inline_header" | "static_header" | "token" => !record.credential_ref.trim().is_empty(),
        _ => !record.credential_ref.trim().is_empty(),
    }
}

fn unique_token() -> String {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos()
        .to_string()
}

fn now_unix_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

fn io_err(error: std::io::Error) -> String {
    error.to_string()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        bindings::sync_binding_registry, init_workspace, onboarding::write_onboard_manifest,
    };

    fn temp_path(label: &str) -> PathBuf {
        let unique = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos();
        let path = std::env::temp_dir().join(format!("{}-{}", label, unique));
        let _ = fs::remove_dir_all(&path);
        fs::create_dir_all(&path).expect("create temp path");
        path
    }

    #[test]
    fn scaffold_and_sync_register_channels_from_onboard_manifest() {
        let root = temp_path("loom-channel-scaffold");
        init_workspace(&root, "embedded", Some("/tmp/meridian-kernel"), "org_demo")
            .expect("init workspace");

        let mut manifest = load_onboard_manifest(&root).expect("load onboard manifest");
        manifest.telegram_enabled = true;
        write_onboard_manifest(&root, &manifest).expect("write manifest");

        let result = sync_channel_registry(&root).expect("sync channel registry");
        assert_eq!(result.total_count, 2);
        assert_eq!(result.enabled_count, 2);
        let records = load_channels(&root).expect("load channels");
        assert_eq!(records[0].channel_id, "web_api");
        assert_eq!(records[1].channel_id, "telegram");
        assert!(records[1].enabled);
    }

    #[test]
    fn enqueue_blocks_internal_tokens() {
        let root = temp_path("loom-channel-blocked");
        init_workspace(&root, "embedded", Some("/tmp/meridian-kernel"), "org_demo")
            .expect("init workspace");
        ensure_channel_runtime_scaffold(&root).expect("channel scaffold");

        let record = enqueue_channel_delivery(
            &root,
            &ChannelDeliveryRequest {
                channel_id: "web_api".to_string(),
                recipient: "founder".to_string(),
                raw_text: "SLEEP".to_string(),
                allow_receipt_hashes: false,
                allow_operator_diagnostics: false,
            },
        )
        .expect("enqueue delivery");
        assert!(!record.allowed);
        assert_eq!(record.status, "blocked");
        assert_eq!(record.final_class, "blocked");
    }

    #[test]
    fn enqueue_compacts_user_safe_output_and_lists_history() {
        let root = temp_path("loom-channel-history");
        init_workspace(&root, "embedded", Some("/tmp/meridian-kernel"), "org_demo")
            .expect("init workspace");
        ensure_channel_runtime_scaffold(&root).expect("channel scaffold");

        let record = enqueue_channel_delivery(
            &root,
            &ChannelDeliveryRequest {
                channel_id: "web_api".to_string(),
                recipient: "founder".to_string(),
                raw_text: "[✅ FINAL ANSWER]\nMeridian is live\n[🛡️ PoGE PROTOCOL] Cryptographic Audit Root Settled: 0xabc123".to_string(),
                allow_receipt_hashes: true,
                allow_operator_diagnostics: false,
            },
        )
        .expect("enqueue delivery");
        assert!(record.allowed);
        assert_eq!(record.status, "queued");
        assert!(record.display_text.contains("Meridian is live"));
        assert!(record.display_text.contains("[PoGE Receipt] 0xabc123"));

        let history = list_channel_deliveries(&root, 10).expect("list deliveries");
        assert_eq!(history.len(), 1);
        assert_eq!(history[0].delivery_id, record.delivery_id);
    }

    #[test]
    fn update_accepts_legacy_unclosed_without_completion_timestamp() {
        let root = temp_path("loom-channel-legacy-unclosed");
        init_workspace(&root, "embedded", Some("/tmp/meridian-kernel"), "org_demo")
            .expect("init workspace");
        ensure_channel_runtime_scaffold(&root).expect("channel scaffold");

        let record = enqueue_channel_delivery(
            &root,
            &ChannelDeliveryRequest {
                channel_id: "web_api".to_string(),
                recipient: "founder".to_string(),
                raw_text: "legacy response".to_string(),
                allow_receipt_hashes: false,
                allow_operator_diagnostics: false,
            },
        )
        .expect("enqueue delivery");

        let updated = update_channel_delivery(
            &root,
            &record.delivery_id,
            "legacy_unclosed",
            None,
            Some("record predates completion tracking"),
        )
        .expect("update delivery");
        assert_eq!(updated.status, "legacy_unclosed");
        assert_eq!(updated.completed_at_unix_ms, 0);
        assert_eq!(updated.status_detail, "record predates completion tracking");
    }

    #[test]
    fn list_channel_deliveries_hides_archived_legacy_records_by_default() {
        let root = temp_path("loom-channel-active-list");
        init_workspace(&root, "embedded", Some("/tmp/meridian-kernel"), "org_demo")
            .expect("init workspace");
        ensure_channel_runtime_scaffold(&root).expect("channel scaffold");

        let active = enqueue_channel_delivery(
            &root,
            &ChannelDeliveryRequest {
                channel_id: "web_api".to_string(),
                recipient: "founder".to_string(),
                raw_text: "active".to_string(),
                allow_receipt_hashes: false,
                allow_operator_diagnostics: false,
            },
        )
        .expect("enqueue active");
        let archived = enqueue_channel_delivery(
            &root,
            &ChannelDeliveryRequest {
                channel_id: "web_api".to_string(),
                recipient: "founder".to_string(),
                raw_text: "legacy".to_string(),
                allow_receipt_hashes: false,
                allow_operator_diagnostics: false,
            },
        )
        .expect("enqueue archived");

        update_channel_delivery(
            &root,
            &archived.delivery_id,
            "legacy_unclosed",
            None,
            Some("historical"),
        )
        .expect("mark archived");

        let visible = list_channel_deliveries(&root, 10).expect("list visible");
        assert_eq!(visible.len(), 1);
        assert_eq!(visible[0].delivery_id, active.delivery_id);

        let all = list_channel_deliveries_with_options(&root, 10, true, false).expect("list all");
        assert_eq!(all.len(), 2);

        let archived_only =
            list_channel_deliveries_with_options(&root, 10, true, true).expect("list archived");
        assert_eq!(archived_only.len(), 1);
        assert_eq!(archived_only[0].delivery_id, archived.delivery_id);
    }

    #[test]
    fn channel_overview_reports_active_and_archived_delivery_counts() {
        let root = temp_path("loom-channel-overview-counts");
        init_workspace(&root, "embedded", Some("/tmp/meridian-kernel"), "org_demo")
            .expect("init workspace");
        ensure_channel_runtime_scaffold(&root).expect("channel scaffold");

        let active = enqueue_channel_delivery(
            &root,
            &ChannelDeliveryRequest {
                channel_id: "web_api".to_string(),
                recipient: "founder".to_string(),
                raw_text: "active".to_string(),
                allow_receipt_hashes: false,
                allow_operator_diagnostics: false,
            },
        )
        .expect("enqueue active");
        update_channel_delivery(
            &root,
            &active.delivery_id,
            "delivered",
            Some("http_response"),
            None,
        )
        .expect("mark delivered");

        let archived = enqueue_channel_delivery(
            &root,
            &ChannelDeliveryRequest {
                channel_id: "web_api".to_string(),
                recipient: "founder".to_string(),
                raw_text: "legacy".to_string(),
                allow_receipt_hashes: false,
                allow_operator_diagnostics: false,
            },
        )
        .expect("enqueue archived");
        update_channel_delivery(
            &root,
            &archived.delivery_id,
            "legacy_unclosed",
            None,
            Some("historical"),
        )
        .expect("mark archived");

        let overview = channel_overview(&root).expect("channel overview");
        assert_eq!(overview.active_delivery_count, 1);
        assert_eq!(overview.archived_delivery_count, 1);
    }

    #[test]
    fn channel_health_flags_webhook_ready_and_failed_state() {
        let root = temp_path("loom-channel-health");
        init_workspace(&root, "embedded", Some("/tmp/meridian-kernel"), "org_demo")
            .expect("init workspace");
        ensure_channel_runtime_scaffold(&root).expect("channel scaffold");

        upsert_channel_record(
            &root,
            &ChannelRecord {
                channel_id: "webhook_demo".to_string(),
                kind: "webhook".to_string(),
                enabled: true,
                endpoint: "https://example.com/hook".to_string(),
                auth_mode: "inline_header".to_string(),
                credential_ref: "Authorization: Bearer test".to_string(),
                dm_policy: "per-agent".to_string(),
                group_policy: String::new(),
                streaming: "async".to_string(),
                note: "personal_agent=demo".to_string(),
            },
        )
        .expect("upsert webhook");

        let healthy = list_channel_health(&root).expect("channel health");
        let webhook = healthy
            .iter()
            .find(|record| record.channel_id == "webhook_demo")
            .expect("webhook health");
        assert_eq!(webhook.health, "healthy");
        assert!(webhook.ready);

        let failed = enqueue_channel_delivery(
            &root,
            &ChannelDeliveryRequest {
                channel_id: "webhook_demo".to_string(),
                recipient: "https://example.com/hook".to_string(),
                raw_text: "delivery".to_string(),
                allow_receipt_hashes: false,
                allow_operator_diagnostics: false,
            },
        )
        .expect("enqueue failed");
        update_channel_delivery(
            &root,
            &failed.delivery_id,
            "failed",
            None,
            Some("network timeout"),
        )
        .expect("mark failed");

        let warning = list_channel_health(&root).expect("channel health warning");
        let webhook = warning
            .iter()
            .find(|record| record.channel_id == "webhook_demo")
            .expect("webhook health warning");
        assert_eq!(webhook.health, "warning");
        assert_eq!(webhook.failed_count, 1);
    }

    #[test]
    fn ingest_materializes_binding_resolution_and_inbox_history() {
        let root = temp_path("loom-channel-ingress");
        init_workspace(&root, "embedded", Some("/tmp/meridian-kernel"), "org_demo")
            .expect("init workspace");
        let mut manifest = load_onboard_manifest(&root).expect("load onboard manifest");
        manifest.telegram_enabled = true;
        write_onboard_manifest(&root, &manifest).expect("write manifest");
        sync_channel_registry(&root).expect("sync channels");
        sync_binding_registry(&root).expect("sync bindings");

        let record = ingest_channel_message(
            &root,
            &ChannelIngressRequest {
                channel_id: "telegram".to_string(),
                peer_id: "founder".to_string(),
                thread_id: None,
                text: "Meridian live check".to_string(),
                agent_override: None,
            },
        )
        .expect("ingest");
        assert_eq!(record.agent_id, "leviathann");
        assert_eq!(record.session_key, "telegram:founder");

        let history = list_channel_ingress(&root, 10).expect("list ingress");
        assert_eq!(history.len(), 1);
        assert_eq!(history[0].ingress_id, record.ingress_id);
    }

    #[test]
    fn channel_health_history_records_transitions() {
        let root = temp_path("loom-channel-health-history");
        init_workspace(&root, "embedded", Some("/tmp/meridian-kernel"), "org_demo")
            .expect("init workspace");
        ensure_channel_runtime_scaffold(&root).expect("channel scaffold");

        upsert_channel_record(
            &root,
            &ChannelRecord {
                channel_id: "webhook_demo".to_string(),
                kind: "webhook".to_string(),
                enabled: true,
                endpoint: "https://example.com/hook".to_string(),
                auth_mode: "inline_header".to_string(),
                credential_ref: "Authorization: Bearer test".to_string(),
                dm_policy: "per-agent".to_string(),
                group_policy: String::new(),
                streaming: "async".to_string(),
                note: "personal_agent=demo".to_string(),
            },
        )
        .expect("upsert webhook");

        let delivery = enqueue_channel_delivery(
            &root,
            &ChannelDeliveryRequest {
                channel_id: "webhook_demo".to_string(),
                recipient: "https://example.com/hook".to_string(),
                raw_text: "delivery".to_string(),
                allow_receipt_hashes: false,
                allow_operator_diagnostics: false,
            },
        )
        .expect("enqueue delivery");
        update_channel_delivery(
            &root,
            &delivery.delivery_id,
            "failed",
            None,
            Some("network timeout"),
        )
        .expect("mark failed");

        let history = list_channel_health_history(&root, "webhook_demo", 10).expect("history");
        assert!(history.len() >= 2);
        assert_eq!(history[0].health, "warning");
        assert_eq!(history[0].latest_delivery_status, "failed");
        assert!(history
            .iter()
            .any(|entry| entry.trigger == "delivery_updated"));
    }

    #[test]
    fn channel_test_diagnostics_track_delivery_updates() {
        let root = temp_path("loom-channel-diagnostics");
        init_workspace(&root, "embedded", Some("/tmp/meridian-kernel"), "org_demo")
            .expect("init workspace");
        ensure_channel_runtime_scaffold(&root).expect("channel scaffold");

        upsert_channel_record(
            &root,
            &ChannelRecord {
                channel_id: "webhook_demo".to_string(),
                kind: "webhook".to_string(),
                enabled: true,
                endpoint: "https://example.com/hook".to_string(),
                auth_mode: "inline_header".to_string(),
                credential_ref: "Authorization: Bearer test".to_string(),
                dm_policy: "per-agent".to_string(),
                group_policy: String::new(),
                streaming: "async".to_string(),
                note: "personal_agent=demo".to_string(),
            },
        )
        .expect("upsert webhook");

        let delivery = enqueue_channel_delivery(
            &root,
            &ChannelDeliveryRequest {
                channel_id: "webhook_demo".to_string(),
                recipient: "https://example.com/hook".to_string(),
                raw_text: "probe".to_string(),
                allow_receipt_hashes: false,
                allow_operator_diagnostics: false,
            },
        )
        .expect("enqueue delivery");
        let diagnostic = record_channel_test_diagnostic(&root, &delivery, "queued from unit test")
            .expect("record diagnostic");
        assert_eq!(diagnostic.status, "queued");

        let updated = update_channel_delivery(
            &root,
            &delivery.delivery_id,
            "failed",
            None,
            Some("simulated downstream failure"),
        )
        .expect("update delivery");
        let diagnostics =
            list_channel_test_diagnostics(&root, "webhook_demo", 10).expect("diagnostics");
        assert_eq!(diagnostics.len(), 1);
        assert_eq!(diagnostics[0].delivery_id, updated.delivery_id);
        assert_eq!(diagnostics[0].status, "failed");
        assert!(diagnostics[0].updated_at_unix_ms >= diagnostics[0].submitted_at_unix_ms);
    }
}
