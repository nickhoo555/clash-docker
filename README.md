# mihomo + zashboard via Docker Compose

[中文说明](README.zh-CN.md)

This stack runs mihomo and zashboard with Docker Compose on a bridge network.
It does not use host networking.

## Files

- `docker-compose.yml`: mihomo + zashboard services
- `.env`: local runtime variables
- `config/mihomo/config.yaml`: generated mihomo runtime config
- `config/mihomo/render-config.sh`: env-driven config renderer
- `config/zashboard/Caddyfile`: static zashboard site config

## Start

```bash
docker compose up -d
```

## Stop

```bash
docker compose down
```

## Access

- Proxy endpoint: `http://127.0.0.1:${MIXED_PORT}` or `socks5://127.0.0.1:${MIXED_PORT}`
- Mihomo API: `http://127.0.0.1:${CONTROLLER_PORT}`
- Zashboard: `http://127.0.0.1:${DASHBOARD_PORT}`

Recommended zashboard setup URL:

```text
http://127.0.0.1:8080/#/setup?hostname=127.0.0.1&port=19090&secret=change-this-secret&disableUpgradeCore=1
```

## Important

1. Change `MIHOMO_SECRET` in `.env` before exposing the API beyond localhost.
2. The default startup path renders a bootable config with a single `MOCK` proxy when no subscription URL is provided.
3. To use real nodes, set `SUBSCRIPTION_1_URL` to `SUBSCRIPTION_3_URL` in `.env` and recreate the `mihomo` container.
4. If you change `CONTROLLER_PORT`, `DASHBOARD_PORT`, or `MIHOMO_SECRET`, update the zashboard setup URL accordingly.
5. Mihomo is already configured with permissive CORS for the dashboard, so zashboard can connect directly to the published API port.

## Validate config

```bash
docker compose up -d --force-recreate mihomo
docker compose exec mihomo /mihomo -t -d /config -f /config/config.yaml
```

## Optional: enable TUN later

If you later need transparent proxy or gateway-style routing, add `/dev/net/tun`, `NET_ADMIN`, and the related Mihomo `tun:` config explicitly. That still does not require `host` mode.