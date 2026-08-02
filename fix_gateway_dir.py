import sys

filepath = 'intelligence/meridian_gateway.py'
with open(filepath, 'r') as f:
    content = f.read()

old_str = """def _resolve_kernel_dir() -> Path:
    explicit_root = str(os.environ.get("MERIDIAN_KERNEL_ROOT") or "").strip()
    if explicit_root:
        return Path(explicit_root) / "kernel"
    for root in ("/opt/meridian-kernel", "/home/ubuntu/meridian/kernel"):
        candidate = Path(root) / "kernel"
        if candidate.exists():
            return candidate
    return Path("/opt/meridian-kernel/kernel")"""

new_str = """def _resolve_kernel_dir() -> Path:
    explicit_root = str(os.environ.get("MERIDIAN_KERNEL_ROOT") or "").strip()
    if explicit_root:
        return Path(explicit_root) / "kernel"
    for root in ("/opt/meridian-kernel", "/home/ubuntu/meridian/kernel"):
        candidate = Path(root) / "kernel"
        try:
            if candidate.exists():
                return candidate
        except PermissionError:
            pass
    # Fallback to local context-relative path (crucial for GitHub Actions)
    local_fallback = Path(__file__).resolve().parent.parent / "kernel" / "kernel"
    try:
        if local_fallback.exists():
            return local_fallback
    except PermissionError:
        pass
    return Path("/opt/meridian-kernel/kernel")"""

if old_str in content:
    content = content.replace(old_str, new_str)
    with open(filepath, 'w') as f:
        f.write(content)
    print("Modified intelligence/meridian_gateway.py successfully")
else:
    print("Failed to find the string in intelligence/meridian_gateway.py")
    sys.exit(1)
