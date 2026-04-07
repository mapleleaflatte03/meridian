use std::env;
use std::fs;
use std::io::{self, IsTerminal, Write};
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use crate::*;
use loom_core::agent_runtime::agent_runtime_overview;
use loom_core::bindings::sync_binding_registry;
use loom_core::channels::sync_channel_registry;
use loom_core::gateway_runtime::sync_gateway_runtime;
use loom_core::onboarding::{
    derive_service_http_address, detect_setup_state, ensure_onboard_manifest,
    load_onboard_manifest, onboard_manifest_path, onboard_overview, onboard_path_hint,
    write_onboard_manifest, OnboardManifest, SetupState,
};
use loom_core::provider_auth_store::{provider_auth_store_overview, sync_provider_auth_store};
use loom_core::provider_router::{
    configure_onboard_provider_profile, configure_onboard_provider_routes,
    default_codex_auth_path_hint, load_provider_profiles, provider_auth_status,
    provider_plane_summary, resolve_provider_route, shared_codex_auth_path_hint,
    OnboardProviderRouteConfig, ProviderAuthMode, ProviderKind, ProviderRouteIntent,
};
use loom_core::schedules::{schedule_overview, sync_schedule_registry};
use loom_core::service_ingress_runtime::sync_service_ingress_runtime;
use loom_core::service_runtime::sync_service_runtime;
use loom_core::skills::sync_skill_registry;
use serde_json::{json, Value};

