// wasm_profiles.rs — Pooling allocator profiles for Wasm execution
// Task 7 from LOOM_100_IMPROVEMENTS

use std::collections::BTreeMap;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PoolingProfile {
    /// Minimal footprint for lightweight governance checks
    Minimal,
    /// Standard profile for typical agent workloads
    Standard,
    /// Heavy profile for compute-intensive tasks (analysis, transforms)
    Heavy,
    /// Custom profile with user-specified limits
    Custom,
}

impl PoolingProfile {
    pub fn label(&self) -> &'static str {
        match self {
            Self::Minimal => "minimal",
            Self::Standard => "standard",
            Self::Heavy => "heavy",
            Self::Custom => "custom",
        }
    }

    pub fn all_named() -> &'static [PoolingProfile] {
        &[Self::Minimal, Self::Standard, Self::Heavy]
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PoolingConfig {
    pub profile: PoolingProfile,
    pub max_instances: u32,
    pub max_tables_per_instance: u32,
    pub max_memories_per_instance: u32,
    pub max_memory_pages: u32,
    pub max_table_elements: u32,
    pub instance_timeout_ms: u64,
}

impl PoolingConfig {
    pub fn from_profile(profile: PoolingProfile) -> Self {
        match profile {
            PoolingProfile::Minimal => Self {
                profile,
                max_instances: 4,
                max_tables_per_instance: 1,
                max_memories_per_instance: 1,
                max_memory_pages: 16, // 1 MB
                max_table_elements: 256,
                instance_timeout_ms: 5_000,
            },
            PoolingProfile::Standard => Self {
                profile,
                max_instances: 16,
                max_tables_per_instance: 4,
                max_memories_per_instance: 2,
                max_memory_pages: 256, // 16 MB
                max_table_elements: 4096,
                instance_timeout_ms: 30_000,
            },
            PoolingProfile::Heavy => Self {
                profile,
                max_instances: 16,
                max_tables_per_instance: 8,
                max_memories_per_instance: 4,
                max_memory_pages: 1024, // 64 MB
                max_table_elements: 16384,
                instance_timeout_ms: 120_000,
            },
            PoolingProfile::Custom => Self {
                profile: PoolingProfile::Custom,
                max_instances: 16,
                max_tables_per_instance: 4,
                max_memories_per_instance: 2,
                max_memory_pages: 256,
                max_table_elements: 4096,
                instance_timeout_ms: 30_000,
            },
        }
    }

    pub fn with_max_instances(mut self, n: u32) -> Self {
        self.max_instances = n;
        self.profile = PoolingProfile::Custom;
        self
    }

    pub fn with_max_memory_pages(mut self, pages: u32) -> Self {
        self.max_memory_pages = pages;
        self.profile = PoolingProfile::Custom;
        self
    }

    pub fn with_timeout(mut self, ms: u64) -> Self {
        self.instance_timeout_ms = ms;
        self.profile = PoolingProfile::Custom;
        self
    }

    pub fn total_memory_bytes(&self) -> u64 {
        self.max_instances as u64
            * self.max_memories_per_instance as u64
            * self.max_memory_pages as u64
            * 65536 // Wasm page = 64 KiB
    }

    pub fn validate(&self) -> Result<(), String> {
        if self.max_instances == 0 {
            return Err("max_instances must be > 0".into());
        }
        if self.max_memory_pages == 0 {
            return Err("max_memory_pages must be > 0".into());
        }
        if self.max_tables_per_instance == 0 {
            return Err("max_tables_per_instance must be > 0".into());
        }
        if self.instance_timeout_ms == 0 {
            return Err("instance_timeout_ms must be > 0".into());
        }
        let total = self.total_memory_bytes();
        // Cap at 4 GB total pool
        if total > 4 * 1024 * 1024 * 1024 {
            return Err(format!(
                "total pooled memory {} bytes exceeds 4 GB cap",
                total
            ));
        }
        Ok(())
    }
}

