use std::fs;
use std::io::IsTerminal;
use std::path::{Path, PathBuf};
use std::process::Command;

use crate::*;
use loom_core::onboarding::{load_onboard_manifest, write_onboard_manifest};
use loom_core::provider_auth_store::{
    list_provider_auth_profiles, mark_provider_auth_profile_failure,
    mark_provider_auth_profile_used, provider_auth_store_overview,
    render_provider_auth_profile_human, render_provider_auth_profile_json,
    render_provider_auth_profiles_human, render_provider_auth_profiles_json,
    render_provider_auth_store_human, render_provider_auth_store_json, sync_provider_auth_store,
};
use loom_core::provider_router::{
    configure_onboard_provider_routes, default_codex_auth_path_hint, provider_auth_status,
    provider_plane_summary, read_codex_identity_fingerprint, render_provider_auth_human,
    render_provider_auth_json, render_provider_plane_human, render_provider_plane_json,
    render_provider_route_human, render_provider_route_json, resolve_provider_route,
    shared_codex_auth_path_hint, CodexIdentityFingerprint, ProviderRouteIntent,
};

#[derive(Clone, Debug, PartialEq, Eq)]
struct ProviderLoginSummary {
    source: String,
    codex_home: Option<String>,
    staged_auth_path: Option<String>,
    configured_auth_path: String,
    auth_ready: bool,
    detail: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct CodexIdentityRelation {
    configured_auth_path: String,
    configured_account_id: Option<String>,
    configured_subject_id: Option<String>,
    configured_identity_label: Option<String>,
    shared_cli_auth_path: String,
    shared_cli_account_id: Option<String>,
    shared_cli_subject_id: Option<String>,
    shared_cli_identity_label: Option<String>,
    relation: String,
}

pub(crate) fn handle_provider(args: &[String]) -> LoomResult<()> {
    match args.first().map(String::as_str) {
        None | Some("help") | Some("-h") | Some("--help") => {
            print_startup_banner();
            print_human(provider_help_text());
            Ok(())
        }
        Some("status") => handle_provider_status(&args[1..]),
        Some("route") => handle_provider_route(&args[1..]),
        Some("auth") => handle_provider_auth(&args[1..]),
        Some("login") => handle_provider_login(&args[1..]),
        Some("profiles") => handle_provider_profiles(&args[1..]),
        Some("mark-used") => handle_provider_mark_used(&args[1..]),
        Some("mark-failure") => handle_provider_mark_failure(&args[1..]),
        _ => Err("provider supports 'status', 'route', 'auth', 'login', 'profiles', 'mark-used', and 'mark-failure'".to_string()),
    }
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

fn handle_provider_status(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = output_format(args);
    let summary = provider_plane_summary(Some(&root))?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_provider_plane_human(&summary));
        }
        _ => print!("{}", render_provider_plane_json(&summary)),
    }
    Ok(())
}

fn handle_provider_route(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
    let capability =
        take_value(args, "--capability").unwrap_or_else(|| "loom.llm.inference.v1".to_string());
    let requested_model = take_value(args, "--model").unwrap_or_default();
    let mut intent = ProviderRouteIntent::for_capability(&capability, &requested_model);
    if let Some(agent_id) = take_value(args, "--agent-id") {
        intent = intent.with_agent_id(&agent_id);
    }
    if let Some(org_id) = take_value(args, "--org-id") {
        intent = intent.with_org_id(&org_id);
    }
    if let Some(profile) = take_value(args, "--profile") {
        intent = intent.with_preferred_profile_name(&profile);
    }
    let route = resolve_provider_route(Some(&root), &intent)?;
    if format == "json" {
        print!("{}", render_provider_route_json(&route));
    } else {
        print_startup_banner();
        print_human(&render_provider_route_human(&route));
    }
    Ok(())
}