pub(crate) fn handle_onboard(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_onboard_help();
        return Ok(());
    }

    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = take_value(args, "--format").unwrap_or_else(|| {
        if std::io::stdout().is_terminal() {
            "human".to_string()
        } else {
            "json".to_string()
        }
    });
    let requested_mode = take_value(args, "--mode").unwrap_or_else(|| "embedded".to_string());
    let requested_org_id = take_value(args, "--org-id").unwrap_or_else(|| "default".to_string());
    let kernel_path = take_value(args, "--kernel-path");
    let interactive = format == "human"
        && !has_flag(args, "--non-interactive")
        && std::io::stdin().is_terminal()
        && std::io::stdout().is_terminal();

    let setup_state = detect_setup_state(&root);
    let had_existing_config = root.join("loom.toml").exists();
    let had_existing_manifest = onboard_manifest_path(&root).exists();
    let existing_manifest_action = if had_existing_manifest {
        load_onboard_manifest(&root)
            .ok()
            .map(|manifest| manifest.last_action)
    } else {
        None
    };
    let is_fresh_runtime =
        had_existing_config && existing_manifest_action.as_deref() == Some("initialized");
    let mut config_action = take_value(args, "--config-action").unwrap_or_else(|| {
        if is_fresh_runtime {
            "setup".to_string()
        } else if had_existing_config {
            "keep".to_string()
        } else {
            "init".to_string()
        }
    });
    if had_existing_config && has_setup_overrides(args) && config_action == "keep" {
        config_action = "modify".to_string();
    }
    if interactive
        && had_existing_config
        && had_existing_manifest
        && !is_fresh_runtime
        && !has_setup_overrides(args)
    {
        config_action = prompt_select(
            "Existing Loom runtime detected. Choose action",
            &config_action,
            &[
                PromptSelectOption {
                    value: "keep",
                    label: "Keep current setup",
                    hint: "Leave the runtime as-is and review the current state only.",
                },
                PromptSelectOption {
                    value: "modify",
                    label: "Adjust current setup",
                    hint: "Walk through setup again and update the live runtime defaults.",
                },
                PromptSelectOption {
                    value: "reset",
                    label: "Reset and rebuild",
                    hint: "Discard the current runtime config and rewrite it from scratch.",
                },
            ],
        )?;
    }

    if had_existing_config && config_action == "reset" {
        let _ = fs::remove_file(root.join("loom.toml"));
        let _ = fs::remove_file(onboard_manifest_path(&root));
    }

    let config_status = if root.join("loom.toml").exists() {
        if !had_existing_config || is_fresh_runtime {
            "initialized"
        } else if config_action == "modify" {
            "modified"
        } else {
            "reused"
        }
    } else {
        "initialized"
    };

    let mut config = if root.join("loom.toml").exists() {
        read_config(&root)?
    } else {
        init_workspace(
            &root,
            &requested_mode,
            kernel_path.as_deref(),
            &requested_org_id,
        )?
    };

    if config_action != "keep" {
        if let Some(mode) = take_value(args, "--mode") {
            config.mode = mode;
        }
        if let Some(org_id) = take_value(args, "--org-id") {
            config.org_id = org_id;
        }
        if let Some(kernel_path) = kernel_path.as_deref() {
            config.kernel_path = kernel_path.to_string();
        }
    }

    let _ = ensure_onboard_manifest(&root, &config)?;
    let mut manifest = load_onboard_manifest(&root)?;
    let current_brain = current_manager_brain(&root, &manifest);
    let explicit_manager_model = take_value(args, "--manager-model");
    let explicit_codex_auth_source = take_value(args, "--codex-auth-source");
    let explicit_codex_auth_path = take_value(args, "--codex-auth-path");
    let mut manager_lane =
        take_value(args, "--manager-lane").unwrap_or_else(|| current_brain.lane.clone());
    let mut manager_model = explicit_manager_model
        .clone()
        .unwrap_or_else(|| current_brain.model.clone());
    let mut codex_auth_source = explicit_codex_auth_source
        .clone()
        .unwrap_or_else(|| current_brain.codex_auth_source.clone());
    let mut codex_auth_path = if explicit_codex_auth_path.is_some() {
        explicit_codex_auth_path.clone()
    } else if explicit_codex_auth_source.is_some() {
        None
    } else {
        current_brain.codex_auth_path.clone()
    };
    if explicit_codex_auth_path.is_some() && explicit_codex_auth_source.is_none() {
        codex_auth_source = "path".to_string();
    }
    let mut banner_rendered = false;
    let mut interactive_provider_config: Option<OnboardProviderRouteConfig> = None;

    if interactive {
        print_startup_banner();
        banner_rendered = true;
        print_human("Meridian Loom // SETUP\n=======================\n");
        print_setup_note(
            "Setup overview",
            &format!(
                "Choose your manager brain, edge bindings, and runtime defaults.\n\
                 Meridian will scaffold the governed runtime, but the operator still owns the final configuration.\n\
                 Current setup state: {}\n\
                 Hint: {}",
                setup_state_label(&setup_state),
                onboard_path_hint(&setup_state),
            ),
        );
    } else if format == "human" {
        print_startup_banner();
        banner_rendered = true;
        print_human(
            "Meridian Loom // SETUP (non-interactive)\n=========================================\n",
        );
        print_setup_note(
            "Current state",
            &format!(
                "Setup state: {}\nHint: {}",
                setup_state_label(&setup_state),
                onboard_path_hint(&setup_state),
            ),
        );
    }

    if interactive && config_action != "keep" {
        // Security acknowledgment
        print_setup_note(
            "Security notice",
            "Meridian Loom governs autonomous agent actions on your behalf.\n\
             All pipeline runs are subject to the constitutional contract.\n\
             Actions are audited and cost-attributed to the owning org.\n\
             Provider credentials stay under the runtime root.\n\
             No telemetry leaves this host without explicit configuration.",
        );
        let ack = prompt_bool("Acknowledge and continue", true)?;
        if !ack {
            return Err("Setup cancelled — security acknowledgment declined.".to_string());
        }

        // Quickstart vs manual mode
        let setup_mode = prompt_select(
            "Setup mode",
            "quickstart",
            &[
                PromptSelectOption {
                    value: "quickstart",
                    label: "QuickStart",
                    hint: "Keep Meridian's default edge, daemon, and recurring setup. You only choose the provider path now.",
                },
                PromptSelectOption {
                    value: "manual",
                    label: "Manual setup",
                    hint: "Walk every stage and tune the runtime defaults before writing the root.",
                },
            ],
        )?;
        let default_provider_choice =
            default_provider_choice_for_state(&manager_lane, current_brain.provider_kind.as_ref());

        if setup_mode == "quickstart" {
            print_quickstart_summary_card(&manifest, &manager_model);
            print_setup_stage(
                1,
                5,
                "Provider",
                "Choose the inference path Meridian should wire now. QuickStart keeps the edge, daemon, and recurring defaults intact.",
            );
            let provider_choice = prompt_select(
                "Inference provider",
                default_provider_choice,
                &[
                    PromptSelectOption {
                        value: "loom_codex",
                        label: "Loom-managed Codex OAuth",
                        hint: "Frontier lane with a Meridian-owned auth file and device-auth setup.",
                    },
                    PromptSelectOption {
                        value: "local_ollama",
                        label: "Local Ollama",
                        hint: "Stay fully local and point the manager at an Ollama model on this host.",
                    },
                    PromptSelectOption {
                        value: "openai_compatible",
                        label: "OpenAI-compatible endpoint",
                        hint: "Use a standard chat-completions endpoint with a bearer token env var.",
                    },
                    PromptSelectOption {
                        value: "custom_endpoint",
                        label: "Custom endpoint",
                        hint: "Wire a non-standard HTTP endpoint with explicit auth mode selection.",
                    },
                    PromptSelectOption {
                        value: "local_only",
                        label: "Local-only for now",
                        hint: "Skip remote provider setup and keep the runtime entirely local until later.",
                    },
                ],
            )?;
            let selection = prompt_provider_setup(
                &provider_choice,
                &manager_model,
                &codex_auth_source,
                codex_auth_path.clone(),
                false,
            )?;
            print_provider_selection_preview(&provider_choice, &selection);
            manager_lane = selection.manager_lane;
            manager_model = selection.manager_model;
            codex_auth_source = selection.codex_auth_source;
            codex_auth_path = selection.codex_auth_path;
            interactive_provider_config = selection.provider_config;
            print_setup_note(
                "QuickStart defaults",
                "Meridian will now confirm the local edge, daemon, and built-in runtime defaults before writing the runtime root.",
            );
        } else {
            // Manual: full interactive flow
            print_setup_stage(
                1,
                5,
                "Manager provider",
                "Pick the provider, model, and account Meridian should use for Leviathann.",
            );
            let provider_choice = prompt_select(
                "Inference provider",
                default_provider_choice,
                &[
                    PromptSelectOption {
                        value: "loom_codex",
                        label: "Loom-managed Codex OAuth",
                        hint: "Frontier lane with a Meridian-owned auth file and device-auth setup.",
                    },
                    PromptSelectOption {
                        value: "local_ollama",
                        label: "Local Ollama",
                        hint: "Stay fully local and point the manager at an Ollama model on this host.",
                    },
                    PromptSelectOption {
                        value: "openai_compatible",
                        label: "OpenAI-compatible endpoint",
                        hint: "Use a standard chat-completions endpoint with a bearer token env var.",
                    },
                    PromptSelectOption {
                        value: "custom_endpoint",
                        label: "Custom endpoint",
                        hint: "Wire a non-standard HTTP endpoint with explicit auth mode selection.",
                    },
                    PromptSelectOption {
                        value: "local_only",
                        label: "Local-only for now",
                        hint: "Skip remote provider setup and keep the runtime entirely local until later.",
                    },
                ],
            )?;
            let selection = prompt_provider_setup(
                &provider_choice,
                &manager_model,
                &codex_auth_source,
                codex_auth_path.clone(),
                true,
            )?;
            print_provider_selection_preview(&provider_choice, &selection);
            manager_lane = selection.manager_lane;
            manager_model = selection.manager_model;
            codex_auth_source = selection.codex_auth_source;
            codex_auth_path = selection.codex_auth_path;
            interactive_provider_config = selection.provider_config;
        }
        apply_interactive_overrides(&mut manifest)?;
    }
    apply_cli_overrides(args, &mut manifest)?;
    let uses_codex_auth = interactive_provider_config
        .as_ref()
        .map(|config| matches!(config.kind, ProviderKind::OpenAiCodex))
        .unwrap_or(true);
    let (codex_auth_source, codex_auth_path) = if uses_codex_auth {
        normalize_codex_auth_selection(&manager_lane, &codex_auth_source, codex_auth_path)?
    } else {
        ("none".to_string(), None)
    };
    manifest.manager_lane = manager_lane.clone();
    manifest.manager_model = manager_model.clone();
    manifest.codex_auth_source = codex_auth_source.clone();
    manifest.codex_auth_path = codex_auth_path.clone().unwrap_or_default();
    let human_output = format == "human";
    let progress_mode = if interactive {
        ProgressRenderMode::Animated
    } else if human_output {
        ProgressRenderMode::Transcript
    } else {
        ProgressRenderMode::Silent
    };
    let (provider_profiles_path, provider_auth_sync, manifest_path) = run_with_spinner(
        progress_mode,
        "Writing runtime plan",
        Some("Saving the manager route, gateway edge, and governed defaults."),
        || {
            let provider_profiles_path =
                if let Some(provider_config) = interactive_provider_config.as_ref() {
                    configure_onboard_provider_profile(&root, provider_config)?
                } else {
                    configure_onboard_provider_routes(
                        &root,
                        &manager_lane,
                        Some(&manager_model),
                        codex_auth_path.as_deref(),
                    )?
                };
            let provider_auth_sync = sync_provider_auth_store(&root)?;

            if manifest.gateway_auth_mode == "none" && manifest.gateway_token_env.trim().is_empty()
            {
                manifest.gateway_token_env = config.service_token_env.clone();
            }
            manifest.last_action = if is_fresh_runtime {
                "setup".to_string()
            } else if had_existing_config {
                config_action.clone()
            } else {
                "init".to_string()
            };
            manifest.last_run_at = current_unix();
            manifest.last_run_mode = config.mode.clone();

            config.service_http_address =
                derive_service_http_address(&manifest.gateway_bind, manifest.gateway_port);
            if manifest.gateway_auth_mode != "none" {
                config.service_token_env = manifest.gateway_token_env.clone();
            }
            loom_core::write_config(&root, &config)?;
            let manifest_path = write_onboard_manifest(&root, &manifest)?;
            Ok((provider_profiles_path, provider_auth_sync, manifest_path))
        },
    )?;
    if human_output {
        print_progress_status(
            "ok",
            "Runtime plan saved",
            Some(&format!(
                "The runtime root and onboard manifest were updated under {}.",
                root.display()
            )),
        );
    }
    let (
        channel_summary,
        gateway_runtime,
        service_runtime,
        ingress_runtime,
        binding_summary,
        skill_summary,
        schedule_sync,
        schedule_runtime,
    ) = run_with_spinner(
        progress_mode,
        "Syncing runtime ledgers",
        Some("Refreshing provider state, channels, services, bindings, skills, and schedules."),
        || {
            let channel_summary = sync_channel_registry(&root)?;
            let gateway_runtime = sync_gateway_runtime(&root)?;
            let service_runtime = sync_service_runtime(&root)?;
            let ingress_runtime = sync_service_ingress_runtime(&root)?;
            let binding_summary = sync_binding_registry(&root)?;
            let skill_summary = sync_skill_registry(&root)?;
            let schedule_sync = sync_schedule_registry(&root)?;
            let schedule_runtime = schedule_overview(&root, current_unix_ms())?;
            fs::create_dir_all(root.join("state/memory")).map_err(|error| error.to_string())?;
            Ok((
                channel_summary,
                gateway_runtime,
                service_runtime,
                ingress_runtime,
                binding_summary,
                skill_summary,
                schedule_sync,
                schedule_runtime,
            ))
        },
    )?;
    if human_output {
        print_progress_status(
            "ok",
            "Runtime ledgers synced",
            Some(&format!(
                "Providers={} channels={} skills={} recurring={}",
                provider_auth_sync.profile_count,
                channel_summary.total_count,
                skill_summary.total_count,
                schedule_sync.total_count
            )),
        );
    }

    let provider_summary = provider_plane_summary(Some(&root))?;
    let provider_auth_summary = provider_auth_store_overview(&root)?;
    let runtime_overview = agent_runtime_overview(&root)?;
    let manager_route = resolve_provider_route(
        Some(&root),
        &ProviderRouteIntent::llm_inference("").with_agent_id("leviathann"),
    )
    .ok();
    let configured_manager_provider = configured_manager_provider(&root).ok();
    let manager_profile_name = manager_route
        .as_ref()
        .map(|route| route.profile_name.clone())
        .or_else(|| {
            configured_manager_provider
                .as_ref()
                .map(|route| route.profile_name.clone())
        });
    let manager_profile_kind = manager_route
        .as_ref()
        .map(|route| route.profile_kind.clone())
        .or_else(|| {
            configured_manager_provider
                .as_ref()
                .map(|route| route.profile_kind.clone())
        });
    let manager_auth_status =
        provider_auth_status(Some(&root), manager_profile_name.as_deref()).ok();
    let codex_status = manager_profile_kind
        .as_ref()
        .filter(|kind| matches!(kind, ProviderKind::OpenAiCodex))
        .and_then(|_| manager_auth_status.clone());
    let pulse_route = resolve_provider_route(
        Some(&root),
        &ProviderRouteIntent::llm_inference("").with_agent_id("pulse"),
    )
    .ok();
    let start_daemon_requested =
        if interactive && config_action != "keep" && manifest.daemon_enabled {
            prompt_bool(
                "Start supervisor daemon now",
                has_flag(args, "--start-daemon"),
            )?
        } else {
            has_flag(args, "--start-daemon")
        };
    let daemon_snapshot = if start_daemon_requested
        && manifest.daemon_enabled
        && manifest.daemon_manager == "supervisor"
    {
        let snapshot = run_with_spinner(
            progress_mode,
            "Starting supervisor daemon",
            Some("Handing background lifecycle to the local supervisor."),
            || start_supervisor_daemon(&root, kernel_path.as_deref()),
        )?;
        manifest.daemon_state = daemon_state_from_snapshot(&snapshot);
        write_onboard_manifest(&root, &manifest)?;
        if human_output {
            print_progress_status(
                "ok",
                "Supervisor daemon ready",
                Some(&render_daemon_summary(&snapshot)),
            );
        }
        Some(snapshot)
    } else {
        None
    };

    let health_requested = if interactive && config_action != "keep" {
        prompt_bool(
            "Run post-setup health check",
            !has_flag(args, "--skip-health-check"),
        )?
    } else {
        !has_flag(args, "--skip-health-check")
    };
    let health_snapshot = if health_requested {
        let (healthy, report) = run_with_spinner(
            progress_mode,
            "Running post-setup health check",
            Some("Checking provider, gateway, service, and runtime surfaces."),
            || health(&root),
        )?;
        if human_output {
            print_progress_status(
                if healthy { "ok" } else { "!!" },
                "Health check complete",
                Some(if healthy {
                    "The fresh runtime is healthy."
                } else {
                    "Some runtime surfaces still need attention before the operator can call this green."
                }),
            );
        }
        Some((healthy, report))
    } else {
        if human_output {
            print_progress_status(
                "--",
                "Health check skipped",
                Some("Run loom doctor when you are ready to verify the runtime."),
            );
        }
        None
    };

    let final_setup_state = detect_setup_state(&root);
    let overview = onboard_overview(&root)?;

    let codex_ready = codex_status
        .as_ref()
        .map(|status| status.ready)
        .unwrap_or(false);
    let codex_path = codex_status
        .as_ref()
        .and_then(|status| status.credential_path.clone());
    let codex_detail = if let Some(status) = codex_status.as_ref() {
        status.detail.clone()
    } else {
        codex_detail_for_manager(manager_profile_kind.as_ref())
    };
    let manager_auth_ready = manager_auth_status
        .as_ref()
        .map(|status| status.ready)
        .unwrap_or(false);
    let manager_auth_mode = manager_auth_status
        .as_ref()
        .map(|status| status.auth_mode.clone())
        .unwrap_or_else(|| "(unknown)".to_string());

    if format == "json" {
        print!(
            "{}",
            serde_json::to_string_pretty(&json!({
                "root": root.display().to_string(),
                "setup_state": setup_state_label(&final_setup_state),
                "setup_hint": onboard_path_hint(&final_setup_state),
                "config_status": config_status,
                "config_action": config_action,
                "mode": config.mode,
                "org_id": config.org_id,
                "provider_profiles": provider_summary.profile_count,
                "provider_profiles_path": provider_profiles_path.display().to_string(),
                "provider_auth_runtime": {
                    "profile_count": provider_auth_summary.profile_count,
                    "ready_count": provider_auth_summary.ready_count,
                    "last_good_count": provider_auth_summary.last_good_count,
                    "usage_stats_count": provider_auth_summary.usage_stats_count,
                    "profiles": provider_auth_summary.profile_names.clone(),
                    "sync_ready_count": provider_auth_sync.ready_count,
                },
                "agent_profiles": runtime_overview.profile_count,
                "manager_lane": manager_lane,
                "manager_provider_profile": manager_route
                    .as_ref()
                    .map(|route| route.profile_name.clone())
                    .or_else(|| configured_manager_provider.as_ref().map(|route| route.profile_name.clone())),
                "manager_transport_kind": manager_route
                    .as_ref()
                    .map(|route| route.transport_kind().to_string())
                    .or_else(|| configured_manager_provider.as_ref().map(|route| route.transport_kind.clone())),
                "manager_model_config": manager_model,
                "codex_auth_source": manifest.codex_auth_source,
                "configured_codex_auth_path": if manifest.codex_auth_path.trim().is_empty() { None } else { Some(manifest.codex_auth_path.clone()) },
                "codex_auth_ready": codex_ready,
                "codex_credential_path": codex_path,
                "codex_detail": codex_detail,
                "manifest_path": manifest_path.display().to_string(),
                "onboard": {
                    "brain": overview.brain_summary,
                    "gateway": overview.gateway_summary,
                    "telegram": overview.telegram_summary,
                    "daemon": overview.daemon_summary,
                    "skills": overview.skills_summary,
                    "recurring": overview.recurring_summary,
                    "remote_mode": overview.remote_mode,
                    "channels": {
                        "total_count": channel_summary.total_count,
                        "enabled_count": channel_summary.enabled_count,
                        "channel_ids": channel_summary.channel_ids.clone(),
                    },
                    "gateway_runtime": {
                        "gateway_id": gateway_runtime.gateway_id.clone(),
                        "endpoint": gateway_runtime.endpoint.clone(),
                        "auth_mode": gateway_runtime.auth_mode.clone(),
                        "remote_mode": gateway_runtime.remote_mode.clone(),
                        "daemon_summary": gateway_runtime.daemon_summary.clone(),
                        "total_channel_count": gateway_runtime.total_channel_count,
                        "enabled_channel_count": gateway_runtime.enabled_channel_count,
                        "channel_ids": gateway_runtime.channel_ids.clone(),
                    },
                    "service_runtime": {
                        "service_health": service_runtime.service_health.clone(),
                        "service_http_address": service_runtime.service_http_address.clone(),
                        "service_pending_jobs": service_runtime.service_pending_jobs,
                        "service_processed_jobs": service_runtime.service_processed_jobs,
                        "supervisor_health": service_runtime.supervisor_health.clone(),
                        "supervisor_pending_jobs": service_runtime.supervisor_pending_jobs,
                        "supervisor_processed_jobs": service_runtime.supervisor_processed_jobs,
                    },
                    "service_ingress_runtime": {
                        "total_requests": ingress_runtime.total_requests,
                        "accepted_count": ingress_runtime.accepted_count,
                        "pending_count": ingress_runtime.pending_count,
                        "last_request_id": ingress_runtime.last_request_id.clone(),
                        "last_job_id": ingress_runtime.last_job_id.clone(),
                    },
                    "bindings_runtime": {
                        "total_count": binding_summary.total_count,
                        "enabled_count": binding_summary.enabled_count,
                        "binding_ids": binding_summary.binding_ids.clone(),
                    },
                    "skills_runtime": {
                        "total_count": skill_summary.total_count,
                        "enabled_count": skill_summary.enabled_count,
                        "default_count": skill_summary.default_count,
                        "imported_count": skill_summary.imported_count,
                        "skill_ids": skill_summary.skill_ids.clone(),
                    },
                    "schedules_runtime": {
                        "total_count": schedule_sync.total_count,
                        "enabled_count": schedule_sync.enabled_count,
                        "due_count": schedule_runtime.due_count,
                        "job_ids": schedule_sync.job_ids.clone(),
                    },
                },
                "manager_route": manager_route.as_ref().map(route_json),
                "manager_route_configured": configured_manager_provider.as_ref().map(configured_route_json),
                "pulse_route": pulse_route.as_ref().map(route_json),
                "daemon": daemon_snapshot,
                "health": health_snapshot.as_ref().map(|(healthy, report)| json!({
                    "status": if *healthy { "healthy" } else { "degraded" },
                    "report": report,
                })),
            }))
            .map_err(|error| error.to_string())?
        );
        println!();
        return Ok(());
    }

    let manager_endpoint = manager_route
        .as_ref()
        .map(|route| route.endpoint_url.to_string())
        .or_else(|| {
            configured_manager_provider
                .as_ref()
                .map(|route| route.endpoint.clone())
        })
        .unwrap_or_else(|| "(pending provider setup)".to_string());
    let manager_route_model = manager_route
        .as_ref()
        .map(|route| route.model.clone())
        .or_else(|| {
            configured_manager_provider
                .as_ref()
                .map(|route| route.model.clone())
        })
        .unwrap_or_else(|| "(pending provider setup)".to_string());
    let manager_route_status = if manager_route.is_some() {
        "ready".to_string()
    } else if configured_manager_provider.is_some() {
        "configured but not ready — action required".to_string()
    } else {
        "not connected — action required".to_string()
    };
    let pulse_profile = pulse_route
        .as_ref()
        .map(|route| format!("{} ({})", route.profile_name, route.profile_kind.label()))
        .unwrap_or_else(|| "not connected — action required".to_string());
    let daemon_summary = daemon_snapshot
        .as_ref()
        .map(render_daemon_summary)
        .unwrap_or_else(|| overview.daemon_summary.clone());
    let health_summary = health_snapshot
        .as_ref()
        .map(|(healthy, _)| if *healthy { "healthy" } else { "degraded" }.to_string())
        .unwrap_or_else(|| "skipped".to_string());
    let manager_next_step = if manager_auth_ready {
        format!("loom service status --root {}", root.display())
    } else if let Some(status) = manager_auth_status.as_ref() {
        match status.auth_mode.as_str() {
            "codex_auth_json" => "loom provider login --source loom --device-auth".to_string(),
            "bearer_env" | "static_header_env" => format!(
                "export {}=... && loom doctor --root {} --format human",
                status
                    .env_var
                    .as_deref()
                    .unwrap_or("MERIDIAN_PROVIDER_TOKEN"),
                root.display()
            ),
            _ => format!("loom doctor --root {} --format human", root.display()),
        }
    } else {
        format!("loom doctor --root {} --format human", root.display())
    };
    let current_state_hint = manager_current_state_hint(
        &final_setup_state,
        manager_profile_kind.as_ref(),
        manager_route.is_some(),
        &manager_endpoint,
        &manager_route_model,
        manager_auth_status.as_ref(),
    );
    let manager_profile_name = manager_route
        .as_ref()
        .map(|route| route.profile_name.as_str())
        .or_else(|| {
            configured_manager_provider
                .as_ref()
                .map(|route| route.profile_name.as_str())
        })
        .unwrap_or("(pending provider setup)");
    let manager_transport_label = manager_route
        .as_ref()
        .map(|route| route.transport_kind())
        .or_else(|| {
            configured_manager_provider
                .as_ref()
                .map(|route| route.transport_kind.as_str())
        })
        .unwrap_or("(pending provider setup)");
    let next_steps = build_next_steps(&root, manager_auth_ready, &manager_next_step);

    if !banner_rendered {
        print_startup_banner();
    }
    if config_status == "initialized" {
        print_human("Meridian // READY TO LAUNCH\n============================\n");
        print_setup_note(
            "Finish line",
            &format!(
                "Root:             {}\n\
                 Setup state:      {}\n\
                 Manager route:    {} via {} ({})\n\
                 Auth:             {} [{}]\n\
                 Gateway edge:     {}\n\
                 Telegram:         {}\n\
                 Defaults seeded:  skills={} recurring={}\n\
                 Runtime health:   {}",
                root.display(),
                setup_state_label(&final_setup_state),
                manager_model,
                manager_profile_name,
                manager_transport_label,
                manager_auth_mode.as_str(),
                if manager_auth_ready {
                    "ready"
                } else {
                    "action required"
                },
                overview.gateway_summary,
                overview.telegram_summary,
                skill_summary.total_count,
                schedule_sync.total_count,
                health_summary,
            ),
        );
        print_setup_note("Current state", &current_state_hint);
        print_setup_note("Next move", &render_numbered_steps(&next_steps));
    } else {
        print_human(&format!(
            "Meridian Loom // ONBOARD
=========================
root:                {}
setup_state:         {}
config_status:       {}
config_action:       {}
mode:                {}
org_id:              {}
brain:               {}
manager_lane:        {}
manager_provider:    {}
manager_transport:   {}
gateway:             {}
telegram:            {}
daemon:              {}
health:              {}
provider plane:      profiles={} ready={} last_good={}
manager_endpoint:    {}
manager_model:       {}
manager_route:       {}
channels:            total={} enabled={}
service runtime:     service={} supervisor={} pending={} processed={}
ingress runtime:     requests={} accepted={} pending={}
skills runtime:      total={} enabled={} defaults={} imported={}
recurring runtime:   total={} enabled={} due={}
codex auth:          {} [{}]
pulse route:         {}
manifest:            {}
next_step:           loom doctor --root {} --format human
",
            root.display(),
            setup_state_label(&final_setup_state),
            config_status,
            config_action,
            config.mode,
            config.org_id,
            overview.brain_summary,
            manager_lane,
            manager_route
                .as_ref()
                .map(|route| route.profile_name.as_str())
                .or_else(|| configured_manager_provider
                    .as_ref()
                    .map(|route| route.profile_name.as_str()))
                .unwrap_or("(pending provider setup)"),
            manager_route
                .as_ref()
                .map(|route| route.transport_kind())
                .or_else(|| configured_manager_provider
                    .as_ref()
                    .map(|route| route.transport_kind.as_str()))
                .unwrap_or("(pending provider setup)"),
            overview.gateway_summary,
            overview.telegram_summary,
            daemon_summary,
            health_summary,
            provider_auth_summary.profile_count,
            provider_auth_summary.ready_count,
            provider_auth_summary.last_good_count,
            manager_endpoint,
            manager_route_model,
            manager_route_status,
            channel_summary.total_count,
            channel_summary.enabled_count,
            service_runtime.service_health,
            service_runtime.supervisor_health,
            service_runtime.service_pending_jobs + service_runtime.supervisor_pending_jobs,
            service_runtime.service_processed_jobs + service_runtime.supervisor_processed_jobs,
            ingress_runtime.total_requests,
            ingress_runtime.accepted_count,
            ingress_runtime.pending_count,
            skill_summary.total_count,
            skill_summary.enabled_count,
            skill_summary.default_count,
            skill_summary.imported_count,
            schedule_sync.total_count,
            schedule_sync.enabled_count,
            schedule_runtime.due_count,
            manager_auth_mode.as_str(),
            if manager_auth_ready {
                "ready"
            } else {
                "action required"
            },
            pulse_profile,
            manifest_path.display(),
            root.display(),
        ));
    }

    Ok(())
}

