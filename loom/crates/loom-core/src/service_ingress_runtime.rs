use std::fs;
use std::path::{Path, PathBuf};

use serde_json::{json, Value};

use crate::{read_config, LoomResult};

pub const DEFAULT_SERVICE_INGRESS_REGISTRY_PATH: &str = "state/service-ingress/registry.json";
const SERVICE_INGRESS_VERSION: u32 = 1;

#[derive(Clone, Debug, PartialEq)]
pub struct ServiceIngressRecord {
    pub request_id: String,
    pub request_type: String,
    pub status: String,
    pub transport: String,
    pub ingress_target: String,
    pub agent_id: String,
    pub org_id: String,
    pub action_type: String,
    pub resource: String,
    pub capability_name: String,
    pub payload_json: String,
    pub estimated_cost_usd: f64,
    pub received_at: String,
    pub accepted_at: String,
    pub job_id: String,
    pub policy_class: String,
    pub queue_path: String,
    pub request_path: PathBuf,
    pub receipt_path: Option<PathBuf>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ServiceIngressOverview {
    pub registry_path: PathBuf,
    pub request_dir: PathBuf,
    pub receipt_dir: PathBuf,
    pub stream_path: PathBuf,
    pub total_requests: usize,
    pub accepted_count: usize,
    pub pending_count: usize,
    pub last_request_id: String,
    pub last_job_id: String,
}

pub fn service_ingress_registry_path(root: &Path) -> PathBuf {
    root.join(DEFAULT_SERVICE_INGRESS_REGISTRY_PATH)
}

pub fn ensure_service_ingress_runtime_scaffold(root: &Path) -> LoomResult<PathBuf> {
    let config = read_config(root)?;
    let run_dir = root.join(&config.run_dir).join("ingress");
    fs::create_dir_all(run_dir.join("requests")).map_err(io_err)?;
    fs::create_dir_all(run_dir.join("receipts")).map_err(io_err)?;
    let path = service_ingress_registry_path(root);
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(io_err)?;
    }
    if !path.exists() {
        sync_service_ingress_runtime(root)?;
    }
    Ok(path)
}

pub fn sync_service_ingress_runtime(root: &Path) -> LoomResult<ServiceIngressOverview> {
    let config = read_config(root)?;
    let ingress_root = root.join(&config.run_dir).join("ingress");
    let request_dir = ingress_root.join("requests");
    let receipt_dir = ingress_root.join("receipts");
    let stream_path = ingress_root.join("stream.jsonl");
    fs::create_dir_all(&request_dir).map_err(io_err)?;
    fs::create_dir_all(&receipt_dir).map_err(io_err)?;

    let records = collect_service_ingress_records(root)?;
    let accepted_count = records
        .iter()
        .filter(|record| !record.accepted_at.is_empty())
        .count();
    let pending_count = records.len().saturating_sub(accepted_count);
    let last_request_id = records
        .first()
        .map(|record| record.request_id.clone())
        .unwrap_or_default();
    let last_job_id = records
        .iter()
        .find(|record| !record.job_id.is_empty())
        .map(|record| record.job_id.clone())
        .unwrap_or_default();
    let summary = json!({
        "version": SERVICE_INGRESS_VERSION,
        "runtime": {
            "request_dir": request_dir.display().to_string(),
            "receipt_dir": receipt_dir.display().to_string(),
            "stream_path": stream_path.display().to_string(),
            "total_requests": records.len(),
            "accepted_count": accepted_count,
            "pending_count": pending_count,
            "last_request_id": last_request_id,
            "last_job_id": last_job_id,
        }
    });
    let mut rendered = serde_json::to_string_pretty(&summary).map_err(|error| error.to_string())?;
    rendered.push('\n');
    fs::write(service_ingress_registry_path(root), rendered).map_err(io_err)?;
    service_ingress_overview(root)
}

pub fn service_ingress_overview(root: &Path) -> LoomResult<ServiceIngressOverview> {
    ensure_service_ingress_runtime_scaffold(root)?;
    let config = read_config(root)?;
    let ingress_root = root.join(&config.run_dir).join("ingress");
    let raw = fs::read_to_string(service_ingress_registry_path(root)).map_err(io_err)?;
    let value: Value = serde_json::from_str(&raw)
        .map_err(|error| format!("invalid service ingress registry json: {error}"))?;
    let runtime = value
        .get("runtime")
        .and_then(Value::as_object)
        .ok_or_else(|| "service ingress registry missing runtime object".to_string())?;
    Ok(ServiceIngressOverview {
        registry_path: service_ingress_registry_path(root),
        request_dir: PathBuf::from(value_string_object(
            runtime,
            "request_dir",
            &ingress_root.join("requests").display().to_string(),
        )),
        receipt_dir: PathBuf::from(value_string_object(
            runtime,
            "receipt_dir",
            &ingress_root.join("receipts").display().to_string(),
        )),
        stream_path: PathBuf::from(value_string_object(
            runtime,
            "stream_path",
            &ingress_root.join("stream.jsonl").display().to_string(),
        )),
        total_requests: value_usize_object(runtime, "total_requests"),
        accepted_count: value_usize_object(runtime, "accepted_count"),
        pending_count: value_usize_object(runtime, "pending_count"),
        last_request_id: value_string_object(runtime, "last_request_id", ""),
        last_job_id: value_string_object(runtime, "last_job_id", ""),
    })
}

