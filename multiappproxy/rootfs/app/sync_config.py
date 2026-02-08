#!/usr/bin/env python3
"""
Synchronise la configuration entre JSON (UI) et YAML (fichier)
Permet de basculer entre les deux sans perdre de données
"""

import json
import yaml
import sys
import os

def sync_configs():
    """Synchronise JSON (UI) ↔ YAML (fichier)"""
    
    json_path = '/data/options.json'
    yaml_path = '/config/multi-app-proxy.yaml'
    
    # Créer le fichier YAML s'il n'existe pas
    if not os.path.exists(yaml_path):
        print(f"[INFO] Création de {yaml_path}")
        # Copier la config JSON vers YAML
        with open(json_path, 'r') as f:
            config = json.load(f)
        with open(yaml_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
        return
    
    # Lire les deux fichiers
    with open(json_path, 'r') as f:
        json_config = json.load(f)
    
    with open(yaml_path, 'r') as f:
        yaml_config = yaml.safe_load(f) or {}
    
    # Comparer les timestamps de modification
    json_mtime = os.path.getmtime(json_path)
    yaml_mtime = os.path.getmtime(yaml_path)
    
    if json_mtime > yaml_mtime:
        # UI plus récent → Sauvegarder dans YAML
        print("[INFO] UI plus récent, sauvegarde dans YAML")
        with open(yaml_path, 'w') as f:
            yaml.dump(json_config, f, default_flow_style=False, allow_unicode=True)
    elif yaml_mtime > json_mtime:
        # YAML plus récent → Charger dans JSON (lecture seule pour info)
        print("[INFO] YAML plus récent (édition manuelle détectée)")
        print("[INFO] Pour utiliser le YAML, copiez-le dans la config de l'add-on")
    else:
        print("[INFO] Configurations synchronisées")

if __name__ == '__main__':
    try:
        sync_configs()
    except Exception as e:
        print(f"[ERROR] Erreur de synchronisation: {e}", file=sys.stderr)
        sys.exit(1)