fn setup_state_label(state: &SetupState) -> &'static str {
    match state {
        SetupState::FreshWorkspace => "fresh_workspace",
        SetupState::FreshNoAuth { .. } => "fresh_no_auth",
        SetupState::ProviderConfiguredAuthPending { .. } => "provider_configured_auth_pending",
        SetupState::LocalOnly { .. } => "local_only",
        SetupState::FrontierAvailable { .. } => "frontier_available",
        SetupState::FullyConfigured { .. } => "fully_configured",
    }
}

fn has_setup_overrides(args: &[String]) -> bool {
    const FLAGS: &[&str] = &[
        "--manager-lane",
        "--manager-model",
        "--codex-auth-source",
        "--codex-auth-path",
        "--gateway-port",
        "--gateway-bind",
        "--gateway-auth-mode",
        "--gateway-token-env",
        "--tailscale-mode",
        "--telegram-enabled",
        "--telegram-token-env",
        "--telegram-dm-policy",
        "--telegram-group-policy",
        "--telegram-streaming",
        "--dm-scope",
        "--daemon-enabled",
        "--daemon-manager",
        "--remote-mode",
        "--skills-node-manager",
        "--skills-entry",
        "--recurring-install-defaults",
        "--recurring-entry",
        "--start-daemon",
        "--skip-health-check",
        "--mode",
        "--org-id",
        "--kernel-path",
    ];
    FLAGS.iter().any(|flag| has_flag(args, flag))
}

