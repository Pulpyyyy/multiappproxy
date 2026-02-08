#!/bin/bash

echo "=========================================="
echo "Multi-App Proxy - Diagnostic"
echo "=========================================="
echo ""

echo "1. Vérification de l'environnement:"
echo "   - Bash version: $(bash --version | head -n1)"
echo "   - Python version: $(python3 --version)"
echo "   - Nginx version: $(nginx -v 2>&1)"
echo "   - jq version: $(jq --version)"
echo ""

echo "2. Variables d'environnement:"
echo "   - INGRESS_ENTRY: ${INGRESS_ENTRY:-'(non définie)'}"
echo "   - HOME: ${HOME:-'(non définie)'}"
echo "   - PATH: ${PATH:-'(non définie)'}"
echo ""

echo "3. Fichiers de configuration:"
if [ -f "/data/options.json" ]; then
    echo "   ✓ /data/options.json existe"
    echo "   Taille: $(wc -c < /data/options.json) octets"
    echo "   Contenu:"
    cat /data/options.json | jq . 2>&1 | head -20
else
    echo "   ✗ /data/options.json MANQUANT"
fi
echo ""

echo "4. Permissions:"
echo "   - /data: $(ls -ld /data 2>&1)"
echo "   - /app: $(ls -ld /app 2>&1)"
echo "   - /etc/nginx: $(ls -ld /etc/nginx 2>&1)"
echo ""

echo "5. Scripts disponibles:"
ls -lh /app/*.py /app/*.sh 2>&1
echo ""

echo "=========================================="
echo "Fin du diagnostic"
echo "=========================================="
