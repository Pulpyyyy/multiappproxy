#!/command/with-contenv bashio
# ==============================================================================
# Generate nginx configuration
# ==============================================================================

bashio::log.info "=========================================="
bashio::log.info "Multi-App Proxy - Configuration"
bashio::log.info "=========================================="

CONFIG_PATH=/data/options.json

# Detect Ingress mode from the HA environment variable
if bashio::var.has_value "$(bashio::addon.ingress_entry)"; then
    INGRESS_ENTRY=$(bashio::addon.ingress_entry)
    bashio::log.info "Ingress mode detected: ${INGRESS_ENTRY}"
    export INGRESS_ENTRY
else
    bashio::log.info "Standalone mode"
    export INGRESS_ENTRY="/"
fi

bashio::log.info "Reading configuration..."
python3 /app/sync_config.py || bashio::log.warning "Sync config skipped"
python3 /app/json_to_yaml.py || bashio::exit.nok "JSON conversion failed"

bashio::log.info "Generating Nginx configuration..."
python3 /app/generate_config.py || bashio::exit.nok "Nginx config generation failed"

if [ ! -f /etc/nginx/nginx.conf ]; then
    bashio::exit.nok "nginx.conf does not exist!"
fi

bashio::log.info "Validating configuration..."
nginx -t 2>&1 | grep -v "warn" || bashio::exit.nok "Invalid Nginx configuration"

APP_COUNT=$(jq '.apps | length' $CONFIG_PATH)
bashio::log.info "=========================================="
bashio::log.info "${APP_COUNT} application(s) configured"

for i in $(seq 0 $(($APP_COUNT - 1))); do
    APP_NAME=$(jq -r ".apps[$i].name" $CONFIG_PATH)
    APP_URL=$(jq -r ".apps[$i].url" $CONFIG_PATH)
    bashio::log.info "  - ${APP_NAME}: ${APP_URL}"
done

bashio::log.info "=========================================="
bashio::log.info "Configuration completed successfully"
