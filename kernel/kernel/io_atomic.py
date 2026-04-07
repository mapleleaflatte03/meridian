#!/usr/bin/env python3
"""Atomic persistence helpers for file-backed kernel state."""

from __future__ import annotations

import json
import os
from typing import Any


def atomic_write_json(path: str, data: Any, *, indent: int = 2) -> None:
    directory = os.path.dirname(path) or '.'
    os.makedirs(directory, exist_ok=True)
    tmp_path = f"{path}.tmp.{os.getpid()}"
    try:
        with open(tmp_path, 'w') as f:
            json.dump(data, f, indent=indent)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
        _fsync_directory(directory)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def append_jsonl(path: str, entry: dict[str, Any]) -> None:
    directory = os.path.dirname(path) or '.'
    os.makedirs(directory, exist_ok=True)
    with open(path, 'a') as f:
        f.write(json.dumps(entry) + '\n')
        f.flush()
        os.fsync(f.fileno())


def _fsync_directory(directory: str) -> None:
    try:
        dir_fd = os.open(directory, os.O_DIRECTORY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
