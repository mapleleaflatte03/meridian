use std::collections::BTreeMap;
use std::fs;
use std::path::Path;

/// Result type for scheduler operations.
pub type SchedulerResult<T> = Result<T, String>;

/// Status of a scheduled job.
#[derive(Clone, Debug, PartialEq)]
pub enum JobStatus {
    Queued,
    Reserved,
    Running,
    Suspended,
    Completed,
    Failed,
    Cancelled,
}

impl JobStatus {
    pub fn as_str(&self) -> &'static str {
        match self {
            JobStatus::Queued => "queued",
            JobStatus::Reserved => "reserved",
            JobStatus::Running => "running",
            JobStatus::Suspended => "suspended",
            JobStatus::Completed => "completed",
            JobStatus::Failed => "failed",
            JobStatus::Cancelled => "cancelled",
        }
    }

    pub fn from_str(s: &str) -> SchedulerResult<Self> {
        match s {
            "queued" => Ok(JobStatus::Queued),
            "reserved" => Ok(JobStatus::Reserved),
            "running" => Ok(JobStatus::Running),
            "suspended" => Ok(JobStatus::Suspended),
            "completed" => Ok(JobStatus::Completed),
            "failed" => Ok(JobStatus::Failed),
            "cancelled" => Ok(JobStatus::Cancelled),
            other => Err(format!("unknown job status: {}", other)),
        }
    }

    /// Returns the set of statuses this status is allowed to transition to.
    pub fn valid_transitions(&self) -> &'static [JobStatus] {
        match self {
            JobStatus::Queued => &[JobStatus::Reserved, JobStatus::Cancelled],
            JobStatus::Reserved => &[
                JobStatus::Running,
                JobStatus::Queued,
                JobStatus::Cancelled,
                JobStatus::Failed,
            ],
            JobStatus::Running => &[
                JobStatus::Completed,
                JobStatus::Failed,
                JobStatus::Cancelled,
                JobStatus::Suspended,
            ],
            JobStatus::Suspended => &[JobStatus::Queued, JobStatus::Failed, JobStatus::Cancelled],
            JobStatus::Completed => &[],
            JobStatus::Failed => &[JobStatus::Queued],
            JobStatus::Cancelled => &[],
        }
    }
}

/// A single job tracked by the scheduler.
#[derive(Clone, Debug)]
pub struct SchedulerJob {
    pub agent_id: String,
    pub org_id: String,
    pub action_type: String,
    pub resource: String,
    pub policy_class: String,
    pub queue_bucket: String,
    pub status: JobStatus,
    pub enqueued_at: u64,
    pub started_at: Option<u64>,
    pub completed_at: Option<u64>,
    pub attempt_count: u32,
    pub lease_owner: Option<String>,
    pub result_summary: Option<String>,
}

impl SchedulerJob {
    fn to_json(&self, id: &str) -> String {
        format!(
            concat!(
                "{{\"id\":{},\"agent_id\":{},\"org_id\":{},\"action_type\":{},",
                "\"resource\":{},\"policy_class\":{},\"queue_bucket\":{},\"status\":{},\"enqueued_at\":{},",
                "\"started_at\":{},\"completed_at\":{},\"attempt_count\":{},\"lease_owner\":{},\"result_summary\":{}}}"
            ),
            json_string(id),
            json_string(&self.agent_id),
            json_string(&self.org_id),
            json_string(&self.action_type),
            json_string(&self.resource),
            json_string(&self.policy_class),
            json_string(&self.queue_bucket),
            json_string(self.status.as_str()),
            self.enqueued_at,
            option_u64_json(&self.started_at),
            option_u64_json(&self.completed_at),
            self.attempt_count,
            option_string_json(&self.lease_owner),
            option_string_json(&self.result_summary),
        )
    }

