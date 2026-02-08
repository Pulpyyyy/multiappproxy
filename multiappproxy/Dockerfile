ARG BUILD_FROM
FROM $BUILD_FROM

# Installer Nginx et Python avec PyYAML
RUN apk add --no-cache \
    nginx \
    python3 \
    py3-pip \
    py3-yaml \
    jq \
    bash

# Créer les répertoires nécessaires
RUN mkdir -p /app /run/nginx /var/log/nginx

# Supprimer la configuration par défaut de Nginx
RUN rm -f /etc/nginx/nginx.conf /etc/nginx/conf.d/default.conf

# Copier les fichiers
COPY rootfs /

# Rendre les scripts exécutables
RUN chmod a+x /app/*.py \
    && chmod a+x /etc/cont-init.d/*.sh \
    && chmod a+x /etc/services.d/*/run \
    && chmod a+x /etc/services.d/*/finish

WORKDIR /app

# Exposer le port
EXPOSE 8099