fn handle_provider_auth(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = output_format(args);
    let profile = take_value(args, "--profile");
    let status = provider_auth_status(Some(&root), profile.as_deref())?;
    let codex_relation = codex_identity_relation(&status);
    match format.as_str() {
        "human" => {
            print_startup_banner();
            let mut rendered = render_provider_auth_human(&status);
            if let Some(relation) = codex_relation.as_ref() {
                rendered.push_str(&render_codex_identity_relation_human(relation));
            }
            print_human(&rendered);
        }
        _ => {
            if let Some(relation) = codex_relation.as_ref() {
                print!(
                    "{}",
                    render_provider_auth_with_relation_json(&status, relation)
                );
            } else {
                print!("{}", render_provider_auth_json(&status));
            }
        }
    }
    Ok(())
}

fn handle_provider_login(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_startup_banner();
        print_human(provider_login_help_text());
        return Ok(());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = output_format(args);
    let requested_source =
        take_value(args, "--source").or_else(|| take_value(args, "--codex-auth-source"));
    let requested_auth_path =
        take_value(args, "--auth-path").or_else(|| take_value(args, "--codex-auth-path"));
    let (configured_source, configured_auth_path) = configured_codex_selection(&root);
    let source = requested_source
        .or(configured_source)
        .unwrap_or_else(|| "loom".to_string())
        .trim()
        .to_ascii_lowercase();
    let target_auth_path = resolve_login_target_auth_path(
        &source,
        requested_auth_path.as_deref(),
        configured_auth_path.as_deref(),
    )?;
    let login_home = login_home_for_source(&source, &target_auth_path)?;
    let device_auth = has_flag(args, "--device-auth");
    let with_api_key = has_flag(args, "--with-api-key");
    run_codex_login(&source, login_home.as_deref(), device_auth, with_api_key)?;
    let staged_auth_path =
        staged_auth_path_for_source(&source, login_home.as_deref(), &target_auth_path)?;
    if source != "cli" {
        sync_auth_material(&staged_auth_path, &target_auth_path)?;
    }
    persist_login_selection(&root, &source, &target_auth_path)?;
    let _ = sync_provider_auth_store(&root)?;
    let status = provider_auth_status(Some(&root), Some("manager_frontier"))?;
    let auth_ready = target_auth_path.exists() && status.ready;
    let detail = if status.ready {
        login_detail(&source, device_auth, with_api_key)
    } else {
        format!(
            "{}; {}",
            login_detail(&source, device_auth, with_api_key),
            status.detail
        )
    };
    let summary = ProviderLoginSummary {
        source: source.clone(),
        codex_home: login_home.as_ref().map(|path| path.display().to_string()),
        staged_auth_path: Some(staged_auth_path.display().to_string()),
        configured_auth_path: target_auth_path.display().to_string(),
        auth_ready,
        detail,
    };
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_provider_login_human(&summary));
        }
        _ => print!("{}", render_provider_login_json(&summary)),
    }
    if source == "loom" && !status.ready {
        return Err(status.detail);
    }
    Ok(())
}

fn codex_identity_relation(
    status: &loom_core::provider_router::ProviderAuthStatus,
) -> Option<CodexIdentityRelation> {
    if status.auth_mode != "codex_auth_json" {
        return None;
    }
    let configured_path = status.credential_path.as_ref()?;
    let configured_auth_path = PathBuf::from(configured_path);
    let configured_identity = read_codex_identity_fingerprint(&configured_auth_path);
    let shared_cli_auth_path = shared_codex_auth_path_hint()
        .ok()
        .unwrap_or_else(|| PathBuf::from("~/.codex/auth.json"));
    let shared_cli_identity = read_codex_identity_fingerprint(&shared_cli_auth_path);
    let relation = if configured_auth_path == shared_cli_auth_path {
        "shared_cli_path".to_string()
    } else if configured_identity
        .as_ref()
        .zip(shared_cli_identity.as_ref())
        .map(|(configured, shared)| codex_principal_matches(configured, shared))
        .unwrap_or(false)
    {
        "same_identity_as_cli".to_string()
    } else if configured_identity.is_some() && shared_cli_identity.is_some() {
        "dedicated_account".to_string()
    } else if shared_cli_identity.is_none() {
        "cli_auth_unavailable".to_string()
    } else {
        "unknown".to_string()
    };
    Some(CodexIdentityRelation {
        configured_auth_path: configured_auth_path.display().to_string(),
        configured_account_id: configured_identity
            .as_ref()
            .and_then(|identity| identity.account_id.clone()),
        configured_subject_id: configured_identity
            .as_ref()
            .and_then(|identity| identity.subject_id.clone()),
        configured_identity_label: configured_identity.as_ref().map(describe_identity_label),
        shared_cli_auth_path: shared_cli_auth_path.display().to_string(),
        shared_cli_account_id: shared_cli_identity
            .as_ref()
            .and_then(|identity| identity.account_id.clone()),
        shared_cli_subject_id: shared_cli_identity
            .as_ref()
            .and_then(|identity| identity.subject_id.clone()),
        shared_cli_identity_label: shared_cli_identity.as_ref().map(describe_identity_label),
        relation,
    })
}