    fn from_json(raw: &str) -> SchedulerResult<(String, Self)> {
        let id = extract_json_string(raw, "\"id\"").ok_or_else(|| "id missing".to_string())?;
        let agent_id = extract_json_string(raw, "\"agent_id\"")
            .ok_or_else(|| "agent_id missing".to_string())?;
        let org_id =
            extract_json_string(raw, "\"org_id\"").ok_or_else(|| "org_id missing".to_string())?;
        let action_type = extract_json_string(raw, "\"action_type\"")
            .ok_or_else(|| "action_type missing".to_string())?;
        let resource = extract_json_string(raw, "\"resource\"")
            .ok_or_else(|| "resource missing".to_string())?;
        let policy_class =
            extract_json_string(raw, "\"policy_class\"").unwrap_or_else(|| "standard".to_string());
        let queue_bucket =
            extract_json_string(raw, "\"queue_bucket\"").unwrap_or_else(|| "pending".to_string());
        let status_str =
            extract_json_string(raw, "\"status\"").ok_or_else(|| "status missing".to_string())?;
        let status = JobStatus::from_str(&status_str)?;
        let enqueued_at = extract_json_u64(raw, "\"enqueued_at\"")
            .ok_or_else(|| "enqueued_at missing".to_string())?;
        let started_at = extract_json_optional_u64(raw, "\"started_at\"");
        let completed_at = extract_json_optional_u64(raw, "\"completed_at\"");
        let attempt_count = extract_json_u32(raw, "\"attempt_count\"").unwrap_or(0);
        let lease_owner = extract_json_optional_string(raw, "\"lease_owner\"");
        let result_summary = extract_json_optional_string(raw, "\"result_summary\"");
        Ok((
            id,
            SchedulerJob {
                agent_id,
                org_id,
                action_type,
                resource,
                policy_class,
                queue_bucket,
                status,
                enqueued_at,
                started_at,
                completed_at,
                attempt_count,
                lease_owner,
                result_summary,
            },
        ))
    }
}

/// Persistent scheduler state holding all jobs.
#[derive(Clone, Debug)]
pub struct SchedulerState {
    pub jobs: BTreeMap<String, SchedulerJob>,
    pub next_job_id: u64,
    pub created_at: u64,
    pub last_modified_at: u64,
}

impl SchedulerState {
    pub fn new() -> Self {
        let now = epoch_now();
        SchedulerState {
            jobs: BTreeMap::new(),
            next_job_id: 1,
            created_at: now,
            last_modified_at: now,
        }
    }

    fn to_json(&self) -> String {
        let job_entries: Vec<String> = self.jobs.iter().map(|(id, j)| j.to_json(id)).collect();
        format!(
            "{{\"next_job_id\":{},\"created_at\":{},\"last_modified_at\":{},\"jobs\":[{}]}}",
            self.next_job_id,
            self.created_at,
            self.last_modified_at,
            job_entries.join(","),
        )
    }

    fn from_json(raw: &str) -> SchedulerResult<Self> {
        let next_job_id = extract_json_u64(raw, "\"next_job_id\"")
            .ok_or_else(|| "next_job_id missing".to_string())?;
        let created_at = extract_json_u64(raw, "\"created_at\"")
            .ok_or_else(|| "created_at missing".to_string())?;
        let last_modified_at = extract_json_u64(raw, "\"last_modified_at\"")
            .ok_or_else(|| "last_modified_at missing".to_string())?;

        let mut jobs = BTreeMap::new();
        let arr_start = raw
            .find("\"jobs\"")
            .and_then(|i| raw[i..].find('[').map(|j| i + j));
        if let Some(start) = arr_start {
            let arr_end = find_matching_bracket(raw, start);
            let arr_body = &raw[start + 1..arr_end];
            for obj_str in split_json_objects(arr_body) {
                let (id, job) = SchedulerJob::from_json(&obj_str)?;
                jobs.insert(id, job);
            }
        }

        Ok(SchedulerState {
            jobs,
            next_job_id,
            created_at,
            last_modified_at,
        })
    }
}

/// Append a new job to the scheduler state. Returns the assigned job_id.
#[allow(dead_code)]
pub fn append_job(
    state: &mut SchedulerState,
    agent_id: &str,
    org_id: &str,
    action_type: &str,
    resource: &str,
) -> String {
    let job_id = format!("job_{}", state.next_job_id);
    state.next_job_id += 1;
    append_job_with_id(
        state,
        &job_id,
        agent_id,
        org_id,
        action_type,
        resource,
        "standard",
        "pending",
    );
    job_id
}

