#!/bin/bash

echo "=========================================="
echo "Multi-App Proxy - Diagnostic"
echo "=========================================="
echo ""

echo "1. Environment:"
echo "   - Bash version: $(bash --version | head -n1)"
echo "   - Python version: $(python3 --version)"
echo "   - Nginx version: $(nginx -v 2>&1)"
echo "   - jq version: $(jq --version)"
echo ""

echo "2. Environment variables:"
echo "   - INGRESS_ENTRY: ${INGRESS_ENTRY:-'(not set)'}"
echo "   - HOME: ${HOME:-'(not set)'}"
echo "   - PATH: ${PATH:-'(not set)'}"
echo ""

echo "3. Configuration files:"
if [ -f "/data/options.json" ]; then
    echo "   ✓ /data/options.json exists"
    echo "   Size: $(wc -c < /data/options.json) bytes"
    echo "   Content:"
    cat /data/options.json | jq . 2>&1 | head -20
else
    echo "   ✗ /data/options.json MISSING"
fi
echo ""

echo "4. Permissions:"
echo "   - /data: $(ls -ld /data 2>&1)"
echo "   - /app: $(ls -ld /app 2>&1)"
echo "   - /etc/nginx: $(ls -ld /etc/nginx 2>&1)"
echo ""

echo "5. Available scripts:"
ls -lh /app/*.py /app/*.sh 2>&1
echo ""

echo "=========================================="
echo "End of diagnostic"
echo "=========================================="