fn codex_principal_matches(
    left: &CodexIdentityFingerprint,
    right: &CodexIdentityFingerprint,
) -> bool {
    if let (Some(left), Some(right)) = (left.subject_id.as_deref(), right.subject_id.as_deref()) {
        return left == right;
    }
    if let (Some(left), Some(right)) = (left.email.as_deref(), right.email.as_deref()) {
        return left.eq_ignore_ascii_case(right);
    }
    if let (Some(left), Some(right)) = (left.account_id.as_deref(), right.account_id.as_deref()) {
        return left == right;
    }
    false
}

fn describe_identity_label(identity: &CodexIdentityFingerprint) -> String {
    match (
        identity.name.as_deref().filter(|value| !value.is_empty()),
        identity.email.as_deref().filter(|value| !value.is_empty()),
        identity
            .subject_id
            .as_deref()
            .filter(|value| !value.is_empty()),
        identity
            .account_id
            .as_deref()
            .filter(|value| !value.is_empty()),
    ) {
        (Some(name), Some(email), _, _) => format!("{} <{}>", name, email),
        (Some(name), None, Some(subject), _) => format!("{} [{}]", name, subject),
        (Some(name), None, None, Some(account_id)) => format!("{} [{}]", name, account_id),
        (None, Some(email), _, _) => email.to_string(),
        (None, None, Some(subject), _) => subject.to_string(),
        (None, None, None, Some(account_id)) => account_id.to_string(),
        _ => "unknown".to_string(),
    }
}

fn render_codex_identity_relation_human(relation: &CodexIdentityRelation) -> String {
    format!(
        "identity_scope:      {}
configured_identity: {}
shared_cli_identity: {}
configured_account:  {}
shared_cli_account:  {}
configured_subject:  {}
shared_cli_subject:  {}
shared_cli_auth:     {}
",
        relation.relation,
        relation
            .configured_identity_label
            .as_deref()
            .unwrap_or("(unknown)"),
        relation
            .shared_cli_identity_label
            .as_deref()
            .unwrap_or("(unknown)"),
        relation
            .configured_account_id
            .as_deref()
            .unwrap_or("(unknown)"),
        relation
            .shared_cli_account_id
            .as_deref()
            .unwrap_or("(unknown)"),
        relation
            .configured_subject_id
            .as_deref()
            .unwrap_or("(unknown)"),
        relation
            .shared_cli_subject_id
            .as_deref()
            .unwrap_or("(unknown)"),
        relation.shared_cli_auth_path,
    )
}