pub fn list_service_ingress(root: &Path, limit: usize) -> LoomResult<Vec<ServiceIngressRecord>> {
    let mut records = collect_service_ingress_records(root)?;
    if limit > 0 && records.len() > limit {
        records.truncate(limit);
    }
    Ok(records)
}

pub fn show_service_ingress(root: &Path, request_id: &str) -> LoomResult<ServiceIngressRecord> {
    let request_id = request_id.trim();
    if request_id.is_empty() {
        return Err("request_id is required".to_string());
    }
    let records = collect_service_ingress_records(root)?;
    records
        .into_iter()
        .find(|record| record.request_id == request_id)
        .ok_or_else(|| format!("service ingress request '{}' was not found", request_id))
}

pub fn render_service_ingress_overview_human(summary: &ServiceIngressOverview) -> String {
    format!(
        "registry_path:    {}\nrequest_dir:       {}\nreceipt_dir:       {}\nstream_path:       {}\ntotal_requests:    {}\naccepted_count:    {}\npending_count:     {}\nlast_request_id:   {}\nlast_job_id:       {}\n",
        summary.registry_path.display(),
        summary.request_dir.display(),
        summary.receipt_dir.display(),
        summary.stream_path.display(),
        summary.total_requests,
        summary.accepted_count,
        summary.pending_count,
        if summary.last_request_id.is_empty() { "(none)" } else { summary.last_request_id.as_str() },
        if summary.last_job_id.is_empty() { "(none)" } else { summary.last_job_id.as_str() },
    )
}

pub fn render_service_ingress_overview_json(summary: &ServiceIngressOverview) -> String {
    serde_json::to_string_pretty(&json!({
        "registry_path": summary.registry_path.display().to_string(),
        "request_dir": summary.request_dir.display().to_string(),
        "receipt_dir": summary.receipt_dir.display().to_string(),
        "stream_path": summary.stream_path.display().to_string(),
        "total_requests": summary.total_requests,
        "accepted_count": summary.accepted_count,
        "pending_count": summary.pending_count,
        "last_request_id": summary.last_request_id,
        "last_job_id": summary.last_job_id,
    }))
    .unwrap_or_else(|_| "{}".to_string())
        + "\n"
}

pub fn render_service_ingress_human(record: &ServiceIngressRecord) -> String {
    format!(
        "request_id:         {}\nrequest_type:       {}\nstatus:             {}\ntransport:          {}\ningress_target:     {}\nagent_id:           {}\norg_id:             {}\naction_type:        {}\nresource:           {}\ncapability_name:    {}\nestimated_cost_usd: {:.6}\nreceived_at:        {}\naccepted_at:        {}\njob_id:             {}\npolicy_class:       {}\nqueue_path:         {}\nrequest_path:       {}\nreceipt_path:       {}\n",
        record.request_id,
        if record.request_type.is_empty() { "(none)" } else { record.request_type.as_str() },
        record.status,
        if record.transport.is_empty() { "(none)" } else { record.transport.as_str() },
        if record.ingress_target.is_empty() { "(none)" } else { record.ingress_target.as_str() },
        if record.agent_id.is_empty() { "(none)" } else { record.agent_id.as_str() },
        if record.org_id.is_empty() { "(none)" } else { record.org_id.as_str() },
        if record.action_type.is_empty() { "(none)" } else { record.action_type.as_str() },
        if record.resource.is_empty() { "(none)" } else { record.resource.as_str() },
        if record.capability_name.is_empty() { "(none)" } else { record.capability_name.as_str() },
        record.estimated_cost_usd,
        if record.received_at.is_empty() { "(none)" } else { record.received_at.as_str() },
        if record.accepted_at.is_empty() { "(none)" } else { record.accepted_at.as_str() },
        if record.job_id.is_empty() { "(none)" } else { record.job_id.as_str() },
        if record.policy_class.is_empty() { "(none)" } else { record.policy_class.as_str() },
        if record.queue_path.is_empty() { "(none)" } else { record.queue_path.as_str() },
        record.request_path.display(),
        record.receipt_path.as_ref().map(|path| path.display().to_string()).unwrap_or_else(|| "(none)".to_string()),
    )
}

