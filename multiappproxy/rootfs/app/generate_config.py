#!/usr/bin/env python3

import yaml
import json
import os
import sys
from urllib.parse import quote

def generate_nginx_config(config_file='/app/config.yml'):
    """Génère la configuration Nginx à partir du fichier YAML"""
    
    print("[DEBUG] generate_config.py - Démarrage")
    
    try:
        print(f"[DEBUG] Lecture de {config_file}...")
        with open(config_file, 'r') as f:
            config = yaml.safe_load(f)
        
        apps = config.get('apps', [])
        debug_mode = config.get('debug', False)
        print(f"[DEBUG] {len(apps)} application(s) trouvée(s)")
        print(f"[DEBUG] Mode debug: {debug_mode}")
        
        # Détecter si on est en mode Ingress (variable d'environnement HA)
        ingress_entry = os.environ.get('INGRESS_ENTRY', '/')
        is_ingress = ingress_entry != '/'
        
        print(f"[DEBUG] Mode Ingress: {is_ingress}")
        print(f"[DEBUG] Ingress entry: {ingress_entry}")
        
        # Générer le JSON pour la page d'accueil
        apps_json = []
        for i, app in enumerate(apps):
            print(f"[DEBUG] App {i+1}: {app.get('name', 'N/A')}")
            apps_json.append({
                'name': app['name'],
                'url': app['url'],
                'description': app.get('description', ''),
                'icon': app.get('icon', ''),
                'logo': app.get('logo', ''),
                'category': app.get('category', 'default'),
                'path': app.get('path', f"/{app['name'].lower().replace(' ', '-')}"),
                'debug': debug_mode
            })
        
        apps_json_str = json.dumps(apps_json).replace("'", "\\'").replace('"', '\\"')
        print(f"[DEBUG] JSON généré: {len(apps_json_str)} caractères")
        
        # Écrire le fichier apps.json avec debug
        with open('/app/apps.json', 'w') as f:
            json.dump({'apps': apps_json, 'debug': debug_mode}, f, indent=2)
        print(f"[DEBUG] Fichier apps.json créé")
        
        # Template de base Nginx avec support Ingress
        print("[DEBUG] Génération du template Nginx...")
        
        # Niveau de log selon le mode debug
        error_log_level = "debug" if debug_mode else "warn"
        
        nginx_config = f"""
events {{
    worker_connections 1024;
}}

http {{
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    
    # DNS Resolver (utilise le DNS de Home Assistant Supervisor)
    resolver 172.30.32.3 valid=10s;
    resolver_timeout 5s;
    
    # Logs
    access_log /var/log/nginx/access.log;
    error_log /var/log/nginx/error.log {error_log_level};
    
    # Performance
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    keepalive_timeout 65;
    types_hash_max_size 2048;
    
    # Gzip
    gzip on;
    gzip_vary on;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml;
    
    # Map pour gérer le prefix Ingress
    map $http_x_ingress_path $ingress_path {{
        default "{ingress_entry}";
    }}
    
    server {{
        listen 8099;
        server_name _;
        
        # Gestion du base path pour Ingress
        set $base_path "";
"""
        
        if is_ingress:
            nginx_config += f"""
        # Mode Ingress - HA retire le prefix, on utilise /
        set $base_path "";
"""
        
        nginx_config += """
        
        # Page d'accueil
        location = / {
            alias /app/;
            try_files /index.html =404;
        }
        
        location = /apps.json {
            alias /app/apps.json;
            default_type application/json;
            add_header Access-Control-Allow-Origin *;
            add_header Cache-Control "no-cache, no-store, must-revalidate";
        }
        
        location /static/ {
            alias /app/static/;
        }
"""
        
        # Générer les proxys pour chaque app
        print("[DEBUG] Génération des configurations proxy...")
        for app in apps:
            name = app['name']
            url = app['url']
            path = app.get('path', f"/{name.lower().replace(' ', '-')}")
            
            print(f"[DEBUG] App config brute: {app}")
            
            # Détecter si c'est une app qui nécessite une réécriture complète
            # Si rewrite est explicitement défini (True ou False), on le respecte
            # Sinon, on auto-détecte selon le nom
            if 'rewrite' in app:
                needs_rewrite = app['rewrite']
                print(f"[DEBUG] Rewrite explicite pour {name}: {needs_rewrite}")
            else:
                # Auto-détection seulement si pas spécifié
                name_lower = name.lower()
                needs_rewrite = (
                    'zwave' in name_lower or 
                    'zwavejs' in name_lower or
                    'zigbee2mqtt' in name_lower or
                    'z2m' in name_lower
                )
                print(f"[DEBUG] Rewrite auto-détecté pour {name}: {needs_rewrite}")
            
            print(f"[DEBUG] Proxy {name}: {path} -> {url} (rewrite: {needs_rewrite})")
            
            if needs_rewrite:
                # Configuration avec réécriture complète pour apps type Z-Wave JS UI
                token = app.get('token', '')
                
                # URL-encoder le token pour supporter les caractères spéciaux
                if token:
                    token_encoded = quote(token, safe='')
                    print(f"[DEBUG] Token encodé: {token[:5]}... → {token_encoded[:5]}...")
                    token_config = f"""set $token "{token_encoded}";
            set $args $args&token=$token;
            """
                else:
                    token_encoded = ''
                    token_config = ''
                
                nginx_config += f"""
        # Proxy pour {name} (avec réécriture)
        location {path}/ {{
            # ACL: Autoriser uniquement le Supervisor HA
            allow 172.30.32.2;
            deny all;
            
            # Token d'authentification
            {token_config}
            # Réécrire l'URL pour enlever le prefix
            rewrite ^{path}/(.*) /$1 break;
            
            proxy_pass {url};
            proxy_http_version 1.1;
            
            # Désactiver la vérification SSL (pour certificats auto-signés)
            proxy_ssl_verify off;
            proxy_ssl_server_name on;
            
            # WebSocket support
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
            
            # Headers standard
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            
            # Header pour indiquer le path externe
            proxy_set_header X-External-Path {path};
            
            # Pas de redirection
            proxy_redirect off;
            
            # Pas de buffering pour WebSocket
            proxy_buffering off;
            
            # Headers cache (important pour Z2M)
            add_header Cache-Control "no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0";
            add_header Pragma "no-cache";
            add_header Expires 0;
            
            # Timeouts pour les WebSockets
            proxy_read_timeout 86400;
            proxy_send_timeout 86400;
            proxy_connect_timeout 240;
            
            # Réécriture du contenu HTML/JS/CSS pour ajouter le prefix
            sub_filter_types text/html text/css text/javascript application/javascript application/json;
            sub_filter_once off;
            sub_filter 'src="/' 'src="{path}/';
            sub_filter 'href="/' 'href="{path}/';
            sub_filter "src='/" "src='{path}/";
            sub_filter "href='/" "href='{path}/";
            sub_filter 'url(/' 'url({path}/';
            sub_filter '/api/' '{path}/api/';
            sub_filter '/socket.io/' '{path}/socket.io/';
            sub_filter '\\"/' '\\"{path}/';
            sub_filter "\\'/" "\\'{path}/";
        }}
        
        # Support des fichiers statiques sans prefix
        location ~ ^{path}/(static|css|js|fonts|img|images)/ {{
            rewrite ^{path}/(.*) /$1 break;
            proxy_pass {url};
            proxy_ssl_verify off;
            proxy_ssl_server_name on;
            proxy_set_header Host $host;
            proxy_cache_valid 200 1h;
            expires 1h;
        }}
"""
            else:
                # Configuration standard
                token = app.get('token', '')
                
                # URL-encoder le token pour supporter les caractères spéciaux
                if token:
                    token_encoded = quote(token, safe='')
                    print(f"[DEBUG] Token encodé: {token[:5]}... → {token_encoded[:5]}...")
                else:
                    token_encoded = ''
                
                # Trailing slash pour strip le prefix
                proxy_url = f"{url}/"
                
                token_config = ''
                if token_encoded:
                    # Logique zigbee2mqtt-proxy: suffix = '&' si args existe, sinon ''
                    token_config = f"""# Token d'authentification (comme zigbee2mqtt-proxy)
            set $suffix '';
            if ($args != '') {{
                set $suffix '&';
            }}
            set $token "{token_encoded}";
            set $args $args${{suffix}}token=$token;
            """
                
                nginx_config += f"""
        # Proxy pour {name}
        location {path}/ {{
            # ACL: Autoriser uniquement le Supervisor HA
            allow 172.30.32.2;
            deny all;
            
            {token_config}
            proxy_pass {proxy_url};
            proxy_http_version 1.1;
            
            # Désactiver la vérification SSL (pour certificats auto-signés)
            proxy_ssl_verify off;
            proxy_ssl_server_name on;
            
            # WebSocket support
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
            
            # Headers standard
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Ingress-Path $http_x_ingress_path;
            
            # Réécrire les redirections pour pointer vers notre proxy
            proxy_redirect / {path}/;
            proxy_redirect http://$host/ {path}/;
            proxy_redirect https://$host/ {path}/;
            
            # Headers cache (important pour Z2M)
            add_header Cache-Control "no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0";
            add_header Pragma "no-cache";
            add_header Expires 0;
            
            # Timeouts pour les WebSockets
            proxy_read_timeout 86400;
            proxy_send_timeout 86400;
        }}
"""
        
        nginx_config += """
    }
}
"""
        
        # Écrire la config Nginx
        print("[DEBUG] Écriture de /etc/nginx/nginx.conf...")
        with open('/etc/nginx/nginx.conf', 'w') as f:
            f.write(nginx_config)
        
        print(f"✓ Configuration Nginx générée avec succès")
        print(f"✓ Mode: {'Ingress' if is_ingress else 'Standalone'}")
        print(f"✓ Base path: {ingress_entry}")
        print(f"✓ {len(apps)} application(s) configurée(s)")
        
    except FileNotFoundError as e:
        print(f"[ERROR] Fichier non trouvé: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyError as e:
        print(f"[ERROR] Clé manquante dans la configuration: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] Erreur inattendue: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    generate_nginx_config()
