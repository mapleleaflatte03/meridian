use std::fmt::Write as _;

pub const EVENT_SCHEMA_VERSION: &str = "loom.runtime.v1";

fn canonical_join(parts: &[&str]) -> String {
    parts
        .iter()
        .map(|part| normalize_token(part))
        .filter(|part| !part.is_empty())
        .collect::<Vec<_>>()
        .join("::")
}

fn normalize_token(value: &str) -> String {
    value
        .trim()
        .chars()
        .map(|ch| match ch {
            'A'..='Z' | 'a'..='z' | '0'..='9' | '-' | '_' | '.' => ch,
            ' ' | '\t' => '_',
            _ => '_',
        })
        .collect::<String>()
}

fn json_escape(input: &str) -> String {
    let mut out = String::with_capacity(input.len() + 8);
    for ch in input.chars() {
        match ch {
            '\\' => out.push_str("\\\\"),
            '"' => out.push_str("\\\""),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            _ => out.push(ch),
        }
    }
    out
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ArtifactRef {
    pub artifact_id: String,
    pub artifact_kind: String,
    pub label: String,
    pub path: String,
    pub source_event_id: String,
    pub job_id: String,
    pub execution_id: String,
    pub content_sha256: String,
    pub note: String,
}

impl ArtifactRef {
    pub fn new(
        artifact_kind: impl Into<String>,
        label: impl Into<String>,
        path: impl Into<String>,
        source_event_id: impl Into<String>,
        job_id: impl Into<String>,
        execution_id: impl Into<String>,
        content_sha256: impl Into<String>,
        note: impl Into<String>,
    ) -> Self {
        let artifact_kind = artifact_kind.into();
        let label = label.into();
        let job_id = job_id.into();
        let execution_id = execution_id.into();
        let artifact_id = canonical_artifact_id(&artifact_kind, &job_id, &execution_id, &label);
        Self {
            artifact_id,
            artifact_kind,
            label,
            path: path.into(),
            source_event_id: source_event_id.into(),
            job_id,
            execution_id,
            content_sha256: content_sha256.into(),
            note: note.into(),
        }
    }
}

pub fn canonical_event_id(
    org_id: &str,
    agent_id: &str,
    action_type: &str,
    resource: &str,
    outcome: &str,
    stage: &str,
    job_id: &str,
    execution_id: &str,
) -> String {
    canonical_join(&[
        EVENT_SCHEMA_VERSION,
        org_id,
        agent_id,
        action_type,
        resource,
        outcome,
        stage,
        job_id,
        execution_id,
    ])
}

pub fn canonical_envelope_id(
    org_id: &str,
    agent_id: &str,
    action_type: &str,
    input_hash: &str,
) -> String {
    canonical_join(&["envelope", org_id, agent_id, action_type, input_hash])
}

pub fn canonical_artifact_id(
    artifact_kind: &str,
    job_id: &str,
    execution_id: &str,
    label: &str,
) -> String {
    canonical_join(&["artifact", artifact_kind, job_id, execution_id, label])
}

pub fn canonical_job_id(
    org_id: &str,
    agent_id: &str,
    action_type: &str,
    input_hash: &str,
) -> String {
    canonical_join(&["job", org_id, agent_id, action_type, input_hash])
}

pub fn canonical_execution_id(job_id: &str, stage: &str, outcome: &str) -> String {
    canonical_join(&["execution", job_id, stage, outcome])
}

pub fn canonical_decision_id(job_id: &str, stage: &str, decision: &str) -> String {
    canonical_join(&["decision", job_id, stage, decision])
}

pub fn canonical_parity_id(job_id: &str, execution_id: &str, parity_status: &str) -> String {
    canonical_join(&["parity", job_id, execution_id, parity_status])
}

pub fn canonical_audit_id(job_id: &str, execution_id: &str, action_type: &str) -> String {
    canonical_join(&["audit", job_id, execution_id, action_type])
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ArtifactRefSpec {
    pub artifact_kind: String,
    pub label: String,
    pub path: String,
    pub source_event_id: String,
    pub job_id: String,
    pub execution_id: String,
    pub content_sha256: String,
    pub note: String,
}

impl ArtifactRefSpec {
    pub fn into_ref(self) -> ArtifactRef {
        ArtifactRef::new(
            self.artifact_kind,
            self.label,
            self.path,
            self.source_event_id,
            self.job_id,
            self.execution_id,
            self.content_sha256,
            self.note,
        )
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RuntimeEventSpec {
    pub truth_class: String,
    pub org_id: String,
    pub agent_id: String,
    pub action_type: String,
    pub resource: String,
    pub outcome: String,
    pub stage: String,
    pub source: String,
    pub subject_kind: String,
    pub subject_id: String,
    pub job_id: String,
    pub execution_id: String,
    pub decision_id: String,
    pub parity_id: String,
    pub audit_id: String,
    pub note: String,
    pub artifact_refs: Vec<ArtifactRefSpec>,
}

impl RuntimeEventSpec {
    pub fn into_event(self) -> RuntimeEventV1 {
        RuntimeEventV1::from_context(
            self.org_id,
            self.agent_id,
            self.action_type,
            self.resource,
            self.outcome,
            self.stage,
            self.source,
            self.subject_kind,
            self.subject_id,
            self.job_id,
            self.execution_id,
            self.decision_id,
            self.parity_id,
            self.audit_id,
            self.truth_class,
            self.note,
            self.artifact_refs
                .into_iter()
                .map(ArtifactRefSpec::into_ref)
                .collect(),
        )
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RuntimeEventV1 {
    pub schema_version: String,
    pub event_id: String,
    pub truth_class: String,
    pub org_id: String,
    pub agent_id: String,
    pub action_type: String,
    pub resource: String,
    pub outcome: String,
    pub stage: String,
    pub source: String,
    pub subject_kind: String,
    pub subject_id: String,
    pub job_id: String,
    pub execution_id: String,
    pub decision_id: String,
    pub parity_id: String,
    pub audit_id: String,
    pub note: String,
    pub artifact_refs: Vec<ArtifactRef>,
}

#[allow(dead_code)]
impl RuntimeEventV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn from_context(
        org_id: impl Into<String>,
        agent_id: impl Into<String>,
        action_type: impl Into<String>,
        resource: impl Into<String>,
        outcome: impl Into<String>,
        stage: impl Into<String>,
        source: impl Into<String>,
        subject_kind: impl Into<String>,
        subject_id: impl Into<String>,
        job_id: impl Into<String>,
        execution_id: impl Into<String>,
        decision_id: impl Into<String>,
        parity_id: impl Into<String>,
        audit_id: impl Into<String>,
        truth_class: impl Into<String>,
        note: impl Into<String>,
        artifact_refs: Vec<ArtifactRef>,
    ) -> Self {
        let org_id = org_id.into();
        let agent_id = agent_id.into();
        let action_type = action_type.into();
        let resource = resource.into();
        let outcome = outcome.into();
        let stage = stage.into();
        let job_id = job_id.into();
        let execution_id = execution_id.into();
        let decision_id = decision_id.into();
        let parity_id = parity_id.into();
        let audit_id = audit_id.into();
        let event_id = canonical_event_id(
            &org_id,
            &agent_id,
            &action_type,
            &resource,
            &outcome,
            &stage,
            &job_id,
            &execution_id,
        );
        Self {
            schema_version: EVENT_SCHEMA_VERSION.to_string(),
            event_id,
            truth_class: truth_class.into(),
            org_id,
            agent_id,
            action_type,
            resource,
            outcome,
            stage,
            source: source.into(),
            subject_kind: subject_kind.into(),
            subject_id: subject_id.into(),
            job_id,
            execution_id,
            decision_id,
            parity_id,
            audit_id,
            note: note.into(),
            artifact_refs,
        }
    }

    pub fn artifact_index(&self) -> Vec<String> {
        self.artifact_refs
            .iter()
            .map(|artifact| artifact.artifact_id.clone())
            .collect()
    }

    pub fn render_json(&self) -> String {
        let mut out = String::from("{\n");
        let fields = [
            ("schema_version", self.schema_version.as_str()),
            ("event_id", self.event_id.as_str()),
            ("truth_class", self.truth_class.as_str()),
            ("org_id", self.org_id.as_str()),
            ("agent_id", self.agent_id.as_str()),
            ("action_type", self.action_type.as_str()),
            ("resource", self.resource.as_str()),
            ("outcome", self.outcome.as_str()),
            ("stage", self.stage.as_str()),
            ("source", self.source.as_str()),
            ("subject_kind", self.subject_kind.as_str()),
            ("subject_id", self.subject_id.as_str()),
            ("job_id", self.job_id.as_str()),
            ("execution_id", self.execution_id.as_str()),
            ("decision_id", self.decision_id.as_str()),
            ("parity_id", self.parity_id.as_str()),
            ("audit_id", self.audit_id.as_str()),
            ("note", self.note.as_str()),
        ];
        for (idx, (key, value)) in fields.iter().enumerate() {
            let suffix = if idx + 1 == fields.len() && self.artifact_refs.is_empty() {
                ""
            } else {
                ","
            };
            let _ = writeln!(out, "  \"{}\": \"{}\"{}", key, json_escape(value), suffix);
        }
        out.push_str("  \"artifact_refs\": [");
        if self.artifact_refs.is_empty() {
            out.push_str("]\n");
        } else {
            out.push('\n');
            for (idx, artifact) in self.artifact_refs.iter().enumerate() {
                let suffix = if idx + 1 == self.artifact_refs.len() {
                    ""
                } else {
                    ","
                };
                let _ = writeln!(
                    out,
                    "    {{\"artifact_id\":\"{}\",\"artifact_kind\":\"{}\",\"label\":\"{}\",\"path\":\"{}\",\"source_event_id\":\"{}\",\"job_id\":\"{}\",\"execution_id\":\"{}\",\"content_sha256\":\"{}\",\"note\":\"{}\"}}{}",
                    json_escape(&artifact.artifact_id),
                    json_escape(&artifact.artifact_kind),
                    json_escape(&artifact.label),
                    json_escape(&artifact.path),
                    json_escape(&artifact.source_event_id),
                    json_escape(&artifact.job_id),
                    json_escape(&artifact.execution_id),
                    json_escape(&artifact.content_sha256),
                    json_escape(&artifact.note),
                    suffix,
                );
            }
            out.push_str("  ]\n");
        }
        out.push('}');
        out
    }

    pub fn render_json_line(&self) -> String {
        let fields = [
            ("schema_version", self.schema_version.as_str()),
            ("event_id", self.event_id.as_str()),
            ("truth_class", self.truth_class.as_str()),
            ("org_id", self.org_id.as_str()),
            ("agent_id", self.agent_id.as_str()),
            ("action_type", self.action_type.as_str()),
            ("resource", self.resource.as_str()),
            ("outcome", self.outcome.as_str()),
            ("stage", self.stage.as_str()),
            ("source", self.source.as_str()),
            ("subject_kind", self.subject_kind.as_str()),
            ("subject_id", self.subject_id.as_str()),
            ("job_id", self.job_id.as_str()),
            ("execution_id", self.execution_id.as_str()),
            ("decision_id", self.decision_id.as_str()),
            ("parity_id", self.parity_id.as_str()),
            ("audit_id", self.audit_id.as_str()),
            ("note", self.note.as_str()),
        ];
        let head = fields
            .iter()
            .map(|(key, value)| format!("\"{}\":\"{}\"", key, json_escape(value)))
            .collect::<Vec<_>>()
            .join(",");
        let artifacts = self
            .artifact_refs
            .iter()
            .map(|artifact| {
                format!(
                    "{{\"artifact_id\":\"{}\",\"artifact_kind\":\"{}\",\"label\":\"{}\",\"path\":\"{}\",\"source_event_id\":\"{}\",\"job_id\":\"{}\",\"execution_id\":\"{}\",\"content_sha256\":\"{}\",\"note\":\"{}\"}}",
                    json_escape(&artifact.artifact_id),
                    json_escape(&artifact.artifact_kind),
                    json_escape(&artifact.label),
                    json_escape(&artifact.path),
                    json_escape(&artifact.source_event_id),
                    json_escape(&artifact.job_id),
                    json_escape(&artifact.execution_id),
                    json_escape(&artifact.content_sha256),
                    json_escape(&artifact.note),
                )
            })
            .collect::<Vec<_>>()
            .join(",");
        format!("{{{},\"artifact_refs\":[{}]}}", head, artifacts)
    }

    pub fn render_human(&self) -> String {
        let mut out = String::new();
        let _ = writeln!(
            out,
            "Meridian Loom // RUNTIME EVENT V1\n==================================\nphase:       proof-first canonical runtime event\nboundary:    runtime event identities and artifact links are explicit; hosted parity is still future work\n"
        );
        let _ = writeln!(
            out,
            "Canonical IDs\n=============\nschema_version: {}\nevent_id:       {}\njob_id:         {}\nexecution_id:   {}\ndecision_id:    {}\nparity_id:      {}\naudit_id:       {}\n",
            self.schema_version,
            self.event_id,
            self.job_id,
            self.execution_id,
            self.decision_id,
            self.parity_id,
            self.audit_id,
        );
        let _ = writeln!(
            out,
            "Context\n=======\ntruth_class:    {}\norg_id:         {}\nagent_id:       {}\naction_type:    {}\nresource:       {}\noutcome:        {}\nstage:          {}\nsource:         {}\nsubject_kind:   {}\nsubject_id:     {}\nnote:           {}\n",
            self.truth_class,
            self.org_id,
            self.agent_id,
            self.action_type,
            self.resource,
            self.outcome,
            self.stage,
            self.source,
            self.subject_kind,
            self.subject_id,
            self.note,
        );
        out.push_str("Artifacts\n=========\n");
        if self.artifact_refs.is_empty() {
            out.push_str("(none)\n");
        } else {
            for artifact in &self.artifact_refs {
                let _ = writeln!(
                    out,
                    "- {} | kind={} | path={} | source={} | job={} | exec={} | note={}",
                    artifact.artifact_id,
                    artifact.artifact_kind,
                    artifact.path,
                    artifact.source_event_id,
                    artifact.job_id,
                    artifact.execution_id,
                    artifact.note,
                );
            }
        }
        out
    }
}

pub fn render_artifact_refs_human(refs: &[ArtifactRef]) -> String {
    if refs.is_empty() {
        return "(none)\n".to_string();
    }
    refs.iter()
        .map(|artifact| {
            format!(
                "- {} | kind={} | label={} | path={} | source={} | note={}\n",
                artifact.artifact_id,
                artifact.artifact_kind,
                artifact.label,
                artifact.path,
                artifact.source_event_id,
                artifact.note,
            )
        })
        .collect::<String>()
}

pub fn render_artifact_refs_json(refs: &[ArtifactRef]) -> String {
    if refs.is_empty() {
        return "[]".to_string();
    }
    let rendered = refs
        .iter()
        .map(|artifact| {
            format!(
                "{{\"artifact_id\":\"{}\",\"artifact_kind\":\"{}\",\"label\":\"{}\",\"path\":\"{}\",\"source_event_id\":\"{}\",\"job_id\":\"{}\",\"execution_id\":\"{}\",\"content_sha256\":\"{}\",\"note\":\"{}\"}}",
                json_escape(&artifact.artifact_id),
                json_escape(&artifact.artifact_kind),
                json_escape(&artifact.label),
                json_escape(&artifact.path),
                json_escape(&artifact.source_event_id),
                json_escape(&artifact.job_id),
                json_escape(&artifact.execution_id),
                json_escape(&artifact.content_sha256),
                json_escape(&artifact.note),
            )
        })
        .collect::<Vec<_>>()
        .join(", ");
    format!("[{}]", rendered)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn canonical_ids_are_stable_and_tokenized() {
        let job_id = canonical_job_id("org_demo", "agent_atlas", "research", "abc123");
        let execution_id = canonical_execution_id(&job_id, "runtime_execute", "worker_executed");
        let envelope_id = canonical_envelope_id("org_demo", "agent_atlas", "research", "abc123");
        assert!(job_id.starts_with("job::"));
        assert!(execution_id.starts_with("execution::"));
        assert!(envelope_id.starts_with("envelope::"));
    }

    #[test]
    fn runtime_event_spec_builds_event_and_artifact_refs() {
        let job_id = canonical_job_id("org_demo", "agent_atlas", "research", "abc123");
        let execution_id = canonical_execution_id(&job_id, "runtime_execute", "worker_executed");
        let event = RuntimeEventSpec {
            truth_class: "experimental_runtime".to_string(),
            org_id: "org_demo".to_string(),
            agent_id: "agent_atlas".to_string(),
            action_type: "research".to_string(),
            resource: "web_search".to_string(),
            outcome: "allow".to_string(),
            stage: "runtime_execute".to_string(),
            source: "loom_runtime".to_string(),
            subject_kind: "envelope".to_string(),
            subject_id: canonical_envelope_id("org_demo", "agent_atlas", "research", "abc123"),
            job_id: job_id.clone(),
            execution_id: execution_id.clone(),
            decision_id: canonical_decision_id(&job_id, "runtime_execute", "allow"),
            parity_id: canonical_parity_id(&job_id, &execution_id, "match"),
            audit_id: canonical_audit_id(&job_id, &execution_id, "research"),
            note: "proof-first event".to_string(),
            artifact_refs: vec![ArtifactRefSpec {
                artifact_kind: "execution_receipt".to_string(),
                label: "runtime_execution".to_string(),
                path: ".loom/runtime/last_execution.json".to_string(),
                source_event_id: "evt".to_string(),
                job_id,
                execution_id,
                content_sha256: "unverified_local".to_string(),
                note: "receipt".to_string(),
            }],
        }
        .into_event();
        assert_eq!(event.schema_version, EVENT_SCHEMA_VERSION);
        assert_eq!(event.artifact_refs.len(), 1);
        assert!(render_artifact_refs_json(&event.artifact_refs).contains("execution_receipt"));
        assert!(event
            .render_json_line()
            .contains("\"schema_version\":\"loom.runtime.v1\""));
    }
}
