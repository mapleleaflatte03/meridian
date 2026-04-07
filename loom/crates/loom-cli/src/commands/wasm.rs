use crate::*;

pub(crate) fn handle_wasm_limits(args: &[String]) -> LoomResult<()> {
    let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
    let raw = if let Some(config_path) = take_value(args, "--config-file") {
        std::fs::read_to_string(&config_path)
            .map_err(|error| format!("failed to read {}: {}", config_path, error))?
    } else {
        String::new()
    };
    let limits = if raw.is_empty() {
        default_limits()
    } else {
        parse_wasm_limits_toml(&raw)?
    };
    if let Err(errors) = validate_limits(&limits) {
        return Err(format!("invalid wasm limits: {}", errors.join("; ")));
    }
    if format == "json" {
        print!("{}", render_limits_json(&limits));
    } else {
        print_human(&render_limits_human(&limits));
    }
    Ok(())
}

pub(crate) fn handle_wasm_profile(args: &[String]) -> LoomResult<()> {
    if args.get(1).map(String::as_str) != Some("show") {
        return Err("wasm profile supports 'show'".to_string());
    }
    let profile_name = take_value(args, "--profile").unwrap_or_else(|| "standard".to_string());
    let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
    let profile = profile_defaults_map()
        .remove(&profile_name)
        .ok_or_else(|| format!("unknown wasm profile '{}'", profile_name))?;
    if format == "json" {
        print!("{}", render_pooling_config_json(&profile));
    } else {
        print_human(&render_pooling_config_human(&profile));
    }
    Ok(())
}

pub(crate) fn handle_wasm_host(args: &[String]) -> LoomResult<()> {
    if args.get(1).map(String::as_str) != Some("show") {
        return Err("wasm host supports 'show'".to_string());
    }
    let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
    let backend = match take_value(args, "--backend")
        .unwrap_or_else(|| "preview_only".to_string())
        .as_str()
    {
        "preview_only" => HostBackend::PreviewOnly,
        "wasmtime_ready" => HostBackend::WasmtimeReady,
        other => return Err(format!("unknown wasm host backend '{}'", other)),
    };
    let profile_name = take_value(args, "--profile").unwrap_or_else(|| "standard".to_string());
    let profile = match profile_name.as_str() {
        "minimal" => PoolingProfile::Minimal,
        "standard" => PoolingProfile::Standard,
        "heavy" => PoolingProfile::Heavy,
        "custom" => PoolingProfile::Custom,
        other => return Err(format!("unknown wasm pooling profile '{}'", other)),
    };
    let raw = if let Some(config_path) = take_value(args, "--config-file") {
        std::fs::read_to_string(&config_path)
            .map_err(|error| format!("failed to read {}: {}", config_path, error))?
    } else {
        String::new()
    };
    let limits = if raw.is_empty() {
        default_limits()
    } else {
        parse_wasm_limits_toml(&raw)?
    };
    let config = WasmHostBuilder::new()
        .with_profile_name(format!("host/{}", profile_name))
        .with_backend(backend)
        .with_pooling_profile(profile)
        .with_store_limits(limits)
        .build()
        .map_err(|errors| format!("invalid wasm host config: {}", errors.join("; ")))?;
    if format == "json" {
        print!("{}", render_host_config_json(&config));
    } else {
        print_human(&render_host_config_human(&config));
    }
    Ok(())
}

pub(crate) fn handle_wasm_run(args: &[String]) -> LoomResult<()> {
    let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
    let backend = match take_value(args, "--backend")
        .unwrap_or_else(|| "wasmtime_ready".to_string())
        .as_str()
    {
        "preview_only" => HostBackend::PreviewOnly,
        "wasmtime_ready" => HostBackend::WasmtimeReady,
        other => return Err(format!("unknown wasm host backend '{}'", other)),
    };
    let profile_name = take_value(args, "--profile").unwrap_or_else(|| "standard".to_string());
    let profile = match profile_name.as_str() {
        "minimal" => PoolingProfile::Minimal,
        "standard" => PoolingProfile::Standard,
        "heavy" => PoolingProfile::Heavy,
        "custom" => PoolingProfile::Custom,
        other => return Err(format!("unknown wasm pooling profile '{}'", other)),
    };
    let raw = if let Some(config_path) = take_value(args, "--config-file") {
        std::fs::read_to_string(&config_path)
            .map_err(|error| format!("failed to read {}: {}", config_path, error))?
    } else {
        String::new()
    };
    let limits = if raw.is_empty() {
        default_limits()
    } else {
        parse_wasm_limits_toml(&raw)?
    };
    let config = WasmHostBuilder::new()
        .with_profile_name(format!("host/{}", profile_name))
        .with_backend(backend)
        .with_pooling_profile(profile)
        .with_store_limits(limits)
        .build()
        .map_err(|errors| format!("invalid wasm host config: {}", errors.join("; ")))?;
    let module_source =
        take_value(args, "--module").unwrap_or_else(|| "builtin:minimal".to_string());
    let source = if module_source == "builtin:minimal" {
        WasmGuestSource::WasmBytes {
            name: "builtin:minimal".to_string(),
            bytes: builtin_minimal_wasm_module(),
        }
    } else {
        WasmGuestSource::WasmBytes {
            name: module_source.clone(),
            bytes: std::fs::read(&module_source)
                .map_err(|error| format!("failed to read {}: {}", module_source, error))?,
        }
    };
    let entrypoint = take_value(args, "--entrypoint").unwrap_or_else(|| "run".to_string());
    let entrypoint_args = take_value(args, "--entrypoint-arg")
        .map(|raw| {
            raw.parse::<i32>()
                .map(|value| vec![value])
                .map_err(|error| format!("invalid --entrypoint-arg '{}': {}", raw, error))
        })
        .transpose()?
        .unwrap_or_default();
    let fuel_budget = take_value(args, "--fuel-budget")
        .map(|raw| {
            raw.parse::<u64>()
                .map_err(|error| format!("invalid --fuel-budget '{}': {}", raw, error))
        })
        .transpose()?
        .unwrap_or(100_000);
    let result = run_wasm_guest(&WasmExecutionRequest {
        host: config,
        source,
        entrypoint,
        entrypoint_args,
        memory_probe: None,
        fuel_budget,
    })?;
    if format == "json" {
        print!("{}", render_wasm_run_json(&result));
    } else {
        print_human(&render_wasm_run_human(&result));
    }
    Ok(())
}

