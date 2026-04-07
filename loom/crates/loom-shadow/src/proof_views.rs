use crate::event_schema::RuntimeEventV1;

pub fn render_proof_first_status_human(label: &str, event: &RuntimeEventV1) -> String {
    format!(
        "{label}\n{rule}\nschema_version:    {schema}\ntruth_class:       {truth}\nevent_id:          {event_id}\njob_id:            {job_id}\nexecution_id:      {execution_id}\ndecision_id:       {decision_id}\nparity_id:         {parity_id}\naudit_id:          {audit_id}\nartifact_count:    {artifact_count}\n",
        label = label,
        rule = "=".repeat(label.len()),
        schema = event.schema_version,
        truth = event.truth_class,
        event_id = event.event_id,
        job_id = event.job_id,
        execution_id = event.execution_id,
        decision_id = event.decision_id,
        parity_id = event.parity_id,
        audit_id = event.audit_id,
        artifact_count = event.artifact_refs.len(),
    )
}
