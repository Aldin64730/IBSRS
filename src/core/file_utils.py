"""
file_utils.py
Shared utilities for reading and writing files in the run directory.
All agents import from here — never use open() directly in agent files.
"""

import json
import csv
import yaml
from pathlib import Path


def read_json(path: str) -> dict:
    with open(path, "r") as f:
        return json.load(f)


def write_json(path: str, data: dict) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"[file_utils] Written: {path}")


def read_yaml(path: str) -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f)


def write_markdown(path: str, content: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    print(f"[file_utils] Written: {path}")


def read_text(path: str) -> str:
    with open(path, "r") as f:
        return f.read()


def append_log(path: str, message: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(message + "\n")