pub(crate) fn handle_wasm(args: &[String]) -> LoomResult<()> {
    match args.first().map(String::as_str) {
        Some("limits") => handle_wasm_limits(args),
        Some("profile") => handle_wasm_profile(args),
        Some("host") => handle_wasm_host(args),
        Some("run") => handle_wasm_run(args),
        _ => Err("wasm supports 'limits', 'profile show', 'host show', and 'run'".to_string()),
    }
}

pub(crate) fn render_wasm_run_human(result: &loom_core::wasm_host::WasmExecutionResult) -> String {
    let mut out = format!(
        "Meridian Loom // WASM RUN\n==========================\nphase:       experimental local guest lane\nboundary:    local Wasmtime execution is real; hosted capability runtime is not\n\nRuntime\n=======\nmodule:      {}\nentrypoint:  {}\nhost_backend:{}\nruntime_path:{}\nprofile:     {}\nentrypoint_result: {}\nstore_limit: {}\npooling:     {}\n",
        result.module_name,
        result.entrypoint,
        result.host_backend,
        result.runtime_path,
        result.host_profile_name,
        result
            .entrypoint_result
            .map(|value| value.to_string())
            .unwrap_or_else(|| "(none)".to_string()),
        result.store_memory_limit_bytes,
        result.pooling_profile,
    );
    if let Some(export_name) = result.memory_probe_export.as_ref() {
        out.push_str(&format!(
            "memory_probe:{} => {} pages_after={}\n",
            export_name,
            result
                .memory_probe_result
                .map(|value| value.to_string())
                .unwrap_or_else(|| "(none)".to_string()),
            result
                .memory_pages_after
                .map(|value| value.to_string())
                .unwrap_or_else(|| "(unknown)".to_string()),
        ));
    }
    out.push_str("\nHost hints\n==========\n");
    for (key, value) in &result.host_hints {
        out.push_str(&format!("{:<18} {}\n", format!("{}:", key), value));
    }
    out.push_str("\nNotes\n=====\n");
    for note in &result.notes {
        out.push_str(&format!("- {}\n", note));
    }
    out
}

pub(crate) fn render_wasm_run_json(result: &loom_core::wasm_host::WasmExecutionResult) -> String {
    let host_hints = result
        .host_hints
        .iter()
        .map(|(key, value)| format!("    {}: {}", json_string(key), json_string(value)))
        .collect::<Vec<_>>()
        .join(",\n");
    let notes = result
        .notes
        .iter()
        .map(|note| format!("    {}", json_string(note)))
        .collect::<Vec<_>>()
        .join(",\n");
    format!(
        "{{\n  \"status\": \"wasm_guest_executed\",\n  \"module_name\": {},\n  \"entrypoint\": {},\n  \"entrypoint_result\": {},\n  \"host_backend\": {},\n  \"host_profile_name\": {},\n  \"runtime_path\": {},\n  \"memory_probe_export\": {},\n  \"memory_probe_result\": {},\n  \"memory_pages_after\": {},\n  \"store_memory_limit_bytes\": {},\n  \"pooling_profile\": {},\n  \"host_hints\": {{\n{}\n  }},\n  \"notes\": [\n{}\n  ]\n}}\n",
        json_string(&result.module_name),
        json_string(&result.entrypoint),
        result
            .entrypoint_result
            .map(|value| value.to_string())
            .unwrap_or_else(|| "null".to_string()),
        json_string(&result.host_backend),
        json_string(&result.host_profile_name),
        json_string(&result.runtime_path),
        result
            .memory_probe_export
            .as_ref()
            .map(|value| json_string(value))
            .unwrap_or_else(|| "null".to_string()),
        result
            .memory_probe_result
            .map(|value| value.to_string())
            .unwrap_or_else(|| "null".to_string()),
        result
            .memory_pages_after
            .map(|value| value.to_string())
            .unwrap_or_else(|| "null".to_string()),
        result.store_memory_limit_bytes,
        json_string(&result.pooling_profile),
        host_hints,
        notes,
    )
}

pub(crate) fn builtin_minimal_wasm_module() -> Vec<u8> {
    vec![
        0x00, 0x61, 0x73, 0x6d, 0x01, 0x00, 0x00, 0x00, 0x01, 0x05, 0x01, 0x60, 0x00, 0x01, 0x7f,
        0x03, 0x02, 0x01, 0x00, 0x07, 0x07, 0x01, 0x03, 0x72, 0x75, 0x6e, 0x00, 0x00, 0x0a, 0x06,
        0x01, 0x04, 0x00, 0x41, 0x07, 0x0b,
    ]
}
