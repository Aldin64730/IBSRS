"""
file_utils.py
Shared utilities for reading and writing files in the run directory.
All agents import from here — never use open() directly in agent files.

All writes are UTF-8 with a trailing newline and explicit ordering so that two
runs of the same bundle produce byte-identical artifacts (idempotency).
"""

import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List


def read_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: str, data: Any) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"[file_utils] Written: {path}")


def read_yaml(path: str) -> Any:
    import yaml
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def write_markdown(path: str, content: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    text = content if content.endswith("\n") else content + "\n"
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print(f"[file_utils] Written: {path}")


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def append_log(path: str, message: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(message + "\n")


def read_csv_rows(path: str) -> List[Dict[str, str]]:
    """Read a CSV into a list of dict rows (header-keyed)."""
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return [dict(row) for row in csv.DictReader(f)]


def write_csv(path: str, rows: List[Dict[str, Any]], fieldnames: List[str]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    print(f"[file_utils] Written: {path}")


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()
