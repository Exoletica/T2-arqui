#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CERT_DIR="${1:-$ROOT/certs}"
mkdir -p "$CERT_DIR"
umask 077
# No sobrescribir un par existente; para renovarlo, usar otro directorio.
if [[ -e "$CERT_DIR/localhost.key" || -e "$CERT_DIR/localhost.crt" ]]; then
  echo "Ya existe un certificado o clave en $CERT_DIR; usa otro directorio para regenerarlo." >&2
  exit 1
fi
openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days 365 \
  -keyout "$CERT_DIR/localhost.key" -out "$CERT_DIR/localhost.crt" \
  -subj '/CN=localhost' \
  -addext 'subjectAltName=DNS:localhost,IP:127.0.0.1' \
  -addext 'basicConstraints=critical,CA:FALSE' \
  -addext 'keyUsage=critical,digitalSignature,keyEncipherment' \
  -addext 'extendedKeyUsage=serverAuth'
echo "Certificado de desarrollo generado en $CERT_DIR (localhost y 127.0.0.1)."