pub fn render_service_ingress_json(record: &ServiceIngressRecord) -> String {
    serde_json::to_string_pretty(&service_ingress_record_json(record))
        .unwrap_or_else(|_| "{}".to_string())
        + "\n"
}

pub fn render_service_ingress_list_human(records: &[ServiceIngressRecord]) -> String {
    if records.is_empty() {
        return "request_count:       0\n".to_string();
    }
    let mut rendered = format!("request_count:       {}\n", records.len());
    for record in records {
        rendered.push_str(&format!(
            "\n- {} status={} transport={} job_id={} agent={} resource={} received_at={}\n",
            record.request_id,
            record.status,
            if record.transport.is_empty() {
                "(none)"
            } else {
                record.transport.as_str()
            },
            if record.job_id.is_empty() {
                "(none)"
            } else {
                record.job_id.as_str()
            },
            if record.agent_id.is_empty() {
                "(none)"
            } else {
                record.agent_id.as_str()
            },
            if record.resource.is_empty() {
                "(none)"
            } else {
                record.resource.as_str()
            },
            if record.received_at.is_empty() {
                "(none)"
            } else {
                record.received_at.as_str()
            },
        ));
    }
    rendered
}

pub fn render_service_ingress_list_json(records: &[ServiceIngressRecord]) -> String {
    serde_json::to_string_pretty(
        &records
            .iter()
            .map(service_ingress_record_json)
            .collect::<Vec<_>>(),
    )
    .unwrap_or_else(|_| "[]".to_string())
        + "\n"
}

fn collect_service_ingress_records(root: &Path) -> LoomResult<Vec<ServiceIngressRecord>> {
    let config = read_config(root)?;
    let request_dir = root.join(&config.run_dir).join("ingress").join("requests");
    let receipt_dir = root.join(&config.run_dir).join("ingress").join("receipts");
    fs::create_dir_all(&request_dir).map_err(io_err)?;
    fs::create_dir_all(&receipt_dir).map_err(io_err)?;

    let mut existing_receipts = std::collections::HashSet::new();
    if let Ok(entries) = fs::read_dir(&receipt_dir) {
        for entry in entries.flatten() {
            existing_receipts.insert(entry.file_name());
        }
    }

    let mut records = Vec::new();
    for entry in fs::read_dir(&request_dir).map_err(io_err)? {
        let path = entry.map_err(io_err)?.path();
        if path.extension().and_then(|ext| ext.to_str()) != Some("json") {
            continue;
        }
        let raw = fs::read_to_string(&path).map_err(io_err)?;
        let request = serde_json::from_str::<Value>(&raw)
            .map_err(|error| format!("invalid service ingress request json: {error}"))?;
        let request_id = value_string_value(&request, "request_id", "");
        let receipt_path = path
            .file_name()
            .filter(|name| existing_receipts.contains(*name))
            .map(|name| receipt_dir.join(name));
        let receipt = if let Some(receipt_path) = &receipt_path {
            let raw = fs::read_to_string(receipt_path).map_err(io_err)?;
            Some(
                serde_json::from_str::<Value>(&raw)
                    .map_err(|error| format!("invalid service ingress receipt json: {error}"))?,
            )
        } else {
            None
        };
        let status = if receipt.is_some() {
            value_string(
                receipt.as_ref(),
                "status",
                value_string_value(&request, "status", "received").as_str(),
            )
        } else {
            value_string_value(&request, "status", "received")
        };
        records.push(ServiceIngressRecord {
            request_id,
            request_type: value_string_value(&request, "request_type", ""),
            status,
            transport: if receipt.is_some() {
                value_string(
                    receipt.as_ref(),
                    "transport",
                    value_string_value(&request, "transport", "").as_str(),
                )
            } else {
                value_string_value(&request, "transport", "")
            },
            ingress_target: value_string_value(
                &request,
                "ingress_target",
                value_string(receipt.as_ref(), "service_target", "").as_str(),
            ),
            agent_id: value_string_value(&request, "agent_id", ""),
            org_id: value_string_value(&request, "org_id", ""),
            action_type: value_string_value(&request, "action_type", ""),
            resource: value_string_value(&request, "resource", ""),
            capability_name: value_string_value(&request, "capability_name", ""),
            payload_json: value_string_value(&request, "payload_json", ""),
            estimated_cost_usd: request
                .get("estimated_cost_usd")
                .and_then(Value::as_f64)
                .unwrap_or(0.0),
            received_at: value_string_value(&request, "received_at", ""),
            accepted_at: value_string(receipt.as_ref(), "accepted_at", ""),
            job_id: value_string(receipt.as_ref(), "job_id", ""),
            policy_class: value_string(receipt.as_ref(), "policy_class", ""),
            queue_path: value_string(receipt.as_ref(), "queue_path", ""),
            request_path: path.clone(),
            receipt_path,
        });
    }
    records.sort_by(|left, right| {
        right
            .received_at
            .cmp(&left.received_at)
            .then_with(|| right.request_id.cmp(&left.request_id))
    });
    Ok(records)
}