pub fn render_pooling_config_human(cfg: &PoolingConfig) -> String {
    let total_mb = cfg.total_memory_bytes() / (1024 * 1024);
    format!(
        "Meridian Loom // POOLING PROFILE\n\
         ================================\n\
         profile              {}\n\
         max_instances         {}\n\
         tables/instance       {}\n\
         memories/instance     {}\n\
         memory_pages          {} ({} MB each)\n\
         table_elements        {}\n\
         timeout               {} ms\n\
         total_pool_memory     {} MB\n",
        cfg.profile.label(),
        cfg.max_instances,
        cfg.max_tables_per_instance,
        cfg.max_memories_per_instance,
        cfg.max_memory_pages,
        (cfg.max_memory_pages as u64 * 65536) / (1024 * 1024),
        cfg.max_table_elements,
        cfg.instance_timeout_ms,
        total_mb,
    )
}

pub fn render_pooling_config_json(cfg: &PoolingConfig) -> String {
    format!(
        "{{\n  \"profile\": \"{}\",\n  \"max_instances\": {},\n  \"max_tables_per_instance\": {},\n  \"max_memories_per_instance\": {},\n  \"max_memory_pages\": {},\n  \"max_table_elements\": {},\n  \"instance_timeout_ms\": {},\n  \"total_memory_bytes\": {}\n}}",
        cfg.profile.label(),
        cfg.max_instances,
        cfg.max_tables_per_instance,
        cfg.max_memories_per_instance,
        cfg.max_memory_pages,
        cfg.max_table_elements,
        cfg.instance_timeout_ms,
        cfg.total_memory_bytes(),
    )
}

pub fn profile_defaults_map() -> BTreeMap<String, PoolingConfig> {
    let mut m = BTreeMap::new();
    for p in PoolingProfile::all_named() {
        m.insert(p.label().to_string(), PoolingConfig::from_profile(*p));
    }
    m
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_minimal_profile() {
        let cfg = PoolingConfig::from_profile(PoolingProfile::Minimal);
        assert_eq!(cfg.max_instances, 4);
        assert!(cfg.validate().is_ok());
    }

    #[test]
    fn test_standard_profile() {
        let cfg = PoolingConfig::from_profile(PoolingProfile::Standard);
        assert_eq!(cfg.max_instances, 16);
        assert!(cfg.validate().is_ok());
    }

    #[test]
    fn test_heavy_profile() {
        let cfg = PoolingConfig::from_profile(PoolingProfile::Heavy);
        assert_eq!(cfg.max_instances, 16);
        assert!(cfg.validate().is_ok());
    }

    #[test]
    fn test_custom_override() {
        let cfg = PoolingConfig::from_profile(PoolingProfile::Standard)
            .with_max_instances(32)
            .with_timeout(60_000);
        assert_eq!(cfg.profile, PoolingProfile::Custom);
        assert_eq!(cfg.max_instances, 32);
        assert_eq!(cfg.instance_timeout_ms, 60_000);
        assert!(cfg.validate().is_ok());
    }

    #[test]
    fn test_total_memory_calculation() {
        let cfg = PoolingConfig::from_profile(PoolingProfile::Minimal);
        // 4 instances * 1 memory * 16 pages * 65536 = 4,194,304
        assert_eq!(cfg.total_memory_bytes(), 4 * 1 * 16 * 65536);
    }

    #[test]
    fn test_profile_defaults_map() {
        let m = profile_defaults_map();
        assert_eq!(m.len(), 3);
        assert!(m.contains_key("minimal"));
        assert!(m.contains_key("standard"));
        assert!(m.contains_key("heavy"));
    }

    #[test]
    fn test_validation_rejects_zero_instances() {
        let mut cfg = PoolingConfig::from_profile(PoolingProfile::Minimal);
        cfg.max_instances = 0;
        assert!(cfg.validate().is_err());
    }
}
