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

## LAN access for zashboard

Zashboard is commonly accessed from other LAN clients such as phones, tablets, or laptops.

If you want LAN clients to use the dashboard:

1. Open the dashboard with the host machine's LAN IP, not `127.0.0.1`.
2. Set the zashboard `hostname` parameter to the same LAN IP, because the browser connects to the mihomo controller directly.
3. Make sure the host firewall or security group allows `8080` and `19090`.
4. Replace the default `MIHOMO_SECRET` with a strong random value.

Example for a host LAN IP of `192.168.31.10`:

```text
http://192.168.31.10:8080/#/setup?hostname=192.168.31.10&port=19090&secret=your-strong-secret&disableUpgradeCore=1
```

Notes:

1. In this stack, zashboard does not use a reverse proxy to reach mihomo; the browser calls port `19090` directly.
2. Because of that, exposing only `8080` is not enough for LAN clients; they must also be able to reach `19090`.
3. If you want the dashboard reachable on the LAN without exposing the controller port directly, add a reverse proxy layer or restrict access with firewall rules.

## Important

1. Change `MIHOMO_SECRET` in `.env` before exposing the API beyond localhost.
2. The default startup path renders a bootable config with a single `MOCK` proxy when no subscription URL is provided.
3. To use real nodes, set `SUBSCRIPTION_1_URL` to `SUBSCRIPTION_3_URL` in `.env` and recreate the `mihomo` container.
4. If you change `CONTROLLER_PORT`, `DASHBOARD_PORT`, or `MIHOMO_SECRET`, update the zashboard setup URL accordingly.
5. Mihomo is already configured with permissive CORS for the dashboard, so zashboard can connect directly to the published API port.
6. Subscription providers are rendered with `proxy: DIRECT` so their initial download does not deadlock on the default `MATCH,PROXY` rule before any nodes exist.
7. Direct outbound DNS lookups explicitly use the container system resolver, while the default DNS upstreams are set to `doh.pub` and `dns.alidns.com` instead of Cloudflare/Google endpoints that may be unreachable in some networks.
8. When subscriptions are configured, the rendered policy groups also include auto-testing region groups for `香港`, `台湾`, `日本`, `新加坡`, and `美国`, using common tags in node names to filter each region before selecting the fastest node.


## Traffic collector

This stack includes a `traffic-collector` service for long-running traffic attribution. It polls the mihomo `/connections` API, stores per-connection upload/download deltas in SQLite, and persists the database on the host at `./data/traffic.sqlite3`.

Optional `.env` settings:

```env
TRAFFIC_COLLECTOR_INTERVAL=5
TRAFFIC_COLLECTOR_RETENTION_DAYS=30
```

Start or recreate the collector:

```bash
docker compose up -d traffic-collector
```

View collector logs:

```bash
docker compose logs -f traffic-collector
```

Print recent rankings:

```bash
docker compose exec traffic-collector python /app/collector.py report --hours 24 --by app
docker compose exec traffic-collector python /app/collector.py report --hours 24 --by host
docker compose exec traffic-collector python /app/collector.py report --hours 24 --by proxy
docker compose exec traffic-collector python /app/collector.py report --hours 24 --by rule
```

Supported report dimensions are `app`, `host`, `destination`, `rule`, `proxy`, `chain`, `network`, `process`, `source`, and `inbound`.
`app` prefers the process name returned by mihomo. In the current Docker proxy mode, process fields are usually empty, so the collector falls back to domain-based labels such as ChatGPT/OpenAI, GitHub Copilot, VS Code, Microsoft, and GitHub.

To backfill app labels for existing rows after upgrading the collector:

```bash
docker compose exec traffic-collector python /app/collector.py reclassify
```

Notes:

1. The collector samples active connections, so traffic from very short connections that open and close between two samples can be missed.
2. On the first sample after startup, bytes already present on active connections are counted into the database.
3. The current generated mihomo config ends with `MATCH,PROXY`, so `--by rule` becomes more useful after adding more detailed routing rules.
4. Strict host process/app attribution needs host-side process accounting, or a transparent proxy/TUN deployment where mihomo can resolve process metadata.

## Validate config

```bash
docker compose up -d --force-recreate mihomo
docker compose exec mihomo /mihomo -t -d /config -f /config/config.yaml
```

## Optional: enable TUN later

If you later need transparent proxy or gateway-style routing, add `/dev/net/tun`, `NET_ADMIN`, and the related Mihomo `tun:` config explicitly. That still does not require `host` mode.