fn apply_cli_overrides(args: &[String], manifest: &mut OnboardManifest) -> LoomResult<()> {
    if let Some(port) = take_value(args, "--gateway-port") {
        manifest.gateway_port = parse_u16("--gateway-port", &port)?;
    }
    if let Some(bind) = take_value(args, "--gateway-bind") {
        manifest.gateway_bind = bind;
    }
    if let Some(mode) = take_value(args, "--gateway-auth-mode") {
        manifest.gateway_auth_mode = mode;
    }
    if let Some(token_env) = take_value(args, "--gateway-token-env") {
        manifest.gateway_token_env = token_env;
    }
    if let Some(mode) = take_value(args, "--tailscale-mode") {
        manifest.gateway_tailscale_mode = mode;
    }
    if let Some(value) = take_value(args, "--telegram-enabled") {
        manifest.telegram_enabled = parse_bool_flag("--telegram-enabled", &value)?;
    }
    if let Some(token_env) = take_value(args, "--telegram-token-env") {
        manifest.telegram_token_env = token_env;
    }
    if let Some(value) = take_value(args, "--telegram-dm-policy") {
        manifest.telegram_dm_policy = value;
    }
    if let Some(value) = take_value(args, "--telegram-group-policy") {
        manifest.telegram_group_policy = value;
    }
    if let Some(value) = take_value(args, "--telegram-streaming") {
        manifest.telegram_streaming = value;
    }
    if let Some(value) = take_value(args, "--dm-scope") {
        manifest.session_dm_scope = value;
    }
    if let Some(value) = take_value(args, "--daemon-enabled") {
        manifest.daemon_enabled = parse_bool_flag("--daemon-enabled", &value)?;
        if !manifest.daemon_enabled {
            manifest.daemon_state = "disabled".to_string();
        }
    }
    if let Some(value) = take_value(args, "--daemon-manager") {
        manifest.daemon_manager = value;
    }
    if let Some(value) = take_value(args, "--remote-mode") {
        manifest.remote_mode = value;
    }
    if let Some(value) = take_value(args, "--skills-node-manager") {
        manifest.skills_node_manager = value;
    }
    let entries = take_values(args, "--skills-entry");
    if !entries.is_empty() {
        manifest.skills_entries = entries;
    }
    if let Some(value) = take_value(args, "--recurring-install-defaults") {
        manifest.recurring_install_defaults =
            parse_bool_flag("--recurring-install-defaults", &value)?;
    }
    let recurring_entries = take_values(args, "--recurring-entry");
    if !recurring_entries.is_empty() {
        manifest.recurring_entries = recurring_entries;
    }
    Ok(())
}

fn apply_interactive_overrides(manifest: &mut OnboardManifest) -> LoomResult<()> {
    print_setup_stage(
        2,
        5,
        "Gateway edge",
        "Shape the local web edge before Meridian exposes the service.",
    );
    manifest.remote_mode = prompt_text("Remote mode", &manifest.remote_mode)?;
    manifest.gateway_bind =
        prompt_choice("Gateway bind", &manifest.gateway_bind, &["loopback", "all"])?;
    manifest.gateway_port = parse_u16(
        "gateway port",
        &prompt_text("Gateway port", &manifest.gateway_port.to_string())?,
    )?;
    manifest.gateway_auth_mode = prompt_choice(
        "Gateway auth mode",
        &manifest.gateway_auth_mode,
        &["token", "none"],
    )?;
    manifest.gateway_token_env = prompt_text("Gateway token env", &manifest.gateway_token_env)?;
    manifest.gateway_tailscale_mode = prompt_choice(
        "Gateway tailscale mode",
        &manifest.gateway_tailscale_mode,
        &["off", "on"],
    )?;
    print_setup_stage(
        3,
        5,
        "Telegram edge",
        "Configure delivery without borrowing someone else's bot state.",
    );
    manifest.telegram_enabled = prompt_bool("Enable Telegram channel", manifest.telegram_enabled)?;
    if manifest.telegram_enabled {
        manifest.telegram_token_env =
            prompt_text("Telegram token env", &manifest.telegram_token_env)?;
        manifest.telegram_dm_policy =
            prompt_text("Telegram DM policy", &manifest.telegram_dm_policy)?;
        manifest.telegram_group_policy =
            prompt_text("Telegram group policy", &manifest.telegram_group_policy)?;
        manifest.telegram_streaming =
            prompt_text("Telegram streaming", &manifest.telegram_streaming)?;
    }
    print_setup_stage(
        4,
        5,
        "Runtime daemon",
        "Choose how Meridian stays alive after setup finishes.",
    );
    manifest.session_dm_scope = prompt_text("Session DM scope", &manifest.session_dm_scope)?;
    manifest.daemon_enabled = prompt_bool("Enable supervisor daemon", manifest.daemon_enabled)?;
    manifest.daemon_manager =
        prompt_choice("Daemon manager", &manifest.daemon_manager, &["supervisor"])?;
    print_setup_stage(
        5,
        5,
        "Skills and defaults",
        "Finish by seeding the built-in skills Meridian expects on day one.",
    );
    manifest.skills_node_manager = prompt_choice(
        "Skills node manager",
        &manifest.skills_node_manager,
        &["npm", "pnpm", "bun"],
    )?;
    let skill_entries = prompt_text(
        "Default skills entries (comma separated)",
        &manifest.skills_entries.join(","),
    )?;
    manifest.skills_entries = skill_entries
        .split(',')
        .map(str::trim)
        .filter(|entry| !entry.is_empty())
        .map(|entry| entry.to_string())
        .collect();
    manifest.recurring_install_defaults = prompt_bool(
        "Install default recurring jobs",
        manifest.recurring_install_defaults,
    )?;
    let recurring_entries = prompt_text(
        "Recurring job entries (comma separated)",
        &manifest.recurring_entries.join(","),
    )?;
    manifest.recurring_entries = recurring_entries
        .split(',')
        .map(str::trim)
        .filter(|entry| !entry.is_empty())
        .map(|entry| entry.to_string())
        .collect();
    Ok(())
}

#[derive(Clone, Debug)]
struct ManagerBrainSelection {
    lane: String,
    model: String,
    codex_auth_source: String,
    codex_auth_path: Option<String>,
    provider_kind: Option<ProviderKind>,
}

fn current_manager_brain(root: &Path, manifest: &OnboardManifest) -> ManagerBrainSelection {
    let route = resolve_provider_route(
        Some(root),
        &ProviderRouteIntent::llm_inference("").with_agent_id("leviathann"),
    )
    .ok();
    let lane = route
        .as_ref()
        .map(|resolved| {
            if resolved.profile_name == "local_ollama"
                || resolved.profile_kind.label() == "local_ollama"
            {
                "local".to_string()
            } else {
                "frontier".to_string()
            }
        })
        .unwrap_or_else(|| default_manager_lane(manifest));
    let model = route
        .as_ref()
        .map(|resolved| resolved.model.trim().to_string())
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| default_manager_model(&lane, manifest));
    let (codex_auth_source, codex_auth_path) = current_codex_auth_selection(root)
        .unwrap_or_else(|_| manifest_codex_auth_selection(manifest, &lane));
    let provider_kind = route.as_ref().map(|resolved| resolved.profile_kind.clone());
    let (codex_auth_source, codex_auth_path) = match provider_kind.as_ref() {
        Some(ProviderKind::OpenAiCodex) | None => (codex_auth_source, codex_auth_path),
        _ => ("none".to_string(), None),
    };
    ManagerBrainSelection {
        lane,
        model,
        codex_auth_source,
        codex_auth_path,
        provider_kind,
    }
}

#[derive(Clone, Debug)]
struct ProviderSetupSelection {
    manager_lane: String,
    manager_model: String,
    codex_auth_source: String,
    codex_auth_path: Option<String>,
    provider_config: Option<OnboardProviderRouteConfig>,
}

#[derive(Clone, Copy, Debug)]
struct PromptSelectOption<'a> {
    value: &'a str,
    label: &'a str,
    hint: &'a str,
}

#[derive(Clone, Debug)]
struct ConfiguredManagerRoute {
    profile_name: String,
    profile_kind: ProviderKind,
    endpoint: String,
    model: String,
    transport_kind: String,
}

fn default_provider_choice_for_state(
    lane: &str,
    provider_kind: Option<&ProviderKind>,
) -> &'static str {
    match provider_kind {
        Some(ProviderKind::OpenAiCompatible) => "openai_compatible",
        Some(ProviderKind::CustomEndpoint) => "custom_endpoint",
        Some(ProviderKind::LocalOllama) => "local_ollama",
        _ if lane.eq_ignore_ascii_case("local") => "local_ollama",
        _ => "loom_codex",
    }
}

fn print_quickstart_summary_card(manifest: &OnboardManifest, manager_model: &str) {
    print_setup_note(
        "QuickStart summary",
        &format!(
            "Manager model:    {}\n\
             Best for:         operator-first frontier setup with local edge defaults\n\
             Runtime lane:     frontier-first with local edge defaults\n\
             Gateway edge:     {}:{} auth={} tailscale={}\n\
             Telegram:         {}\n\
             Daemon:           {} ({})\n\
             Skills defaults:  {}\n\
             Recurring:        {}",
            manager_model,
            manifest.gateway_bind,
            manifest.gateway_port,
            manifest.gateway_auth_mode,
            manifest.gateway_tailscale_mode,
            if manifest.telegram_enabled {
                "enabled"
            } else {
                "disabled"
            },
            if manifest.daemon_enabled {
                "enabled"
            } else {
                "disabled"
            },
            manifest.daemon_manager,
            manifest.skills_entries.join(","),
            if manifest.recurring_install_defaults {
                "enabled"
            } else {
                "disabled"
            },
        ),
    );
}

fn print_provider_selection_preview(provider_choice: &str, selection: &ProviderSetupSelection) {
    let (provider_label, transport_label, auth_label, next_label) =
        provider_selection_details(provider_choice, selection);
    print_setup_note(
        "Route preview",
        &format!(
            "Provider:         {}\n\
             Manager lane:     {}\n\
             Model:            {}\n\
             Transport:        {}\n\
             Auth:             {}\n\
             Next write:       {}",
            provider_label,
            selection.manager_lane,
            selection.manager_model,
            transport_label,
            auth_label,
            next_label,
        ),
    );
}

fn provider_selection_details(
    provider_choice: &str,
    selection: &ProviderSetupSelection,
) -> (&'static str, &'static str, String, &'static str) {
    match provider_choice {
        "loom_codex" => {
            let auth_label = match selection.codex_auth_source.as_str() {
                "cli" => "shared operator Codex auth.json".to_string(),
                "path" => format!(
                    "custom Codex auth.json ({})",
                    selection
                        .codex_auth_path
                        .as_deref()
                        .unwrap_or("(missing path)")
                ),
                _ => "Loom-managed device auth file".to_string(),
            };
            (
                "Loom-managed Codex OAuth",
                "codex_session",
                auth_label,
                "Meridian will write the frontier route and keep local edge defaults.",
            )
        }
        "local_ollama" => (
            "Local Ollama",
            "ollama_local",
            "no remote credential required".to_string(),
            "Meridian will keep the runtime local-only until you add a frontier path.",
        ),
        "local_only" => (
            "Local-only",
            "ollama_local",
            "no remote credential required".to_string(),
            "Meridian will skip remote provider setup for this install.",
        ),
        "openai_compatible" => {
            let auth_label = match selection
                .provider_config
                .as_ref()
                .map(|config| &config.auth)
            {
                Some(ProviderAuthMode::BearerEnv { env_var }) => {
                    format!("bearer token env {}", env_var)
                }
                _ => "bearer token env".to_string(),
            };
            (
                "OpenAI-compatible endpoint",
                "openai_rest",
                auth_label,
                "Meridian will save the endpoint and expect the env var before doctor turns green.",
            )
        }
        "custom_endpoint" => {
            let auth_label = match selection
                .provider_config
                .as_ref()
                .map(|config| &config.auth)
            {
                Some(ProviderAuthMode::StaticHeaderEnv {
                    header_name,
                    env_var,
                }) => format!("{} from env {}", header_name, env_var),
                Some(ProviderAuthMode::BearerEnv { env_var }) => {
                    format!("bearer token env {}", env_var)
                }
                Some(ProviderAuthMode::None) => "no auth header".to_string(),
                _ => "custom auth".to_string(),
            };
            (
                "Custom endpoint",
                "custom_http",
                auth_label,
                "Meridian will save the custom HTTP route exactly as configured here.",
            )
        }
        _ => (
            "Configured provider",
            "custom",
            "runtime-managed auth".to_string(),
            "Meridian will write the selected route into the runtime root.",
        ),
    }
}

