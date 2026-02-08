#!/usr/bin/env python3

import json
import yaml
import sys

print("[DEBUG] json_to_yaml.py - Démarrage")

try:
    # Lire la configuration JSON de Home Assistant
    print("[DEBUG] Lecture de /data/options.json...")
    with open('/data/options.json', 'r') as f:
        config = json.load(f)
    
    print(f"[DEBUG] Configuration chargée: {len(config.get('apps', []))} app(s)")
    
    # Écrire en YAML pour le script generate_config.py
    print("[DEBUG] Écriture de /app/config.yml...")
    with open('/app/config.yml', 'w') as f:
        yaml.dump(config, f, default_flow_style=False)
    
    print("[DEBUG] ✓ Configuration convertie de JSON vers YAML")
    
except FileNotFoundError as e:
    print(f"[ERROR] Fichier non trouvé: {e}", file=sys.stderr)
    sys.exit(1)
except json.JSONDecodeError as e:
    print(f"[ERROR] Erreur de parsing JSON: {e}", file=sys.stderr)
    sys.exit(1)
except Exception as e:
    print(f"[ERROR] Erreur inattendue: {e}", file=sys.stderr)
    sys.exit(1)
