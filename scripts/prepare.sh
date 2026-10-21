#!/usr/bin/env bash
# Creates .env from the template and fills what can be generated. Idempotent: it never overwrites
# a value that is already set. Exits with 3 when BOT_TOKEN or DEFAULT_MODEL still need a value.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
# shellcheck disable=SC1091
source scripts/lib/env.sh

ENV_FILE_PATH=.env

set_var() {  # set_var NAME VALUE -- replace the NAME= line, or append one
  local name="$1" value="$2" tmp line found=0
  tmp="$(mktemp)"
  while IFS= read -r line || [ -n "${line}" ]; do
    if [ "${found}" = 0 ] && [[ "${line}" =~ ^${name}= ]]; then
      printf '%s=%s\n' "${name}" "${value}"; found=1
    else
      printf '%s\n' "${line}"
    fi
  done < "${ENV_FILE_PATH}" > "${tmp}"
  [ "${found}" = 1 ] || printf '%s=%s\n' "${name}" "${value}" >> "${tmp}"
  cat "${tmp}" > "${ENV_FILE_PATH}"; rm -f "${tmp}"
}

if [ ! -f "${ENV_FILE_PATH}" ]; then
  cp .env.example "${ENV_FILE_PATH}"
  chmod 600 "${ENV_FILE_PATH}"
  echo "    created ${ENV_FILE_PATH}"
fi

if [ -z "$(env_get POSTGRES_PASSWORD "${ENV_FILE_PATH}")" ]; then
  pw="$(openssl rand -hex 24)"
  set_var POSTGRES_PASSWORD "${pw}"
  set_var DATABASE_URL "postgresql://telegram_bot:${pw}@db:5432/telegram_bot"
  echo "    generated POSTGRES_PASSWORD"
fi
if [ -z "$(env_get CREDS_KEY "${ENV_FILE_PATH}")" ]; then
  set_var CREDS_KEY "$(openssl rand -base64 32 | tr '+/' '-_')"
  echo "    generated CREDS_KEY"
fi
for name in BOT_TOKEN DEFAULT_MODEL; do
  [ -n "$(env_get "${name}" "${ENV_FILE_PATH}")" ] || { echo "    still needed: set ${name} in ${ENV_FILE_PATH}"; MISSING=1; }
done
[ -z "${MISSING:-}" ] || exit 3