fn render_provider_auth_with_relation_json(
    status: &loom_core::provider_router::ProviderAuthStatus,
    relation: &CodexIdentityRelation,
) -> String {
    let mut value = serde_json::from_str::<serde_json::Value>(&render_provider_auth_json(status))
        .unwrap_or_default();
    if let Some(object) = value.as_object_mut() {
        object.insert(
            "identity_scope".to_string(),
            serde_json::Value::String(relation.relation.clone()),
        );
        object.insert(
            "configured_account_id".to_string(),
            relation
                .configured_account_id
                .as_ref()
                .map(|value| serde_json::Value::String(value.clone()))
                .unwrap_or(serde_json::Value::Null),
        );
        object.insert(
            "configured_subject_id".to_string(),
            relation
                .configured_subject_id
                .as_ref()
                .map(|value| serde_json::Value::String(value.clone()))
                .unwrap_or(serde_json::Value::Null),
        );
        object.insert(
            "configured_identity".to_string(),
            relation
                .configured_identity_label
                .as_ref()
                .map(|value| serde_json::Value::String(value.clone()))
                .unwrap_or(serde_json::Value::Null),
        );
        object.insert(
            "shared_cli_account_id".to_string(),
            relation
                .shared_cli_account_id
                .as_ref()
                .map(|value| serde_json::Value::String(value.clone()))
                .unwrap_or(serde_json::Value::Null),
        );
        object.insert(
            "shared_cli_subject_id".to_string(),
            relation
                .shared_cli_subject_id
                .as_ref()
                .map(|value| serde_json::Value::String(value.clone()))
                .unwrap_or(serde_json::Value::Null),
        );
        object.insert(
            "shared_cli_identity".to_string(),
            relation
                .shared_cli_identity_label
                .as_ref()
                .map(|value| serde_json::Value::String(value.clone()))
                .unwrap_or(serde_json::Value::Null),
        );
        object.insert(
            "shared_cli_auth_path".to_string(),
            serde_json::Value::String(relation.shared_cli_auth_path.clone()),
        );
    }
    format!(
        "{}
",
        serde_json::to_string_pretty(&value).unwrap_or_else(|_| "{}".to_string())
    )
}

fn handle_provider_profiles(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = output_format(args);
    let store = provider_auth_store_overview(&root)?;
    let records = list_provider_auth_profiles(&root)?;
    if let Some(profile_name) = take_value(args, "--profile") {
        let record = records
            .into_iter()
            .find(|record| record.profile_name == profile_name)
            .ok_or_else(|| format!("provider auth profile '{}' was not found", profile_name))?;
        match format.as_str() {
            "human" => {
                print_startup_banner();
                print_human(&render_provider_auth_profile_human(&record));
            }
            _ => print!("{}", render_provider_auth_profile_json(&record)),
        }
        return Ok(());
    }

    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_provider_auth_store_human(&store));
            print_human(&render_provider_auth_profiles_human(&records));
        }
        _ => {
            let json = serde_json::json!({
                "store": serde_json::from_str::<serde_json::Value>(&render_provider_auth_store_json(&store)).unwrap_or_else(|_| serde_json::json!({})),
                "profiles": serde_json::from_str::<serde_json::Value>(&render_provider_auth_profiles_json(&records)).unwrap_or_else(|_| serde_json::json!([])),
            });
            print!(
                "{}\n",
                serde_json::to_string_pretty(&json).map_err(|error| error.to_string())?
            );
        }
    }
    Ok(())
}

fn handle_provider_mark_used(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let profile = required_flag(args, "--profile")?;
    let format = output_format(args);
    let record = mark_provider_auth_profile_used(&root, &profile)?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_provider_auth_profile_human(&record));
        }
        _ => print!("{}", render_provider_auth_profile_json(&record)),
    }
    Ok(())
}

fn handle_provider_mark_failure(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let profile = required_flag(args, "--profile")?;
    let format = output_format(args);
    let reason = take_value(args, "--reason");
    let cooldown_ms = take_value(args, "--cooldown-ms")
        .map(|raw| {
            raw.parse::<u64>()
                .map_err(|_| format!("invalid --cooldown-ms '{}'", raw))
        })
        .transpose()?;
    let record =
        mark_provider_auth_profile_failure(&root, &profile, reason.as_deref(), cooldown_ms)?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_provider_auth_profile_human(&record));
        }
        _ => print!("{}", render_provider_auth_profile_json(&record)),
    }
    Ok(())
}

fn configured_codex_selection(root: &Path) -> (Option<String>, Option<String>) {
    let Ok(manifest) = load_onboard_manifest(root) else {
        return (None, None);
    };
    let source = trimmed_string_option(&manifest.codex_auth_source);
    let path = trimmed_string_option(&manifest.codex_auth_path);
    (source, path)
}