fn service_ingress_record_json(record: &ServiceIngressRecord) -> Value {
    json!({
        "request_id": record.request_id,
        "request_type": record.request_type,
        "status": record.status,
        "transport": record.transport,
        "ingress_target": record.ingress_target,
        "agent_id": record.agent_id,
        "org_id": record.org_id,
        "action_type": record.action_type,
        "resource": record.resource,
        "capability_name": record.capability_name,
        "payload_json": record.payload_json,
        "estimated_cost_usd": record.estimated_cost_usd,
        "received_at": record.received_at,
        "accepted_at": record.accepted_at,
        "job_id": record.job_id,
        "policy_class": record.policy_class,
        "queue_path": record.queue_path,
        "request_path": record.request_path.display().to_string(),
        "receipt_path": record.receipt_path.as_ref().map(|path| path.display().to_string()),
    })
}

fn value_string(value: Option<&Value>, key: &str, default: &str) -> String {
    value
        .and_then(|object| object.get(key))
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .unwrap_or(default)
        .to_string()
}

fn value_string_value(object: &Value, key: &str, default: &str) -> String {
    object
        .get(key)
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .unwrap_or(default)
        .to_string()
}

fn value_string_object(
    object: &serde_json::Map<String, Value>,
    key: &str,
    default: &str,
) -> String {
    object
        .get(key)
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .unwrap_or(default)
        .to_string()
}

fn value_usize_object(object: &serde_json::Map<String, Value>, key: &str) -> usize {
    object.get(key).and_then(Value::as_u64).unwrap_or(0) as usize
}

fn io_err(error: std::io::Error) -> String {
    error.to_string()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::init_workspace;
    use std::time::{SystemTime, UNIX_EPOCH};

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
    fn sync_service_ingress_runtime_materializes_empty_registry() {
        let root = temp_path("loom-service-ingress");
        init_workspace(&root, "embedded", Some("/tmp/meridian-kernel"), "org_demo")
            .expect("init workspace");
        let summary = sync_service_ingress_runtime(&root).expect("sync service ingress");
        assert_eq!(summary.total_requests, 0);
        assert!(service_ingress_registry_path(&root).exists());
    }

    #[test]
    fn sync_service_ingress_runtime_reads_request_and_receipt_lineage() {
        let root = temp_path("loom-service-ingress-lineage");
        init_workspace(&root, "embedded", Some("/tmp/meridian-kernel"), "org_demo")
            .expect("init workspace");
        let request_dir = root.join("run/ingress/requests");
        let receipt_dir = root.join("run/ingress/receipts");
        fs::create_dir_all(&request_dir).expect("request dir");
        fs::create_dir_all(&receipt_dir).expect("receipt dir");
        fs::write(
            request_dir.join("req_demo.json"),
            serde_json::to_string_pretty(&json!({
                "status": "received",
                "request_id": "req_demo",
                "request_type": "action_submit",
                "received_at": "2026-03-28T00:00:00Z",
                "transport": "file_ingress",
                "ingress_target": "runtime.sock",
                "agent_id": "atlas",
                "org_id": "org_demo",
                "action_type": "research",
                "resource": "web_search",
                "capability_name": "loom.browser.navigate.v1",
                "payload_json": "{}",
                "estimated_cost_usd": 0.05
            }))
            .expect("render request"),
        )
        .expect("write request");
        fs::write(
            receipt_dir.join("req_demo.json"),
            serde_json::to_string_pretty(&json!({
                "status": "accepted",
                "request_id": "req_demo",
                "accepted_at": "2026-03-28T00:00:01Z",
                "transport": "file_ingress",
                "service_target": "runtime.sock",
                "job_id": "job_demo",
                "policy_class": "standard",
                "queue_path": "/tmp/queue/job_demo.json"
            }))
            .expect("render receipt"),
        )
        .expect("write receipt");

        let summary = sync_service_ingress_runtime(&root).expect("sync service ingress");
        assert_eq!(summary.total_requests, 1);
        assert_eq!(summary.accepted_count, 1);
        let record = show_service_ingress(&root, "req_demo").expect("show ingress");
        assert_eq!(record.job_id, "job_demo");
        assert_eq!(record.policy_class, "standard");
    }
}