pub fn append_job_with_id(
    state: &mut SchedulerState,
    job_id: &str,
    agent_id: &str,
    org_id: &str,
    action_type: &str,
    resource: &str,
    policy_class: &str,
    queue_bucket: &str,
) {
    let now = epoch_now();
    let job = SchedulerJob {
        agent_id: agent_id.to_string(),
        org_id: org_id.to_string(),
        action_type: action_type.to_string(),
        resource: resource.to_string(),
        policy_class: policy_class.to_string(),
        queue_bucket: queue_bucket.to_string(),
        status: JobStatus::Queued,
        enqueued_at: now,
        started_at: None,
        completed_at: None,
        attempt_count: 0,
        lease_owner: None,
        result_summary: None,
    };
    state.jobs.insert(job_id.to_string(), job);
    state.last_modified_at = now;
}

/// Transition a job to a new status. Validates the transition is legal.
pub fn transition_job(
    state: &mut SchedulerState,
    job_id: &str,
    new_status: JobStatus,
) -> SchedulerResult<()> {
    let job = state
        .jobs
        .get_mut(job_id)
        .ok_or_else(|| format!("job {} not found", job_id))?;

    let allowed = job.status.valid_transitions();
    if !allowed.contains(&new_status) {
        return Err(format!(
            "invalid transition: {} -> {} for job {}",
            job.status.as_str(),
            new_status.as_str(),
            job_id,
        ));
    }

    let now = epoch_now();

    // Set started_at on transition to Running
    if new_status == JobStatus::Running && job.started_at.is_none() {
        job.started_at = Some(now);
    }

    if new_status == JobStatus::Reserved {
        job.attempt_count = job.attempt_count.saturating_add(1);
    }

    // Set completed_at on terminal transitions
    if new_status == JobStatus::Completed
        || new_status == JobStatus::Failed
        || new_status == JobStatus::Cancelled
    {
        job.completed_at = Some(now);
    }

    job.status = new_status;
    state.last_modified_at = now;
    Ok(())
}

pub fn update_job_metadata(
    state: &mut SchedulerState,
    job_id: &str,
    queue_bucket: Option<&str>,
    lease_owner: Option<Option<&str>>,
    result_summary: Option<Option<&str>>,
) -> SchedulerResult<()> {
    let job = state
        .jobs
        .get_mut(job_id)
        .ok_or_else(|| format!("job {} not found", job_id))?;
    if let Some(bucket) = queue_bucket {
        job.queue_bucket = bucket.to_string();
    }
    if let Some(owner) = lease_owner {
        job.lease_owner = owner.map(|value| value.to_string());
    }
    if let Some(summary) = result_summary {
        job.result_summary = summary.map(|value| value.to_string());
    }
    state.last_modified_at = epoch_now();
    Ok(())
}

/// Save state to a JSON file.
pub fn save_state(state: &SchedulerState, path: &Path) -> SchedulerResult<()> {
    let json = state.to_json();
    fs::write(path, json).map_err(|e| e.to_string())
}

/// Load state from a JSON file.
pub fn load_state(path: &Path) -> SchedulerResult<SchedulerState> {
    let contents = fs::read_to_string(path).map_err(|e| e.to_string())?;
    SchedulerState::from_json(&contents)
}

/// Compact the state by removing Completed and Cancelled jobs older than
/// `max_age_secs` relative to `now_epoch`.
#[allow(dead_code)]
pub fn compact_state(state: &SchedulerState, now_epoch: u64, max_age_secs: u64) -> SchedulerState {
    let mut compacted = SchedulerState {
        jobs: BTreeMap::new(),
        next_job_id: state.next_job_id,
        created_at: state.created_at,
        last_modified_at: state.last_modified_at,
    };
    for (id, job) in &state.jobs {
        let dominated = matches!(job.status, JobStatus::Completed | JobStatus::Cancelled);
        let old_enough = job
            .completed_at
            .map(|t| now_epoch.saturating_sub(t) >= max_age_secs)
            .unwrap_or(false);
        if dominated && old_enough {
            continue; // skip — compact out
        }
        compacted.jobs.insert(id.clone(), job.clone());
    }
    compacted
}

// --- Internal helpers ---

fn json_string(input: &str) -> String {
    format!("{:?}", input)
}

