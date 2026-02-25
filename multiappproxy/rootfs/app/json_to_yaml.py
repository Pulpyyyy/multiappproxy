#!/usr/bin/env python3

import json
import yaml
import sys

print("[DEBUG] json_to_yaml.py - Starting")

try:
    # Read the Home Assistant options JSON
    print("[DEBUG] Reading /data/options.json...")
    with open('/data/options.json', 'r') as f:
        config = json.load(f)

    print(f"[DEBUG] Config loaded: {len(config.get('apps', []))} app(s)")

    # Write as YAML for generate_config.py
    print("[DEBUG] Writing /app/config.yml...")
    with open('/app/config.yml', 'w') as f:
        yaml.dump(config, f, default_flow_style=False)

    print("[DEBUG] ✓ Config converted from JSON to YAML")

except FileNotFoundError as e:
    print(f"[ERROR] File not found: {e}", file=sys.stderr)
    sys.exit(1)
except json.JSONDecodeError as e:
    print(f"[ERROR] JSON parse error: {e}", file=sys.stderr)
    sys.exit(1)
except Exception as e:
    print(f"[ERROR] Unexpected error: {e}", file=sys.stderr)
    sys.exit(1)
