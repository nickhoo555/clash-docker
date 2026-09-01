#!/bin/sh
set -eu

CONFIG_ROOT=/config/configs
LOCAL_CONFIG_DIR=$CONFIG_ROOT/local
REMOTE_CONFIG_DIR=$CONFIG_ROOT/remote
REMOTE_CACHE_DIR=$CONFIG_ROOT/cache
LEGACY_LOCAL_CONFIG=/config/config.yaml
LEGACY_REMOTE_CONFIG=/config/remote/config.yaml
ACTIVE_CONFIG=/config/.runtime-config.yaml
UPDATE_INTERVAL=${MIHOMO_CONFIG_UPDATE_INTERVAL:-3600}

CONFIG_SELECTOR=
CONFIG_TYPE=
CONFIG_NAME=
ACTIVE_TARGET=
REMOTE_URL=
REMOTE_CONFIG=
REMOTE_CONFIG_CANDIDATE=
VALIDATION_LOG=

fail() {
  echo "$*" >&2
  exit 1
}

validate_name() {
  case "$1" in
    ''|*[!a-zA-Z0-9._-]*)
      fail "config name must contain only letters, numbers, '.', '_' or '-'"
      ;;
  esac
}

validate_remote_settings() {
  case "$UPDATE_INTERVAL" in
    ''|*[!0-9]*)
      fail "MIHOMO_CONFIG_UPDATE_INTERVAL must be a non-negative integer"
      ;;
  esac

  case "$REMOTE_URL" in
    http://*|https://*) ;;
    *) fail "remote config URL must start with http:// or https://" ;;
  esac
}

read_remote_url() {
  url_file=$REMOTE_CONFIG_DIR/$CONFIG_NAME.url
  [ -f "$url_file" ] || fail "missing remote config descriptor: $url_file"

  REMOTE_URL=$(awk '
    NR == 1 {
      sub(/\r$/, "")
      sub(/^[[:space:]]+/, "")
      sub(/[[:space:]]+$/, "")
      print
      next
    }
    NF { extra = 1 }
    END { if (extra) exit 1 }
  ' "$url_file") || fail "remote config descriptor must contain exactly one URL: $url_file"
}

resolve_config() {
  requested_selector=${MIHOMO_CONFIG:-}

  # Backward compatibility for the earlier single-URL interface.
  if [ -z "$requested_selector" ] && [ -n "${MIHOMO_CONFIG_URL:-}" ]; then
    CONFIG_SELECTOR=remote:legacy
    REMOTE_URL=$MIHOMO_CONFIG_URL
  else
    CONFIG_SELECTOR=${requested_selector:-local:default}
  fi

  case "$CONFIG_SELECTOR" in
    local:*) CONFIG_TYPE=local ;;
    remote:*) CONFIG_TYPE=remote ;;
    *) fail "MIHOMO_CONFIG must use <local|remote>:<name>, for example local:default" ;;
  esac

  CONFIG_NAME=${CONFIG_SELECTOR#*:}
  validate_name "$CONFIG_NAME"

  case "$CONFIG_NAME" in
    *:*) fail "config name must not contain ':'" ;;
  esac

  if [ "$CONFIG_TYPE" = local ]; then
    local_config=$LOCAL_CONFIG_DIR/$CONFIG_NAME.yaml
    if [ -f "$local_config" ]; then
      ACTIVE_TARGET=configs/local/$CONFIG_NAME.yaml
    elif [ "$CONFIG_NAME" = default ] && [ -f "$LEGACY_LOCAL_CONFIG" ]; then
      echo "using legacy local config: $LEGACY_LOCAL_CONFIG" >&2
      ACTIVE_TARGET=config.yaml
    else
      fail "missing local config: $local_config"
    fi
    return
  fi

  if [ -z "$REMOTE_URL" ]; then
    read_remote_url
  fi
  validate_remote_settings

  REMOTE_CONFIG=$REMOTE_CACHE_DIR/$CONFIG_NAME.yaml
  REMOTE_CONFIG_CANDIDATE=$REMOTE_CACHE_DIR/.$CONFIG_NAME.yaml.new
  VALIDATION_LOG=/tmp/mihomo-config-$CONFIG_NAME-validation.log
  ACTIVE_TARGET=configs/cache/$CONFIG_NAME.yaml

  if [ "$CONFIG_SELECTOR" = remote:legacy ] && \
     [ ! -f "$REMOTE_CONFIG" ] && [ -s "$LEGACY_REMOTE_CONFIG" ]; then
    mkdir -p "$REMOTE_CACHE_DIR"
    cp "$LEGACY_REMOTE_CONFIG" "$REMOTE_CONFIG"
    echo "migrated legacy remote config cache" >&2
  fi
}

download_remote_config() {
  mkdir -p "$REMOTE_CACHE_DIR"
  rm -f "$REMOTE_CONFIG_CANDIDATE"

  if ! wget -q -T 30 -O "$REMOTE_CONFIG_CANDIDATE" "$REMOTE_URL"; then
    echo "failed to download remote config: $CONFIG_SELECTOR" >&2
    rm -f "$REMOTE_CONFIG_CANDIDATE"
    return 1
  fi

  if [ ! -s "$REMOTE_CONFIG_CANDIDATE" ]; then
    echo "downloaded remote config is empty: $CONFIG_SELECTOR" >&2
    rm -f "$REMOTE_CONFIG_CANDIDATE"
    return 1
  fi

  if ! /mihomo -t -d /config -f "$REMOTE_CONFIG_CANDIDATE" >"$VALIDATION_LOG" 2>&1; then
    echo "downloaded remote config is invalid: $CONFIG_SELECTOR" >&2
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
      echo "remote config updated; reloading: $CONFIG_SELECTOR"
      kill -HUP 1
    fi
  done
}

activate_remote_config() {
  if download_remote_config; then
    echo "remote config downloaded: $CONFIG_SELECTOR"
  else
    download_status=$?
    if [ "$download_status" -ne 2 ]; then
      if [ ! -s "$REMOTE_CONFIG" ]; then
        fail "no valid cached config is available: $CONFIG_SELECTOR"
      fi
      echo "using cached remote config: $CONFIG_SELECTOR" >&2
    fi
  fi

  if [ "$UPDATE_INTERVAL" -gt 0 ]; then
    refresh_loop &
  fi
}

resolve_config

if [ "$CONFIG_TYPE" = remote ]; then
  activate_remote_config
fi

ln -sf "$ACTIVE_TARGET" "$ACTIVE_CONFIG"
echo "active Mihomo config: $CONFIG_SELECTOR"

exec /mihomo \
  -d /config \
  -f "$ACTIVE_CONFIG" \
  -ext-ctl 0.0.0.0:9090 \
  -secret "${MIHOMO_SECRET:-}"
