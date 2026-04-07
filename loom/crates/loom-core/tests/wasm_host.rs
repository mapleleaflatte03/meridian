#[path = "../src/wasm_host.rs"]
mod wasm_host;
#[path = "../src/wasm_limits.rs"]
mod wasm_limits;
#[path = "../src/wasm_profiles.rs"]
mod wasm_profiles;

use wasm_host::{
    host_config_hints, render_host_config_human, render_host_config_json, run_wasm_guest,
    validate_host_config, HostBackend, WasmExecutionRequest, WasmGuestSource, WasmHostBuilder,
};
use wasm_limits::WasmStoreLimits;
use wasm_profiles::{PoolingConfig, PoolingProfile};

#[test]
fn host_builder_defaults_to_truthful_preview_mode() {
    let config = WasmHostBuilder::new().build().expect("default host config");
    assert_eq!(config.backend, HostBackend::PreviewOnly);
    assert!(config.component_model_enabled);
    assert!(config.fuel_metering_enabled);
    assert!(validate_host_config(&config).is_ok());
}

#[test]
fn host_builder_can_select_profile_and_backend() {
    let config = WasmHostBuilder::new()
        .with_profile_name("host/standard")
        .with_backend(HostBackend::WasmtimeReady)
        .with_pooling_profile(PoolingProfile::Standard)
        .build()
        .expect("host config");
    let hints = host_config_hints(&config);
    assert_eq!(
        hints.get("profile_name"),
        Some(&"host/standard".to_string())
    );
    assert_eq!(hints.get("backend"), Some(&"wasmtime_ready".to_string()));
    assert_eq!(config.pooling.profile, PoolingProfile::Standard);
}

#[test]
fn host_builder_rejects_incompatible_store_and_pooling() {
    let config = WasmHostBuilder::new()
        .with_store_limits(WasmStoreLimits {
            max_memory_bytes: 512 * 1024,
            max_table_elements: 1_000,
            max_instances: 4,
            max_tables: 4,
            max_memories: 4,
            fuel_limit: Some(10_000),
        })
        .with_pooling_config(PoolingConfig::from_profile(PoolingProfile::Heavy))
        .build();
    let errors = config.expect_err("should fail");
    assert!(errors
        .iter()
        .any(|error| error.contains("exceeds store limit")));
}

#[test]
fn host_rendering_is_terminal_friendly() {
    let config = WasmHostBuilder::new()
        .with_profile_name("terminal/host")
        .with_epoch_deadline_ms(Some(1_500))
        .build()
        .expect("host config");
    let human = render_host_config_human(&config);
    let json = render_host_config_json(&config);
    assert!(human.contains("Meridian Loom // WASM HOST CONFIG"));
    assert!(human.contains("epoch_deadline_ms"));
    assert!(json.contains("\"backend\": \"preview_only\""));
}

#[test]
fn wasm_guest_execution_runs_minimal_module() {
    let host = WasmHostBuilder::new()
        .with_profile_name("runtime/minimal")
        .with_backend(HostBackend::WasmtimeReady)
        .with_pooling_profile(PoolingProfile::Minimal)
        .build()
        .expect("host config");
    let request = WasmExecutionRequest {
        host,
        source: WasmGuestSource::WasmBytes {
            name: "minimal-runner".to_string(),
            bytes: minimal_guest_bytes(),
        },
        entrypoint: "run".to_string(),
        entrypoint_args: vec![],
        memory_probe: None,
        fuel_budget: 100_000,
    };

    let result = run_wasm_guest(&request).expect("wasm guest");
    assert_eq!(result.runtime_path, "wasmtime_local_guest");
    assert_eq!(result.host_backend, "wasmtime_ready");
    assert_eq!(result.entrypoint_result, Some(7));
    assert!(result
        .notes
        .iter()
        .any(|note| note.contains("experimental local Wasmtime guest execution")));
}

#[test]
fn wasm_guest_execution_surfaces_configured_limits_and_profiles() {
    let host = WasmHostBuilder::new()
        .with_profile_name("runtime/custom-memory")
        .with_backend(HostBackend::WasmtimeReady)
        .with_store_limits(WasmStoreLimits {
            max_memory_bytes: 65_536,
            max_table_elements: 256,
            max_instances: 2,
            max_tables: 2,
            max_memories: 2,
            fuel_limit: Some(50_000),
        })
        .with_pooling_config(
            PoolingConfig::from_profile(PoolingProfile::Minimal).with_max_memory_pages(1),
        )
        .build()
        .expect("host config");
    let request = WasmExecutionRequest {
        host,
        source: WasmGuestSource::WasmBytes {
            name: "limit-profile".to_string(),
            bytes: minimal_guest_bytes(),
        },
        entrypoint: "run".to_string(),
        entrypoint_args: vec![],
        fuel_budget: 100_000,
        memory_probe: None,
    };

    let result = run_wasm_guest(&request).expect("wasm guest");
    assert_eq!(result.entrypoint_result, Some(7));
    assert_eq!(result.memory_probe_result, None);
    assert_eq!(result.memory_pages_after, None);
    assert_eq!(result.store_memory_limit_bytes, 65_536);
    assert_eq!(result.pooling_profile, "custom");
    assert_eq!(
        result.host_hints.get("store_memory_budget_bytes"),
        Some(&"65536".to_string())
    );
}

#[test]
fn wasm_host_language_stays_truthful() {
    let config = WasmHostBuilder::new().build().expect("config");
    let human = render_host_config_human(&config);
    let result = run_wasm_guest(&WasmExecutionRequest {
        host: WasmHostBuilder::new()
            .with_backend(HostBackend::WasmtimeReady)
            .build()
            .expect("host"),
        source: WasmGuestSource::WasmBytes {
            name: "truthful".to_string(),
            bytes: minimal_guest_bytes(),
        },
        entrypoint: "run".to_string(),
        entrypoint_args: vec![],
        memory_probe: None,
        fuel_budget: 10_000,
    })
    .expect("guest");
    assert!(human.contains("prepared host config"));
    assert!(result
        .notes
        .iter()
        .any(|note| note.contains("truth boundary: local-only execution path")));
}

fn minimal_guest_bytes() -> Vec<u8> {
    vec![
        0x00, 0x61, 0x73, 0x6d, 0x01, 0x00, 0x00, 0x00, 0x01, 0x05, 0x01, 0x60, 0x00, 0x01, 0x7f,
        0x03, 0x02, 0x01, 0x00, 0x07, 0x07, 0x01, 0x03, 0x72, 0x75, 0x6e, 0x00, 0x00, 0x0a, 0x06,
        0x01, 0x04, 0x00, 0x41, 0x07, 0x0b,
    ]
}
