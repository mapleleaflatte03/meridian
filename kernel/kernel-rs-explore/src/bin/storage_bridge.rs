use serde_json::Value;
use std::env;
use std::error::Error;

fn arg_value(args: &[String], flag: &str) -> Option<String> {
    let mut i = 0usize;
    while i < args.len() {
        if args[i] == flag {
            return args.get(i + 1).cloned();
        }
        i += 1;
    }
    None
}

fn next_sequence(meta: &sled::Tree, key: &str) -> Result<u64, Box<dyn Error>> {
    let counter_key = format!("seq::{key}");
    let current = match meta.get(counter_key.as_bytes())? {
        Some(raw) if raw.len() == 8 => {
            let mut bytes = [0u8; 8];
            bytes.copy_from_slice(raw.as_ref());
            u64::from_be_bytes(bytes)
        }
        _ => 0,
    };
    let next = current.saturating_add(1);
    meta.insert(counter_key.as_bytes(), next.to_be_bytes().to_vec())?;
    Ok(next)
}

fn run() -> Result<(), Box<dyn Error>> {
    let args: Vec<String> = env::args().skip(1).collect();
    if args.len() < 3 || args[0] != "--db-path" {
        return Err("usage: storage_bridge --db-path <path> <op> [args]".into());
    }
    let db_path = args[1].clone();
    let operation = args[2].as_str();
    let op_args = &args[3..];

    let db = sled::open(db_path)?;
    let docs = db.open_tree("documents")?;
    let logs = db.open_tree("logs")?;
    let meta = db.open_tree("meta")?;

    match operation {
        "load" => {
            let key = arg_value(op_args, "--key").ok_or("missing --key")?;
            if let Some(raw) = docs.get(key.as_bytes())? {
                let raw_str = std::str::from_utf8(raw.as_ref())?;
                let parsed: Value = serde_json::from_str(raw_str)?;
                println!("{}", serde_json::to_string(&parsed)?);
            } else {
                println!("null");
            }
        }
        "save" => {
            let key = arg_value(op_args, "--key").ok_or("missing --key")?;
            let json_raw = arg_value(op_args, "--json").ok_or("missing --json")?;
            let parsed: Value = serde_json::from_str(&json_raw)?;
            let canonical = serde_json::to_string(&parsed)?;
            docs.insert(key.as_bytes(), canonical.as_bytes())?;
            db.flush()?;
            println!("{{\"ok\":true}}");
        }
        "append" => {
            let key = arg_value(op_args, "--key").ok_or("missing --key")?;
            let json_raw = arg_value(op_args, "--json").ok_or("missing --json")?;
            let parsed: Value = serde_json::from_str(&json_raw)?;
            let canonical = serde_json::to_string(&parsed)?;
            let seq = next_sequence(&meta, &key)?;
            let entry_key = format!("{key}\u{1f}{seq:020}");
            logs.insert(entry_key.as_bytes(), canonical.as_bytes())?;
            db.flush()?;
            println!("{{\"ok\":true}}");
        }
        "read-log" => {
            let key = arg_value(op_args, "--key").ok_or("missing --key")?;
            let tail = arg_value(op_args, "--tail")
                .map(|raw| raw.parse::<usize>())
                .transpose()?;

            let prefix = format!("{key}\u{1f}");
            let mut entries: Vec<Value> = Vec::new();
            for row in logs.scan_prefix(prefix.as_bytes()) {
                let (_, raw) = row?;
                let raw_str = std::str::from_utf8(raw.as_ref())?;
                entries.push(serde_json::from_str(raw_str)?);
            }
            if let Some(limit) = tail {
                if entries.len() > limit {
                    entries = entries.split_off(entries.len() - limit);
                }
            }
            println!("{}", serde_json::to_string(&entries)?);
        }
        "exists" => {
            let key = arg_value(op_args, "--key").ok_or("missing --key")?;
            let present = docs.contains_key(key.as_bytes())?;
            println!("{}", if present { "true" } else { "false" });
        }
        _ => return Err(format!("unknown operation: {operation}").into()),
    }
    Ok(())
}

fn main() {
    if let Err(error) = run() {
        eprintln!("{error}");
        std::process::exit(1);
    }
}