fn prompt_provider_setup(
    provider_choice: &str,
    current_model: &str,
    current_codex_auth_source: &str,
    current_codex_auth_path: Option<String>,
    detailed_flow: bool,
) -> LoomResult<ProviderSetupSelection> {
    print_provider_branch_card(provider_choice, detailed_flow);
    match provider_choice {
        "loom_codex" => {
            if looks_remote_headless() {
                print_setup_note(
                    "Remote OAuth",
                    "This host appears to be headless or remote.\nKeep the Loom-managed auth path on this runtime, then finish device auth in your local browser when prompted.\nMeridian keeps the Loom-owned auth file separate from the shared operator login.",
                );
            }
            let manager_model = prompt_text("Manager model", current_model)?;
            let codex_auth_source = prompt_select(
                "Codex auth source",
                if current_codex_auth_source == "none" {
                    "loom"
                } else {
                    current_codex_auth_source
                },
                &[
                    PromptSelectOption {
                        value: "loom",
                        label: "Loom-managed account",
                        hint: "Use the runtime-owned Meridian auth file for this install.",
                    },
                    PromptSelectOption {
                        value: "cli",
                        label: "Shared operator account",
                        hint: "Reuse the shared auth.json path already present on this host.",
                    },
                    PromptSelectOption {
                        value: "path",
                        label: "Custom auth.json path",
                        hint: "Point Meridian at a specific Codex auth.json file.",
                    },
                ],
            )?;
            let codex_auth_path = match codex_auth_source.as_str() {
                "loom" => None,
                "cli" => None,
                _ => {
                    let hint = current_codex_auth_path.unwrap_or_else(|| {
                        default_codex_auth_path_hint()
                            .map(|path| path.display().to_string())
                            .unwrap_or_else(|_| "~/.meridian/auth/codex/auth.json".to_string())
                    });
                    Some(prompt_text("Custom Codex auth.json path", &hint)?)
                }
            };
            Ok(ProviderSetupSelection {
                manager_lane: "frontier".to_string(),
                manager_model,
                codex_auth_source,
                codex_auth_path,
                provider_config: None,
            })
        }
        "local_ollama" | "local_only" => {
            if provider_choice == "local_only" {
                print_setup_note(
                    "Local-only setup",
                    "Meridian will stay on the local inference path and skip remote provider setup for now.",
                );
            }
            let default_model = if current_model.trim().is_empty() {
                "qwen2.5:7b"
            } else {
                current_model
            };
            let manager_model = prompt_text("Local model", default_model)?;
            Ok(ProviderSetupSelection {
                manager_lane: "local".to_string(),
                manager_model,
                codex_auth_source: "none".to_string(),
                codex_auth_path: None,
                provider_config: None,
            })
        }
        "openai_compatible" => {
            let default_model = if current_model.trim().is_empty() {
                "gpt-5.4"
            } else {
                current_model
            };
            let manager_model = prompt_text("Remote model", default_model)?;
            let base_url = prompt_text(
                "OpenAI-compatible base URL",
                "https://api.openai.com/v1/chat/completions",
            )?;
            let env_var = prompt_text("Bearer token env var", "OPENAI_API_KEY")?;
            Ok(ProviderSetupSelection {
                manager_lane: "frontier".to_string(),
                manager_model: manager_model.clone(),
                codex_auth_source: "none".to_string(),
                codex_auth_path: None,
                provider_config: Some(OnboardProviderRouteConfig {
                    profile_name: "openai_default".to_string(),
                    kind: ProviderKind::OpenAiCompatible,
                    base_url,
                    default_model: manager_model,
                    auth: ProviderAuthMode::BearerEnv { env_var },
                    note: "seeded Meridian OpenAI-compatible route for manager reasoning"
                        .to_string(),
                    make_default: true,
                }),
            })
        }
        "custom_endpoint" => {
            let default_model = if current_model.trim().is_empty() {
                "gpt-5.4"
            } else {
                current_model
            };
            let manager_model = prompt_text("Remote model", default_model)?;
            let base_url = prompt_text(
                "Custom endpoint base URL",
                "https://api.example.test/v1/chat/completions",
            )?;
            let auth_mode = prompt_select(
                "Custom endpoint auth mode",
                "bearer_env",
                &[
                    PromptSelectOption {
                        value: "bearer_env",
                        label: "Bearer token from env",
                        hint: "Send Authorization: Bearer using an environment variable.",
                    },
                    PromptSelectOption {
                        value: "static_header_env",
                        label: "Static header from env",
                        hint:
                            "Attach a fixed header whose value comes from an environment variable.",
                    },
                    PromptSelectOption {
                        value: "none",
                        label: "No auth header",
                        hint:
                            "Only use this for trusted local gateways or pre-authenticated proxies.",
                    },
                ],
            )?;
            let auth = match auth_mode.as_str() {
                "none" => ProviderAuthMode::None,
                "static_header_env" => {
                    let header_name = prompt_text("Header name", "x-api-key")?;
                    let env_var = prompt_text("Header env var", "MERIDIAN_CUSTOM_LLM_KEY")?;
                    ProviderAuthMode::StaticHeaderEnv {
                        header_name,
                        env_var,
                    }
                }
                _ => {
                    let env_var = prompt_text("Bearer token env var", "MERIDIAN_CUSTOM_LLM_KEY")?;
                    ProviderAuthMode::BearerEnv { env_var }
                }
            };
            Ok(ProviderSetupSelection {
                manager_lane: "frontier".to_string(),
                manager_model: manager_model.clone(),
                codex_auth_source: "none".to_string(),
                codex_auth_path: None,
                provider_config: Some(OnboardProviderRouteConfig {
                    profile_name: "custom_endpoint".to_string(),
                    kind: ProviderKind::CustomEndpoint,
                    base_url,
                    default_model: manager_model,
                    auth,
                    note: "seeded Meridian custom endpoint route for manager reasoning".to_string(),
                    make_default: true,
                }),
            })
        }
        other => Err(format!("unsupported provider choice '{}'", other)),
    }
}

fn default_manager_lane(manifest: &OnboardManifest) -> String {
    let lane = manifest.manager_lane.trim();
    if lane.is_empty() {
        "frontier".to_string()
    } else {
        lane.to_string()
    }
}

fn default_manager_model(lane: &str, manifest: &OnboardManifest) -> String {
    let model = manifest.manager_model.trim();
    if !model.is_empty() {
        return model.to_string();
    }
    if lane.eq_ignore_ascii_case("local") {
        "qwen2.5:7b".to_string()
    } else {
        "gpt-5.4".to_string()
    }
}

fn manifest_codex_auth_selection(
    manifest: &OnboardManifest,
    lane: &str,
) -> (String, Option<String>) {
    if lane.eq_ignore_ascii_case("local") {
        return ("none".to_string(), None);
    }
    let source = match manifest.codex_auth_source.trim() {
        "" => "loom".to_string(),
        value => value.to_string(),
    };
    let path = trimmed_string_option(&manifest.codex_auth_path);
    (source, path)
}

fn current_codex_auth_selection(root: &Path) -> LoomResult<(String, Option<String>)> {
    let profiles = load_provider_profiles(Some(root))?;
    let manifest = load_onboard_manifest(root).ok();
    let profile = profiles
        .profiles
        .iter()
        .find(|candidate| candidate.name == "manager_frontier")
        .ok_or_else(|| "manager_frontier provider profile was not found".to_string())?;
    match &profile.auth {
        ProviderAuthMode::CodexAuthJson { path } => {
            let loom_path = default_codex_auth_path_hint()?.display().to_string();
            let cli_path = shared_codex_auth_path_hint()?.display().to_string();
            match path.as_deref() {
                None => {
                    let prefer_loom_path = manifest
                        .as_ref()
                        .map(|value| value.last_action.trim() == "initialized")
                        .unwrap_or(false);
                    if prefer_loom_path {
                        Ok(("loom".to_string(), Some(loom_path)))
                    } else {
                        Ok(("cli".to_string(), Some(cli_path)))
                    }
                }
                Some(raw) if auth_paths_match(raw, &loom_path) => {
                    Ok(("loom".to_string(), Some(loom_path)))
                }
                Some(raw) if auth_paths_match(raw, &cli_path) => {
                    Ok(("cli".to_string(), Some(cli_path)))
                }
                Some(raw) => Ok(("path".to_string(), Some(raw.trim().to_string()))),
            }
        }
        _ => Ok(("none".to_string(), None)),
    }
}

fn configured_manager_provider(root: &Path) -> LoomResult<ConfiguredManagerRoute> {
    let profiles = load_provider_profiles(Some(root))?;
    let configured_name = profiles
        .routing
        .agents
        .get("leviathann")
        .and_then(|policy| policy.profile_name.clone())
        .unwrap_or_else(|| profiles.default_profile_name.clone());
    let profile = profiles
        .profiles
        .iter()
        .find(|candidate| candidate.name == configured_name)
        .ok_or_else(|| {
            format!(
                "configured provider profile '{}' was not found",
                configured_name
            )
        })?;
    Ok(ConfiguredManagerRoute {
        profile_name: profile.name.clone(),
        profile_kind: profile.kind.clone(),
        endpoint: profile.base_url.clone(),
        model: profile.default_model.clone(),
        transport_kind: transport_kind_for_profile(&profile.kind).to_string(),
    })
}

fn normalize_codex_auth_selection(
    manager_lane: &str,
    codex_auth_source: &str,
    codex_auth_path: Option<String>,
) -> LoomResult<(String, Option<String>)> {
    if manager_lane.eq_ignore_ascii_case("local") {
        return Ok(("none".to_string(), None));
    }
    let source = if codex_auth_source.trim().is_empty() {
        "loom".to_string()
    } else {
        codex_auth_source.trim().to_ascii_lowercase()
    };
    let explicit_path = codex_auth_path.and_then(|value| trimmed_string_option(&value));
    match source.as_str() {
        "loom" | "none" => {
            let expected = default_codex_auth_path_hint()?.display().to_string();
            if let Some(raw) = explicit_path.as_deref() {
                if !auth_paths_match(raw, &expected) {
                    return Err(
                        "--codex-auth-source loom cannot be combined with a different --codex-auth-path; use --codex-auth-source path for a custom Loom account file"
                            .to_string(),
                    );
                }
            }
            Ok(("loom".to_string(), Some(expected)))
        }
        "cli" | "shared" => {
            let expected = shared_codex_auth_path_hint()?.display().to_string();
            if let Some(raw) = explicit_path.as_deref() {
                if !auth_paths_match(raw, &expected) {
                    return Err(
                        "--codex-auth-source cli cannot be combined with a different --codex-auth-path; use --codex-auth-source path for a custom shared auth file"
                            .to_string(),
                    );
                }
            }
            Ok(("cli".to_string(), Some(expected)))
        }
        "path" => Ok((
            "path".to_string(),
            Some(explicit_path.ok_or_else(|| {
                "--codex-auth-source path requires --codex-auth-path PATH".to_string()
            })?),
        )),
        other => Err(format!(
            "unsupported Codex auth source '{}'; expected 'loom', 'cli', or 'path'",
            other
        )),
    }
}