fn resolve_login_target_auth_path(
    source: &str,
    requested_auth_path: Option<&str>,
    configured_auth_path: Option<&str>,
) -> LoomResult<PathBuf> {
    match source {
        "loom" => {
            if requested_auth_path.is_some() {
                return Err("--auth-path is only valid with --source path".to_string());
            }
            default_codex_auth_path_hint()
        }
        "cli" => {
            if requested_auth_path.is_some() {
                return Err("--auth-path is not used with --source cli".to_string());
            }
            shared_codex_auth_path_hint()
        }
        "path" => {
            let raw = requested_auth_path
                .or(configured_auth_path)
                .ok_or_else(|| "--source path requires --auth-path or an onboard manifest with a configured custom auth path".to_string())?;
            expand_auth_path(raw)
        }
        other => Err(format!(
            "unsupported provider login source '{}' (expected loom, cli, or path)",
            other
        )),
    }
}

fn login_home_for_source(source: &str, target_auth_path: &Path) -> LoomResult<Option<PathBuf>> {
    match source {
        "loom" | "path" => {
            let parent = target_auth_path.parent().ok_or_else(|| {
                format!(
                    "auth path {} has no parent directory",
                    target_auth_path.display()
                )
            })?;
            let home = parent.join("login-home");
            fs::create_dir_all(&home).map_err(|error| error.to_string())?;
            Ok(Some(home))
        }
        "cli" => Ok(None),
        other => Err(format!("unsupported provider login source '{}'", other)),
    }
}

fn staged_auth_path_for_source(
    source: &str,
    login_home: Option<&Path>,
    target_auth_path: &Path,
) -> LoomResult<PathBuf> {
    match source {
        "loom" | "path" => {
            let home = login_home
                .ok_or_else(|| "dedicated provider login requires a Codex home".to_string())?;
            Ok(home.join(".codex/auth.json"))
        }
        "cli" => Ok(target_auth_path.to_path_buf()),
        other => Err(format!("unsupported provider login source '{}'", other)),
    }
}

fn run_codex_login(
    source: &str,
    login_home: Option<&Path>,
    device_auth: bool,
    with_api_key: bool,
) -> LoomResult<()> {
    let mut command = Command::new("codex");
    command.arg("login");
    if device_auth {
        command.arg("--device-auth");
    }
    if with_api_key {
        command.arg("--with-api-key");
    }
    if matches!(source, "loom" | "path") {
        let home = login_home
            .ok_or_else(|| "dedicated provider login requires a Codex home".to_string())?;
        fs::create_dir_all(home.join(".codex")).map_err(|error| error.to_string())?;
        command.env("HOME", home);
        command.env_remove("CODEX_HOME");
    }
    let status = command
        .status()
        .map_err(|error| format!("failed to launch codex login: {}", error))?;
    if !status.success() {
        return Err(format!("codex login exited with status {}", status));
    }
    Ok(())
}

fn sync_auth_material(staged_auth_path: &Path, target_auth_path: &Path) -> LoomResult<()> {
    if !staged_auth_path.exists() {
        return Err(format!(
            "codex login completed but no auth.json was found at {}",
            staged_auth_path.display()
        ));
    }
    if let Some(parent) = target_auth_path.parent() {
        fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    fs::copy(staged_auth_path, target_auth_path).map_err(|error| {
        format!(
            "failed to sync Codex auth.json from {} to {}: {}",
            staged_auth_path.display(),
            target_auth_path.display(),
            error
        )
    })?;
    set_private_permissions_if_supported(target_auth_path, 0o600)?;
    Ok(())
}

fn persist_login_selection(root: &Path, source: &str, target_auth_path: &Path) -> LoomResult<()> {
    let Ok(mut manifest) = load_onboard_manifest(root) else {
        return Ok(());
    };
    manifest.codex_auth_source = source.to_string();
    manifest.codex_auth_path = target_auth_path.display().to_string();
    write_onboard_manifest(root, &manifest)?;
    configure_onboard_provider_routes(
        root,
        &manifest.manager_lane,
        Some(&manifest.manager_model),
        Some(&manifest.codex_auth_path),
    )?;
    Ok(())
}

fn expand_auth_path(raw: &str) -> LoomResult<PathBuf> {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return Err("auth path must not be empty".to_string());
    }
    let path = PathBuf::from(trimmed);
    if path.is_absolute() {
        return Ok(path);
    }
    let home = std::env::var("HOME")
        .map_err(|_| "HOME is not set and relative auth paths cannot be resolved".to_string())?;
    Ok(PathBuf::from(home).join(path))
}

