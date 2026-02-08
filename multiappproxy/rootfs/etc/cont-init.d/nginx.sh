#!/command/with-contenv bashio
# ==============================================================================
# Generate nginx configuration
# ==============================================================================

bashio::log.info "=========================================="
bashio::log.info "Multi-App Proxy - Configuration"
bashio::log.info "=========================================="

CONFIG_PATH=/data/options.json

# Détecter le mode Ingress en vérifiant les variables d'environnement HA
if bashio::var.has_value "$(bashio::addon.ingress_entry)"; then
    INGRESS_ENTRY=$(bashio::addon.ingress_entry)
    bashio::log.info "Mode Ingress détecté: ${INGRESS_ENTRY}"
    export INGRESS_ENTRY
else
    bashio::log.info "Mode Standalone"
    export INGRESS_ENTRY="/"
fi

bashio::log.info "Lecture de la configuration..."
python3 /app/sync_config.py || bashio::log.warning "Sync config ignoré"
python3 /app/json_to_yaml.py || bashio::exit.nok "Échec conversion JSON"

bashio::log.info "Génération de la configuration Nginx..."
python3 /app/generate_config.py || bashio::exit.nok "Échec génération Nginx"

if [ ! -f /etc/nginx/nginx.conf ]; then
    bashio::exit.nok "nginx.conf n'existe pas !"
fi

bashio::log.info "Validation de la configuration..."
nginx -t 2>&1 | grep -v "warn" || bashio::exit.nok "Configuration invalide"

APP_COUNT=$(jq '.apps | length' $CONFIG_PATH)
bashio::log.info "=========================================="
bashio::log.info "${APP_COUNT} application(s) configurée(s)"

for i in $(seq 0 $(($APP_COUNT - 1))); do
    APP_NAME=$(jq -r ".apps[$i].name" $CONFIG_PATH)
    APP_URL=$(jq -r ".apps[$i].url" $CONFIG_PATH)
    bashio::log.info "  - ${APP_NAME}: ${APP_URL}"
done

bashio::log.info "=========================================="
bashio::log.info "Configuration terminée avec succès"