#[cfg(test)]
mod tests {
    use super::{
        auth_paths_match, build_next_steps, choice_matches, codex_detail_for_manager,
        manager_current_state_hint, normalize_choice_token, normalize_codex_auth_selection,
        panel_tone, provider_branch_story, provider_selection_details, render_stage_progress,
        PanelTone, PromptSelectOption, ProviderSetupSelection, SetupState,
    };
    use loom_core::provider_router::{
        OnboardProviderRouteConfig, ProviderAuthMode, ProviderAuthStatus, ProviderKind,
    };
    use std::path::Path;

    fn auth_status(
        profile_kind: ProviderKind,
        auth_mode: &str,
        env_var: Option<&str>,
        header_name: Option<&str>,
        credential_path: Option<&str>,
        ready: bool,
        detail: &str,
    ) -> ProviderAuthStatus {
        ProviderAuthStatus {
            profile_name: "manager".to_string(),
            profile_kind,
            auth_mode: auth_mode.to_string(),
            env_var: env_var.map(|value| value.to_string()),
            header_name: header_name.map(|value| value.to_string()),
            credential_path: credential_path.map(|value| value.to_string()),
            source: "test".to_string(),
            ready,
            detail: detail.to_string(),
        }
    }

    #[test]
    fn frontier_none_defaults_to_loom_managed_auth() {
        let (source, path) = normalize_codex_auth_selection("frontier", "none", None)
            .expect("frontier default should normalize");
        assert_eq!(source, "loom");
        assert!(path.is_some());
    }

    #[test]
    fn local_lane_keeps_codex_auth_disabled() {
        let (source, path) = normalize_codex_auth_selection("local", "none", None)
            .expect("local lane should disable codex auth");
        assert_eq!(source, "none");
        assert!(path.is_none());
    }

    #[test]
    fn codex_detail_defaults_to_auth_required_for_frontier_profiles() {
        assert_eq!(
            codex_detail_for_manager(Some(&ProviderKind::OpenAiCodex)),
            "Codex OAuth is not configured yet"
        );
    }

    #[test]
    fn codex_detail_stays_disabled_for_local_profiles() {
        assert_eq!(
            codex_detail_for_manager(Some(&ProviderKind::LocalOllama)),
            "current manager provider does not use Codex OAuth"
        );
    }

    #[test]
    fn choice_tokens_normalize_spacing_and_case() {
        assert_eq!(
            normalize_choice_token("OpenAI-compatible endpoint"),
            "openai compatible endpoint"
        );
        assert_eq!(normalize_choice_token("  Loom_Managed  "), "loom managed");
    }

    #[test]
    fn choice_match_accepts_human_label_or_internal_value() {
        let option = PromptSelectOption {
            value: "openai_compatible",
            label: "OpenAI-compatible endpoint",
            hint: "",
        };
        assert!(choice_matches(&option, "openai_compatible"));
        assert!(choice_matches(&option, "OpenAI compatible endpoint"));
        assert!(!choice_matches(&option, "local_ollama"));
    }

    #[test]
    fn current_state_hint_is_provider_specific_for_openai_env() {
        let hint = manager_current_state_hint(
            &SetupState::FreshNoAuth { provider_count: 1 },
            Some(&ProviderKind::OpenAiCompatible),
            false,
            "https://api.openai.com/v1/chat/completions",
            "gpt-5.4-mini",
            Some(&auth_status(
                ProviderKind::OpenAiCompatible,
                "bearer_env",
                Some("OPENAI_API_KEY"),
                Some("authorization"),
                None,
                false,
                "bearer token env OPENAI_API_KEY is missing",
            )),
        );
        assert!(hint.contains("OpenAI-compatible manager route is configured"));
        assert!(hint.contains("OPENAI_API_KEY is not set yet"));
        assert!(hint.contains("gpt-5.4-mini"));
        assert!(hint.contains("https://api.openai.com/v1/chat/completions"));
    }

    #[test]
    fn current_state_hint_surfaces_codex_ready_state() {
        let hint = manager_current_state_hint(
            &SetupState::FrontierAvailable {
                profiles: vec!["manager_frontier".to_string()],
                agent_count: 1,
            },
            Some(&ProviderKind::OpenAiCodex),
            true,
            "https://chatgpt.com/backend-api",
            "gpt-5.4",
            Some(&auth_status(
                ProviderKind::OpenAiCodex,
                "codex_auth_json",
                None,
                Some("authorization"),
                Some("/tmp/auth.json"),
                true,
                "Codex OAuth auth.json is ready",
            )),
        );
        assert!(hint.contains("Frontier manager route is ready"));
        assert!(hint.contains("Codex OAuth is available"));
        assert!(hint.contains("/tmp/auth.json"));
    }

    #[test]
    fn auth_path_matching_expands_relative_home_paths() {
        std::env::set_var("HOME", "/tmp/meridian-home");
        assert!(auth_paths_match(
            "~/.meridian/auth/codex/auth.json",
            "/tmp/meridian-home/.meridian/auth/codex/auth.json"
        ));
    }

    #[test]
    fn stage_progress_renders_simple_meter() {
        assert_eq!(render_stage_progress(1, 5), "[#----]");
        assert_eq!(render_stage_progress(3, 5), "[###--]");
        assert_eq!(render_stage_progress(5, 5), "[#####]");
    }

    #[test]
    fn provider_selection_details_surface_openai_env_requirement() {
        let selection = ProviderSetupSelection {
            manager_lane: "frontier".to_string(),
            manager_model: "gpt-5.4-mini".to_string(),
            codex_auth_source: "none".to_string(),
            codex_auth_path: None,
            provider_config: Some(OnboardProviderRouteConfig {
                profile_name: "openai_default".to_string(),
                kind: ProviderKind::OpenAiCompatible,
                base_url: "https://api.openai.com/v1/chat/completions".to_string(),
                default_model: "gpt-5.4-mini".to_string(),
                auth: ProviderAuthMode::BearerEnv {
                    env_var: "OPENAI_API_KEY".to_string(),
                },
                note: "test".to_string(),
                make_default: true,
            }),
        };
        let (provider, transport, auth, next) =
            provider_selection_details("openai_compatible", &selection);
        assert_eq!(provider, "OpenAI-compatible endpoint");
        assert_eq!(transport, "openai_rest");
        assert!(auth.contains("OPENAI_API_KEY"));
        assert!(next.contains("doctor"));
    }

    #[test]
    fn provider_branch_story_surfaces_openai_cutover_copy() {
        let (best_for, meridian_path, operator_step, after_write) =
            provider_branch_story("openai_compatible");
        assert!(best_for.contains("fastest remote cutover"));
        assert!(meridian_path.contains("chat-completions"));
        assert!(operator_step.contains("token env var"));
        assert!(after_write.contains("Codex device-auth"));
    }

    #[test]
    fn panel_tone_marks_action_required_surfaces_as_warning() {
        assert_eq!(
            panel_tone(
                "Current state",
                "Auth is action required before doctor turns green"
            ),
            PanelTone::Warning
        );
        assert_eq!(
            panel_tone("Finish line", "Runtime health is healthy"),
            PanelTone::Success
        );
    }

    #[test]
    fn next_steps_dedupe_doctor_when_auth_pending() {
        let steps = build_next_steps(
            Path::new("/tmp/loom"),
            false,
            "export OPENAI_API_KEY=... && loom doctor --root /tmp/loom --format human",
        );
        assert_eq!(steps.len(), 2);
        assert!(steps[0].contains("OPENAI_API_KEY"));
        assert!(steps[1].contains("--config-action modify"));
    }

    #[test]
    fn next_steps_keep_doctor_and_service_status_when_ready() {
        let steps = build_next_steps(
            Path::new("/tmp/loom"),
            true,
            "loom service status --root /tmp/loom",
        );
        assert_eq!(steps.len(), 3);
        assert!(steps[0].contains("loom doctor"));
        assert!(steps[1].contains("loom service status"));
        assert!(steps[2].contains("--config-action modify"));
    }
}

fn codex_detail_for_manager(manager_profile_kind: Option<&ProviderKind>) -> String {
    if matches!(manager_profile_kind, Some(ProviderKind::OpenAiCodex)) {
        "Codex OAuth is not configured yet".to_string()
    } else {
        "current manager provider does not use Codex OAuth".to_string()
    }
}

fn auth_paths_match(raw: &str, expected: &str) -> bool {
    let normalized_expected = expected.trim();
    expand_auth_path(raw)
        .map(|path| path.display().to_string())
        .map(|path| path == normalized_expected)
        .unwrap_or_else(|| raw.trim() == normalized_expected)
}

fn expand_auth_path(raw: &str) -> Option<PathBuf> {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return None;
    }
    if trimmed == "~" {
        return env::var("HOME").ok().map(PathBuf::from);
    }
    if let Some(rest) = trimmed.strip_prefix("~/") {
        return env::var("HOME")
            .ok()
            .map(PathBuf::from)
            .map(|home| home.join(rest));
    }
    let path = PathBuf::from(trimmed);
    if path.is_absolute() {
        return Some(path);
    }
    env::var("HOME")
        .ok()
        .map(|home| PathBuf::from(home).join(path))
}

fn looks_remote_headless() -> bool {
    env::var("SSH_CONNECTION")
        .ok()
        .filter(|value| !value.trim().is_empty())
        .is_some()
        || env::var("SSH_CLIENT")
            .ok()
            .filter(|value| !value.trim().is_empty())
            .is_some()
        || env::var("DISPLAY")
            .ok()
            .map(|value| value.trim().is_empty())
            .unwrap_or(true)
}

fn transport_kind_for_profile(kind: &ProviderKind) -> &'static str {
    match kind {
        ProviderKind::LocalOllama => "ollama_local",
        ProviderKind::OpenAiCompatible => "openai_rest",
        ProviderKind::OpenAiCodex => "codex_session",
        ProviderKind::CustomEndpoint => "custom_http",
    }
}

fn trimmed_string_option(raw: &str) -> Option<String> {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        None
    } else {
        Some(trimmed.to_string())
    }
}

fn print_setup_stage(step: usize, total: usize, title: &str, detail: &str) {
    let progress = render_stage_progress(step, total);
    print_setup_note(
        &format!("Stage {} of {}", step, total),
        &format!("{}\nProgress: {}", title, progress),
    );
    print_setup_note("What happens here", detail);
}