fn trimmed_string_option(raw: &str) -> Option<String> {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        None
    } else {
        Some(trimmed.to_string())
    }
}

fn login_detail(source: &str, device_auth: bool, with_api_key: bool) -> String {
    let method = if with_api_key {
        "api_key"
    } else if device_auth {
        "device_auth"
    } else {
        "interactive"
    };
    match source {
        "loom" => format!(
            "dedicated Loom Codex login captured via {} and synced into Loom-managed auth storage",
            method
        ),
        "cli" => format!(
            "shared Codex CLI login completed via {} in the operator home",
            method
        ),
        "path" => format!(
            "dedicated Codex login captured via {} and synced into the configured auth path",
            method
        ),
        _ => format!("Codex login completed via {}", method),
    }
}

fn render_provider_login_human(summary: &ProviderLoginSummary) -> String {
    format!(
        "Meridian Loom // PROVIDER LOGIN\n===============================\nsource:               {}\ncodex_home:           {}\nstaged_auth_path:     {}\nconfigured_auth_path: {}\nauth_ready:           {}\ndetail:               {}\nnext_step:            loom provider auth --profile manager_frontier\n",
        summary.source,
        summary.codex_home.as_deref().unwrap_or("(shared operator home)"),
        summary.staged_auth_path.as_deref().unwrap_or("(none)"),
        summary.configured_auth_path,
        if summary.auth_ready { "yes" } else { "no" },
        summary.detail,
    )
}

fn render_provider_login_json(summary: &ProviderLoginSummary) -> String {
    serde_json::to_string_pretty(&serde_json::json!({
        "source": summary.source,
        "codex_home": summary.codex_home,
        "staged_auth_path": summary.staged_auth_path,
        "configured_auth_path": summary.configured_auth_path,
        "auth_ready": summary.auth_ready,
        "detail": summary.detail,
        "next_step": "loom provider auth --profile manager_frontier"
    }))
    .unwrap_or_else(|_| "{}".to_string())
}

fn provider_help_text() -> &'static str {
    "Meridian Loom // PROVIDER HELP
=============================
  loom provider status [--root PATH] [--format human|json]
  loom provider route [--root PATH] [--capability NAME] [--model NAME] [--agent-id ID] [--org-id ORG] [--profile NAME] [--format human|json]
  loom provider auth [--root PATH] [--profile NAME] [--format human|json]
  loom provider login [--root PATH] [--source loom|cli|path] [--auth-path PATH] [--device-auth|--with-api-key] [--format human|json]
  loom provider profiles [--root PATH] [--profile NAME] [--format human|json]
  loom provider mark-used --profile NAME [--root PATH] [--format human|json]
  loom provider mark-failure --profile NAME [--reason TEXT] [--cooldown-ms N] [--root PATH] [--format human|json]
"
}

fn provider_login_help_text() -> &'static str {
    "Meridian Loom // PROVIDER LOGIN HELP
===================================
Use a dedicated Loom account by default:
  loom provider login --source loom --device-auth
  The dedicated Loom login must not reuse the shared Codex CLI account.

Reuse the shared Codex CLI login:
  loom provider login --source cli

Write a dedicated login into a custom auth path:
  loom provider login --source path --auth-path ~/.meridian/auth/codex-team/auth.json --device-auth

Flags:
  --root PATH         runtime root used to read or update the onboard manifest
  --source            one of loom, cli, or path
  --auth-path PATH    required with --source path
  --device-auth       use device authorization flow
  --with-api-key      read API key from stdin for login
  --format            human or json
"
}