fn option_u64_json(opt: &Option<u64>) -> String {
    match opt {
        Some(v) => v.to_string(),
        None => "null".to_string(),
    }
}

fn option_string_json(opt: &Option<String>) -> String {
    match opt {
        Some(v) => json_string(v),
        None => "null".to_string(),
    }
}

fn extract_json_string(section: &str, key: &str) -> Option<String> {
    let idx = section.find(key)?;
    let after = &section[idx + key.len()..];
    let first_quote = after.find('"')?;
    let rest = &after[first_quote + 1..];
    let end_quote = rest.find('"')?;
    Some(rest[..end_quote].to_string())
}

fn extract_json_u64(section: &str, key: &str) -> Option<u64> {
    let idx = section.find(key)?;
    let after = &section[idx + key.len()..];
    let colon = after.find(':')?;
    let rest = after[colon + 1..].trim_start();
    let end = rest
        .find([',', '}', '\n'])
        .unwrap_or(rest.len());
    rest[..end].trim().parse::<u64>().ok()
}

fn extract_json_u32(section: &str, key: &str) -> Option<u32> {
    let idx = section.find(key)?;
    let after = &section[idx + key.len()..];
    let colon = after.find(':')?;
    let rest = after[colon + 1..].trim_start();
    let end = rest
        .find([',', '}', '\n'])
        .unwrap_or(rest.len());
    rest[..end].trim().parse::<u32>().ok()
}

fn extract_json_optional_u64(section: &str, key: &str) -> Option<u64> {
    let idx = section.find(key)?;
    let after = &section[idx + key.len()..];
    let colon = after.find(':')?;
    let rest = after[colon + 1..].trim_start();
    if rest.starts_with("null") {
        return None;
    }
    let end = rest
        .find([',', '}', '\n'])
        .unwrap_or(rest.len());
    rest[..end].trim().parse::<u64>().ok()
}

fn extract_json_optional_string(section: &str, key: &str) -> Option<String> {
    let idx = section.find(key)?;
    let after = &section[idx + key.len()..];
    let colon = after.find(':')?;
    let rest = after[colon + 1..].trim_start();
    if rest.starts_with("null") {
        return None;
    }
    let first_quote = rest.find('"')?;
    let inner = &rest[first_quote + 1..];
    let end_quote = inner.find('"')?;
    Some(inner[..end_quote].to_string())
}

fn split_json_objects(body: &str) -> Vec<String> {
    let mut objects = Vec::new();
    let mut depth = 0;
    let mut start = None;
    for (i, c) in body.char_indices() {
        match c {
            '{' => {
                if depth == 0 {
                    start = Some(i);
                }
                depth += 1;
            }
            '}' => {
                depth -= 1;
                if depth == 0 {
                    if let Some(s) = start {
                        objects.push(body[s..=i].to_string());
                    }
                    start = None;
                }
            }
            _ => {}
        }
    }
    objects
}

fn find_matching_bracket(s: &str, open_pos: usize) -> usize {
    let mut depth = 0;
    for (i, c) in s[open_pos..].char_indices() {
        match c {
            '[' => depth += 1,
            ']' => {
                depth -= 1;
                if depth == 0 {
                    return open_pos + i;
                }
            }
            _ => {}
        }
    }
    s.len()
}