fn render_stage_progress(step: usize, total: usize) -> String {
    let safe_total = total.max(1);
    let safe_step = step.clamp(1, safe_total);
    format!(
        "[{}{}]",
        "#".repeat(safe_step),
        "-".repeat(safe_total.saturating_sub(safe_step))
    )
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum PanelTone {
    Info,
    Success,
    Warning,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum ProgressRenderMode {
    Animated,
    Transcript,
    Silent,
}

fn print_setup_note(title: &str, body: &str) {
    let lines = body
        .lines()
        .map(str::trim_end)
        .filter(|line| !line.is_empty())
        .collect::<Vec<_>>();
    let width = lines
        .iter()
        .map(|line| line.len())
        .chain(std::iter::once(title.len()))
        .max()
        .unwrap_or(0)
        .max(24);
    let tone = panel_tone(title, body);
    let border = format!("+{}+", "-".repeat(width + 2));
    let mut block = Vec::new();
    block.push(style_panel_border(&border, tone));
    block.push(style_panel_title_line(
        &format!("| {:width$} |", title, width = width),
        tone,
    ));
    block.push(style_panel_border(
        &format!("| {:width$} |", "", width = width),
        tone,
    ));
    for line in lines {
        block.push(style_panel_body_line(
            &format!("| {:width$} |", line, width = width),
            tone,
        ));
    }
    block.push(style_panel_border(&border, tone));
    print_human(&(block.join("\n") + "\n\n"));
}

fn print_progress_status(marker: &str, title: &str, detail: Option<&str>) {
    print_human(&format!("{} {}\n", style_progress_marker(marker), title));
    if let Some(detail) = detail {
        if !detail.trim().is_empty() {
            print_human(&format!("     {}\n", style_progress_detail(detail, marker)));
        }
    }
    print_human("\n");
}

fn run_with_spinner<T, F>(
    mode: ProgressRenderMode,
    title: &str,
    detail: Option<&str>,
    action: F,
) -> LoomResult<T>
where
    F: FnOnce() -> LoomResult<T>,
{
    match mode {
        ProgressRenderMode::Animated if rich_terminal_enabled() => {
            let started_at = Instant::now();
            if let Some(detail) = detail {
                if !detail.trim().is_empty() {
                    print_human(&format!("     {}\n", style_progress_detail(detail, "..")));
                }
            }
            let running = Arc::new(AtomicBool::new(true));
            let title_string = title.to_string();
            let running_worker = Arc::clone(&running);
            let spinner_thread = thread::spawn(move || {
                let frames = ["[|]", "[/]", "[-]", "[\\]"];
                let mut frame_index = 0usize;
                while running_worker.load(Ordering::Relaxed) {
                    let frame = style_progress_marker(frames[frame_index]);
                    print!("\r{} {}", frame, title_string);
                    let _ = io::stdout().flush();
                    thread::sleep(Duration::from_millis(90));
                    frame_index = (frame_index + 1) % frames.len();
                }
            });
            let result = action();
            let min_visible = Duration::from_millis(240);
            if started_at.elapsed() < min_visible {
                thread::sleep(min_visible - started_at.elapsed());
            }
            running.store(false, Ordering::Relaxed);
            let _ = spinner_thread.join();
            print!("\r\x1b[2K");
            let _ = io::stdout().flush();
            result
        }
        ProgressRenderMode::Animated | ProgressRenderMode::Transcript => {
            print_progress_transcript_start(title, detail);
            action()
        }
        ProgressRenderMode::Silent => action(),
    }
}

fn print_progress_transcript_start(title: &str, detail: Option<&str>) {
    print_human(&format!("{} {}\n", style_progress_marker(">>"), title));
    if let Some(detail) = detail {
        if !detail.trim().is_empty() {
            print_human(&format!("     {}\n", style_progress_detail(detail, ">>")));
        }
    }
    print_human("\n");
}

fn render_numbered_steps(steps: &[String]) -> String {
    steps
        .iter()
        .enumerate()
        .map(|(index, step)| format!("{}. {}", index + 1, step))
        .collect::<Vec<_>>()
        .join("\n")
}

fn build_next_steps(root: &Path, manager_auth_ready: bool, manager_next_step: &str) -> Vec<String> {
    let doctor_step = format!("loom doctor --root {} --format human", root.display());
    let modify_step = format!(
        "loom onboard --root {} --format human --config-action modify",
        root.display()
    );
    let mut steps = Vec::new();
    if manager_auth_ready {
        steps.push(doctor_step.clone());
        steps.push(manager_next_step.to_string());
    } else {
        steps.push(manager_next_step.to_string());
        if !manager_next_step.contains("loom doctor") {
            steps.push(doctor_step.clone());
        }
    }
    steps.push(modify_step);
    dedupe_steps(steps)
}

fn dedupe_steps(steps: Vec<String>) -> Vec<String> {
    let mut unique = Vec::new();
    for step in steps {
        if !unique.contains(&step) {
            unique.push(step);
        }
    }
    unique
}

fn print_provider_branch_card(provider_choice: &str, detailed_flow: bool) {
    let (best_for, meridian_path, operator_step, after_write) =
        provider_branch_story(provider_choice);
    let title = if detailed_flow {
        "Manual provider branch"
    } else {
        "QuickStart provider branch"
    };
    let mode_fit = if detailed_flow {
        "Manual fit:       Meridian will keep this provider selection, then hand you every gateway, Telegram, daemon, and defaults decision before the root is written."
    } else {
        "QuickStart fit:   Meridian wires this provider now and keeps the local edge, recurring jobs, and runtime defaults on the fast path."
    };
    print_setup_note(
        title,
        &format!(
            "Best for:        {}\n\
             {}\n\
             Meridian path:   {}\n\
             Operator step:   {}\n\
             After write:     {}",
            best_for, mode_fit, meridian_path, operator_step, after_write
        ),
    );
}

fn provider_branch_story(
    provider_choice: &str,
) -> (&'static str, &'static str, &'static str, &'static str) {
    match provider_choice {
        "loom_codex" => (
            "frontier-first installs that want a Meridian-owned auth boundary from day one",
            "dedicated Codex session routing with Loom-managed or explicitly chosen auth.json ownership",
            "choose whether Meridian should own the auth file, reuse the shared CLI account, or point at a custom auth.json",
            "doctor expects a live auth.json before the frontier lane turns green",
        ),
        "local_ollama" => (
            "operators who want local inference now without any remote dependency",
            "bind Leviathann to the local Ollama lane while keeping the rest of the runtime scaffold intact",
            "point Meridian at the local model already running on this host",
            "doctor verifies the local model lane and keeps the remote auth boundary out of scope",
        ),
        "local_only" => (
            "staging the runtime today and adding a remote provider later",
            "keep the runtime entirely local and skip remote provider setup for this pass",
            "finish the local edge now, then rerun onboarding when the remote route is ready",
            "Meridian lands in a local-only runtime state with a clean follow-up path back into onboarding",
        ),
        "openai_compatible" => (
            "teams that already have a bearer-token provider and want the fastest remote cutover",
            "standard chat-completions routing with an environment variable the operator controls",
            "set the endpoint, choose the model, and export the required token env var before doctor turns green",
            "doctor checks the env var and remote route without asking for a Codex device-auth login",
        ),
        "custom_endpoint" => (
            "proxies, gateways, and non-standard auth headers that still need a governed HTTP route",
            "custom HTTP routing with explicit auth mode selection and no hidden provider assumptions",
            "define the base URL and tell Meridian exactly how credentials should be attached",
            "doctor verifies the explicit auth attachment rules exactly as written into the runtime root",
        ),
        _ => (
            "a custom provider path",
            "write the selected route into the runtime root",
            "finish the provider prompts and let doctor verify the route afterwards",
            "the runtime root keeps the selected route and waits for doctor to confirm it",
        ),
    }
}

fn panel_tone(title: &str, body: &str) -> PanelTone {
    let title = title.to_ascii_lowercase();
    let body = body.to_ascii_lowercase();
    if title.contains("security")
        || body.contains("action required")
        || body.contains("not ready")
        || body.contains("failed")
        || body.contains("attention")
    {
        PanelTone::Warning
    } else if title.contains("finish line") || title.contains("ready to launch") {
        PanelTone::Success
    } else {
        PanelTone::Info
    }
}

fn rich_terminal_enabled() -> bool {
    std::io::stdout().is_terminal() && env::var_os("NO_COLOR").is_none()
}

fn style_progress_marker(marker: &str) -> String {
    match marker {
        "ok" => paint(marker, "1;92"),
        "!!" => paint(marker, "1;93"),
        ">>" => paint(marker, "1;94"),
        ".." | "[|]" | "[/]" | "[-]" | "[\\]" => paint(marker, "1;96"),
        "--" => paint(marker, "2;37"),
        _ => marker.to_string(),
    }
}

fn style_progress_detail(detail: &str, marker: &str) -> String {
    match marker {
        "ok" => paint(detail, "0;92"),
        "!!" => paint(detail, "0;93"),
        ">>" => paint(detail, "0;94"),
        _ => paint(detail, "0;37"),
    }
}

fn style_panel_border(line: &str, tone: PanelTone) -> String {
    match tone {
        PanelTone::Info => paint(line, "2;36"),
        PanelTone::Success => paint(line, "2;92"),
        PanelTone::Warning => paint(line, "2;93"),
    }
}

fn style_panel_title_line(line: &str, tone: PanelTone) -> String {
    match tone {
        PanelTone::Info => paint(line, "1;96"),
        PanelTone::Success => paint(line, "1;92"),
        PanelTone::Warning => paint(line, "1;93"),
    }
}

fn style_panel_body_line(line: &str, tone: PanelTone) -> String {
    match tone {
        PanelTone::Info => paint(line, "0;37"),
        PanelTone::Success => paint(line, "0;97"),
        PanelTone::Warning => paint(line, "0;93"),
    }
}

fn paint(text: &str, style: &str) -> String {
    if rich_terminal_enabled() {
        format!("\x1b[{}m{}\x1b[0m", style, text)
    } else {
        text.to_string()
    }
}

fn prompt_text(label: &str, default: &str) -> LoomResult<String> {
    print_human(&format!("{label}\n"));
    if !default.trim().is_empty() {
        print_human(&format!("default: {}\n", default));
    }
    print!("> ");
    io::stdout().flush().map_err(|error| error.to_string())?;
    let mut input = String::new();
    io::stdin()
        .read_line(&mut input)
        .map_err(|error| error.to_string())?;
    let trimmed = input.trim();
    if trimmed.is_empty() {
        Ok(default.to_string())
    } else {
        Ok(trimmed.to_string())
    }
}

fn prompt_select(
    label: &str,
    default: &str,
    options: &[PromptSelectOption<'_>],
) -> LoomResult<String> {
    let default_index = options
        .iter()
        .position(|option| choice_matches(option, default))
        .unwrap_or(0);
    print_human(&format!("{label}\n"));
    for (index, option) in options.iter().enumerate() {
        let default_marker = if index == default_index {
            " [default]"
        } else {
            ""
        };
        print_human(&format!(
            "  {}. {}{}\n",
            index + 1,
            option.label,
            default_marker
        ));
        if !option.hint.trim().is_empty() {
            print_human(&format!("     {}\n", option.hint));
        }
    }
    print_human("Enter a number or type the label. Press Enter to keep the default.\n");
    loop {
        print!("choice [{}]: ", default_index + 1);
        io::stdout().flush().map_err(|error| error.to_string())?;
        let mut input = String::new();
        io::stdin()
            .read_line(&mut input)
            .map_err(|error| error.to_string())?;
        let trimmed = input.trim();
        if trimmed.is_empty() {
            return Ok(options[default_index].value.to_string());
        }
        if let Ok(index) = trimmed.parse::<usize>() {
            if let Some(option) = index.checked_sub(1).and_then(|value| options.get(value)) {
                return Ok(option.value.to_string());
            }
        }
        if let Some(option) = options
            .iter()
            .find(|option| choice_matches(option, trimmed))
        {
            return Ok(option.value.to_string());
        }
        let expected = options
            .iter()
            .enumerate()
            .map(|(index, option)| format!("{}={}", index + 1, option.value))
            .collect::<Vec<_>>()
            .join(", ");
        eprintln!("invalid value '{}'; expected one of {}", trimmed, expected);
    }
}

fn prompt_choice(label: &str, default: &str, allowed: &[&str]) -> LoomResult<String> {
    let options = allowed
        .iter()
        .map(|value| PromptSelectOption {
            value,
            label: humanize_choice_value(value),
            hint: "",
        })
        .collect::<Vec<_>>();
    prompt_select(label, default, &options)
}

fn prompt_bool(label: &str, default: bool) -> LoomResult<bool> {
    let suffix = if default { "[Y/n]" } else { "[y/N]" };
    loop {
        print_human(&format!("{label} {suffix}\n"));
        print!("> ");
        io::stdout().flush().map_err(|error| error.to_string())?;
        let mut input = String::new();
        io::stdin()
            .read_line(&mut input)
            .map_err(|error| error.to_string())?;
        let trimmed = input.trim();
        if trimmed.is_empty() {
            return Ok(default);
        }
        match parse_bool_flag(label, trimmed) {
            Ok(parsed) => return Ok(parsed),
            Err(error) => eprintln!("{}", error),
        }
    }
}

fn choice_matches(option: &PromptSelectOption<'_>, raw: &str) -> bool {
    normalize_choice_token(option.value) == normalize_choice_token(raw)
        || normalize_choice_token(option.label) == normalize_choice_token(raw)
}

fn normalize_choice_token(raw: &str) -> String {
    raw.trim()
        .to_ascii_lowercase()
        .chars()
        .map(|ch| if ch.is_ascii_alphanumeric() { ch } else { ' ' })
        .collect::<String>()
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}

fn humanize_choice_value<'a>(raw: &'a str) -> &'a str {
    match raw {
        "keep" => "Keep current setup",
        "modify" => "Adjust current setup",
        "reset" => "Reset and rebuild",
        "quickstart" => "QuickStart",
        "manual" => "Manual setup",
        "loom_codex" => "Loom-managed Codex OAuth",
        "local_ollama" => "Local Ollama",
        "openai_compatible" => "OpenAI-compatible endpoint",
        "custom_endpoint" => "Custom endpoint",
        "local_only" => "Local-only for now",
        "loopback" => "Loopback only",
        "all" => "All interfaces",
        "token" => "Token protected",
        "none" => "No auth",
        "off" => "Off",
        "on" => "On",
        "supervisor" => "Supervisor",
        "npm" => "npm",
        "pnpm" => "pnpm",
        "bun" => "bun",
        "loom" => "Loom-managed account",
        "cli" => "Shared CLI account",
        "path" => "Custom auth path",
        "bearer_env" => "Bearer token from env",
        "static_header_env" => "Static header from env",
        _ => raw,
    }
}

fn parse_bool_flag(label: &str, raw: &str) -> LoomResult<bool> {
    match raw.trim().to_ascii_lowercase().as_str() {
        "1" | "true" | "yes" | "y" | "on" | "enabled" => Ok(true),
        "0" | "false" | "no" | "n" | "off" | "disabled" => Ok(false),
        _ => Err(format!("{} expects yes/no/true/false", label)),
    }
}

fn parse_u16(label: &str, raw: &str) -> LoomResult<u16> {
    raw.trim()
        .parse::<u16>()
        .map_err(|error| format!("{} expects a valid u16: {}", label, error))
}

fn current_unix() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

fn route_json(route: &loom_core::provider_router::ResolvedProviderRoute) -> Value {
    json!({
        "profile": route.profile_name,
        "kind": route.profile_kind.label(),
        "endpoint": route.endpoint_url.as_str(),
        "model": route.model,
        "matched_rule": route.matched_rule,
    })
}

fn configured_route_json(route: &ConfiguredManagerRoute) -> Value {
    json!({
        "profile": route.profile_name,
        "kind": route.profile_kind.label(),
        "endpoint": route.endpoint,
        "model": route.model,
        "transport_kind": route.transport_kind,
        "matched_rule": "configured",
    })
}

fn manager_current_state_hint(
    setup_state: &SetupState,
    manager_profile_kind: Option<&ProviderKind>,
    manager_route_ready: bool,
    manager_endpoint: &str,
    manager_model: &str,
    manager_auth_status: Option<&loom_core::provider_router::ProviderAuthStatus>,
) -> String {
    let fallback = onboard_path_hint(setup_state);
    let Some(kind) = manager_auth_status
        .map(|status| &status.profile_kind)
        .or(manager_profile_kind)
    else {
        return fallback;
    };
    let endpoint =
        if manager_endpoint.trim().is_empty() || manager_endpoint == "(pending provider setup)" {
            None
        } else {
            Some(manager_endpoint.trim())
        };
    let model = if manager_model.trim().is_empty() || manager_model == "(pending provider setup)" {
        None
    } else {
        Some(manager_model.trim())
    };

    let endpoint_line = endpoint
        .map(|value| format!("\n  Endpoint:           {}", value))
        .unwrap_or_default();
    let model_line = model
        .map(|value| format!("\n  Model:              {}", value))
        .unwrap_or_default();

    match kind {
        ProviderKind::OpenAiCompatible => {
            let Some(status) = manager_auth_status else {
                return fallback;
            };
            let env_var = status.env_var.as_deref().unwrap_or("OPENAI_API_KEY");
            if status.ready && manager_route_ready {
                format!(
                    "OpenAI-compatible manager route is ready.{}{}\n  Auth:               bearer token loaded from {}",
                    endpoint_line, model_line, env_var
                )
            } else {
                format!(
                    "OpenAI-compatible manager route is configured, but {} is not set yet.{}{}\n  Detail:             {}",
                    env_var, endpoint_line, model_line, status.detail
                )
            }
        }
        ProviderKind::CustomEndpoint => {
            let Some(status) = manager_auth_status else {
                return fallback;
            };
            let env_var = status
                .env_var
                .as_deref()
                .unwrap_or("MERIDIAN_PROVIDER_TOKEN");
            let header_name = status.header_name.as_deref().unwrap_or("authorization");
            if status.ready && manager_route_ready {
                format!(
                    "Custom manager endpoint is ready.{}{}\n  Auth:               {} from {}",
                    endpoint_line, model_line, header_name, env_var
                )
            } else {
                format!(
                    "Custom manager endpoint is configured, but {} is not set yet.{}{}\n  Detail:             {}",
                    env_var, endpoint_line, model_line, status.detail
                )
            }
        }
        ProviderKind::OpenAiCodex => {
            let Some(status) = manager_auth_status else {
                return fallback;
            };
            let identity_hint = status
                .credential_path
                .as_deref()
                .map(|path| format!("\n  Credentials:        {}", path))
                .unwrap_or_default();
            if status.ready && manager_route_ready {
                format!(
                    "Frontier manager route is ready.{}{}\n  Auth:               Codex OAuth is available{}",
                    endpoint_line, model_line, identity_hint
                )
            } else {
                format!(
                    "Frontier manager route is configured, but Codex OAuth is not ready yet.{}{}\n  Detail:             {}{}",
                    endpoint_line, model_line, status.detail, identity_hint
                )
            }
        }
        ProviderKind::LocalOllama => {
            if manager_route_ready {
                format!(
                    "Local Ollama manager route is ready.{}{}\n  Auth:               no external credentials required",
                    endpoint_line, model_line
                )
            } else {
                format!(
                    "Local Ollama manager route is configured, but the local endpoint has not come up yet.{}{}",
                    endpoint_line, model_line
                )
            }
        }
    }
}

fn print_onboard_help() {
    print_human(
        "Meridian Loom // ONBOARD HELP
================================
USAGE: loom onboard [OPTIONS]

PURPOSE:
  Configure a Loom runtime root, choose a manager provider, and materialize
  the local runtime state Meridian expects.

OPTIONS:
  --root PATH                 Runtime root to initialize or modify.
  --format human|json         Output format. Human becomes interactive on a TTY.
  --non-interactive           Skip prompts and apply CLI flags plus safe defaults.
  --config-action ACTION      keep | modify | reset
  --manager-lane LANE         frontier | local
  --manager-model MODEL       Manager model alias or provider-native name.
  --codex-auth-source SRC     loom | cli | path | none
  --codex-auth-path PATH      Custom auth.json path when using path mode.
  --gateway-bind MODE         loopback | all
  --gateway-port PORT         Gateway port.
  --gateway-auth-mode MODE    token | none
  --gateway-token-env NAME    Gateway token environment variable.
  --tailscale-mode MODE       off | on
  --start-daemon              Start the supervisor daemon after setup when enabled.
  --skip-health-check         Skip the post-setup health check.

NOTES:
  - Interactive setup offers QuickStart and Manual paths.
  - Provider selection and model selection are separate.
  - Loom-managed OAuth stays under the runtime-owned auth path.
  - Non-interactive onboarding still writes real runtime state.
",
    );
}

fn start_supervisor_daemon(root: &Path, kernel_path: Option<&str>) -> LoomResult<Value> {
    let exe = env::current_exe().map_err(|error| error.to_string())?;
    let mut command = Command::new(exe);
    command
        .arg("supervisor")
        .arg("daemon")
        .arg("start")
        .arg("--root")
        .arg(root)
        .arg("--format")
        .arg("json");
    if let Some(kernel_path) = kernel_path {
        command.arg("--kernel-path").arg(kernel_path);
    }
    let output = command.output().map_err(|error| error.to_string())?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
        let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
        return Err(if !stderr.is_empty() { stderr } else { stdout });
    }
    serde_json::from_slice::<Value>(&output.stdout).map_err(|error| error.to_string())
}

fn daemon_state_from_snapshot(snapshot: &Value) -> String {
    if snapshot
        .get("running")
        .and_then(Value::as_bool)
        .unwrap_or(false)
    {
        "running".to_string()
    } else {
        snapshot
            .get("status")
            .and_then(Value::as_str)
            .unwrap_or("configured")
            .to_string()
    }
}

fn render_daemon_summary(snapshot: &Value) -> String {
    let status = daemon_state_from_snapshot(snapshot);
    let pid = snapshot
        .get("pid")
        .and_then(Value::as_u64)
        .map(|pid| pid.to_string())
        .unwrap_or_else(|| "unknown".to_string());
    format!("supervisor {} pid={}", status, pid)
}

fn current_unix_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}
