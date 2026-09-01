#!/bin/sh
set -eu

LOCAL_CONFIG=/config/config.yaml
REMOTE_CONFIG_DIR=/config/remote
REMOTE_CONFIG=$REMOTE_CONFIG_DIR/config.yaml
REMOTE_CONFIG_CANDIDATE=$REMOTE_CONFIG_DIR/.config.yaml.new
ACTIVE_CONFIG=/config/.runtime-config.yaml
VALIDATION_LOG=/tmp/mihomo-config-validation.log
UPDATE_INTERVAL=${MIHOMO_CONFIG_UPDATE_INTERVAL:-3600}

validate_settings() {
  case "$UPDATE_INTERVAL" in
    ''|*[!0-9]*)
      echo "MIHOMO_CONFIG_UPDATE_INTERVAL must be a non-negative integer" >&2
      exit 1
      ;;
  esac

  if [ -n "${MIHOMO_CONFIG_URL:-}" ]; then
    case "$MIHOMO_CONFIG_URL" in
      http://*|https://*) ;;
      *)
        echo "MIHOMO_CONFIG_URL must start with http:// or https://" >&2
        exit 1
        ;;
    esac
  fi
}

download_remote_config() {
  mkdir -p "$REMOTE_CONFIG_DIR"
  rm -f "$REMOTE_CONFIG_CANDIDATE"

  if ! wget -q -T 30 -O "$REMOTE_CONFIG_CANDIDATE" "$MIHOMO_CONFIG_URL"; then
    echo "failed to download remote Mihomo config" >&2
    rm -f "$REMOTE_CONFIG_CANDIDATE"
    return 1
  fi

  if [ ! -s "$REMOTE_CONFIG_CANDIDATE" ]; then
    echo "downloaded remote Mihomo config is empty" >&2
    rm -f "$REMOTE_CONFIG_CANDIDATE"
    return 1
  fi

  if ! /mihomo -t -d /config -f "$REMOTE_CONFIG_CANDIDATE" >"$VALIDATION_LOG" 2>&1; then
    echo "downloaded remote Mihomo config is invalid:" >&2
    cat "$VALIDATION_LOG" >&2
    rm -f "$REMOTE_CONFIG_CANDIDATE"
    return 1
  fi

  if [ -f "$REMOTE_CONFIG" ] && cmp -s "$REMOTE_CONFIG_CANDIDATE" "$REMOTE_CONFIG"; then
    rm -f "$REMOTE_CONFIG_CANDIDATE"
    return 2
  fi

  mv "$REMOTE_CONFIG_CANDIDATE" "$REMOTE_CONFIG"
  return 0
}

refresh_loop() {
  while sleep "$UPDATE_INTERVAL"; do
    if download_remote_config; then
      echo "remote Mihomo config updated; reloading"
      kill -HUP 1
    fi
  done
}

validate_settings

if [ -n "${MIHOMO_CONFIG_URL:-}" ]; then
  if download_remote_config; then
    echo "remote Mihomo config downloaded"
  else
    download_status=$?
    if [ "$download_status" -ne 2 ]; then
      if [ ! -s "$REMOTE_CONFIG" ]; then
        echo "no valid cached remote Mihomo config is available" >&2
        exit 1
      fi
      echo "using cached remote Mihomo config" >&2
    fi
  fi

  ln -sf remote/config.yaml "$ACTIVE_CONFIG"

  if [ "$UPDATE_INTERVAL" -gt 0 ]; then
    refresh_loop &
  fi
else
  if [ ! -f "$LOCAL_CONFIG" ]; then
    echo "missing local Mihomo config: $LOCAL_CONFIG" >&2
    echo "create it or set MIHOMO_CONFIG_URL in .env" >&2
    exit 1
  fi
  ln -sf config.yaml "$ACTIVE_CONFIG"
fi

exec /mihomo \
  -d /config \
  -f "$ACTIVE_CONFIG" \
  -ext-ctl 0.0.0.0:9090 \
  -secret "${MIHOMO_SECRET:-}"
