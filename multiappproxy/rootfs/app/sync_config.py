#!/usr/bin/env python3
"""
Synchronise configuration between JSON (HA UI) and YAML (manual file).
Allows switching between the two sources without losing data.
"""

import json
import yaml
import sys
import os

def sync_configs():
    """Sync JSON (HA UI) ↔ YAML (manual file) based on modification time."""

    json_path = '/data/options.json'
    yaml_path = '/config/multi-app-proxy.yaml'

    # Create the YAML file if it does not exist yet
    if not os.path.exists(yaml_path):
        print(f"[INFO] Creating {yaml_path}")
        # Bootstrap: copy current JSON config to YAML
        with open(json_path, 'r') as f:
            config = json.load(f)
        with open(yaml_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
        return

    # Read both files
    with open(json_path, 'r') as f:
        json_config = json.load(f)

    with open(yaml_path, 'r') as f:
        yaml_config = yaml.safe_load(f) or {}

    # Compare modification timestamps to decide which source wins
    json_mtime = os.path.getmtime(json_path)
    yaml_mtime = os.path.getmtime(yaml_path)

    if json_mtime > yaml_mtime:
        # UI is more recent — persist to YAML
        print("[INFO] UI config is newer, saving to YAML")
        with open(yaml_path, 'w') as f:
            yaml.dump(json_config, f, default_flow_style=False, allow_unicode=True)
    elif yaml_mtime > json_mtime:
        # YAML is more recent — manual edit detected, read-only info
        print("[INFO] YAML config is newer (manual edit detected)")
        print("[INFO] To use the YAML config, copy it into the add-on configuration")
    else:
        print("[INFO] Configurations are in sync")

if __name__ == '__main__':
    try:
        sync_configs()
    except Exception as e:
        print(f"[ERROR] Sync error: {e}", file=sys.stderr)
        sys.exit(1)