fn epoch_now() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    #[test]
    fn append_and_transition_lifecycle() {
        let mut state = SchedulerState::new();
        let id = append_job(
            &mut state,
            "agent_atlas",
            "org_demo",
            "research",
            "web_search",
        );
        assert_eq!(state.jobs.get(&id).unwrap().status, JobStatus::Queued);
        assert_eq!(state.jobs.get(&id).unwrap().policy_class, "standard");

        transition_job(&mut state, &id, JobStatus::Reserved).unwrap();
        assert_eq!(state.jobs.get(&id).unwrap().status, JobStatus::Reserved);

        transition_job(&mut state, &id, JobStatus::Running).unwrap();
        assert!(state.jobs.get(&id).unwrap().started_at.is_some());

        transition_job(&mut state, &id, JobStatus::Completed).unwrap();
        assert!(state.jobs.get(&id).unwrap().completed_at.is_some());
        assert_eq!(state.jobs.get(&id).unwrap().status, JobStatus::Completed);
    }

    #[test]
    fn invalid_transition_rejected() {
        let mut state = SchedulerState::new();
        let id = append_job(&mut state, "agent_forge", "org_demo", "build", "docker");

        // Queued -> Completed is not valid
        let err = transition_job(&mut state, &id, JobStatus::Completed);
        assert!(err.is_err());
        assert!(err.unwrap_err().contains("invalid transition"));
    }

    #[test]
    fn save_load_roundtrip() {
        let mut state = SchedulerState {
            jobs: BTreeMap::new(),
            next_job_id: 1,
            created_at: 10000,
            last_modified_at: 10000,
        };
        let id = append_job(&mut state, "agent_quill", "org_demo", "write", "brief");
        // Manually set enqueued_at for deterministic check
        state.jobs.get_mut(&id).unwrap().enqueued_at = 10001;

        let dir = std::env::temp_dir().join("loom-shadow-scheduler-test");
        let _ = fs::create_dir_all(&dir);
        let path = dir.join("state.json");

        save_state(&state, &path).unwrap();
        let loaded = load_state(&path).unwrap();

        assert_eq!(loaded.next_job_id, state.next_job_id);
        assert_eq!(loaded.created_at, 10000);
        assert_eq!(loaded.jobs.len(), 1);
        let j = loaded.jobs.get(&id).unwrap();
        assert_eq!(j.agent_id, "agent_quill");
        assert_eq!(j.action_type, "write");
        assert_eq!(j.queue_bucket, "pending");
        assert_eq!(j.enqueued_at, 10001);
        assert_eq!(j.status, JobStatus::Queued);
        assert!(j.started_at.is_none());
        assert!(j.completed_at.is_none());
        assert!(j.result_summary.is_none());

        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn compact_removes_old_completed_jobs() {
        let mut state = SchedulerState {
            jobs: BTreeMap::new(),
            next_job_id: 3,
            created_at: 1000,
            last_modified_at: 2000,
        };
        // Old completed job
        state.jobs.insert(
            "job_1".to_string(),
            SchedulerJob {
                agent_id: "agent_a".to_string(),
                org_id: "org_x".to_string(),
                action_type: "scan".to_string(),
                resource: "network".to_string(),
                policy_class: "privileged".to_string(),
                queue_bucket: "processed".to_string(),
                status: JobStatus::Completed,
                enqueued_at: 1000,
                started_at: Some(1010),
                completed_at: Some(1050),
                attempt_count: 1,
                lease_owner: None,
                result_summary: Some("done".to_string()),
            },
        );
        // Recent queued job
        state.jobs.insert(
            "job_2".to_string(),
            SchedulerJob {
                agent_id: "agent_b".to_string(),
                org_id: "org_x".to_string(),
                action_type: "research".to_string(),
                resource: "web".to_string(),
                policy_class: "standard".to_string(),
                queue_bucket: "pending".to_string(),
                status: JobStatus::Queued,
                enqueued_at: 2000,
                started_at: None,
                completed_at: None,
                attempt_count: 0,
                lease_owner: None,
                result_summary: None,
            },
        );

        let compacted = compact_state(&state, 5000, 3600);
        assert_eq!(compacted.jobs.len(), 1);
        assert!(compacted.jobs.contains_key("job_2"));
        assert!(!compacted.jobs.contains_key("job_1"));
    }

    #[test]
    fn next_job_id_increments() {
        let mut state = SchedulerState::new();
        let id1 = append_job(&mut state, "a", "o", "t", "r");
        let id2 = append_job(&mut state, "b", "o", "t", "r");
        assert_eq!(id1, "job_1");
        assert_eq!(id2, "job_2");
        assert_eq!(state.next_job_id, 3);
    }

    #[test]
    fn append_job_with_id_preserves_runtime_job_id() {
        let mut state = SchedulerState::new();
        append_job_with_id(
            &mut state,
            "hash_123",
            "agent_atlas",
            "org_demo",
            "research",
            "web_search",
            "budget_heavy",
            "pending:budget_heavy",
        );
        let job = state.jobs.get("hash_123").expect("job");
        assert_eq!(job.policy_class, "budget_heavy");
        assert_eq!(job.queue_bucket, "pending:budget_heavy");
    }
}
