# mihomo + zashboard via Docker Compose

[中文说明](README.zh-CN.md)

This stack runs mihomo and zashboard with Docker Compose on a bridge network.
It does not use host networking.

## Files

- `docker-compose.yml`: mihomo, zashboard, and traffic collector services
- `.env`: local runtime variables
- `config/mihomo/config.yaml`: user-maintained complete Mihomo config
- `config/mihomo/config.example.yaml`: minimal working config example
- `config/zashboard/Caddyfile`: static zashboard site config

## Start

Create the local files before the first start:

```bash
cp .env.example .env
cp config/mihomo/config.example.yaml config/mihomo/config.yaml
```

Edit `.env` and `config/mihomo/config.yaml` as needed, then start:

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
2. `config.example.yaml` uses `DIRECT` only. Add your nodes, subscriptions, policy groups, and rules to `config.yaml`.
3. Compose no longer reads or aggregates subscriptions and never generates or overwrites `config.yaml`.
4. If you change `CONTROLLER_PORT`, `DASHBOARD_PORT`, or `MIHOMO_SECRET`, update the zashboard setup URL accordingly.
5. `MIHOMO_SECRET` from `.env` overrides `secret` in the YAML through Mihomo's command-line option.


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
3. The example Mihomo config ends with `MATCH,PROXY`, so `--by rule` becomes more useful after adding more detailed routing rules.
4. Strict host process/app attribution needs host-side process accounting, or a transparent proxy/TUN deployment where mihomo can resolve process metadata.

## Validate config

```bash
docker compose up -d --force-recreate mihomo
docker compose exec mihomo /mihomo -t -d /config -f /config/config.yaml
```

## Custom Mihomo config

`config/mihomo/config.yaml` is the single source of truth. Edit it directly or replace it with an existing complete Clash/Mihomo YAML file.

To work with the current Compose port mappings and zashboard, keep at least:

```yaml
mixed-port: 17890
external-controller: 0.0.0.0:9090
external-controller-cors:
  allow-origins:
    - "*"
  allow-private-network: true
```

Nodes, `proxy-providers`, policy groups, DNS, and routing rules are entirely user-defined. Put provider files referenced with relative paths under `config/mihomo/`.

Restart and validate after editing:

```bash
docker compose restart mihomo
docker compose exec mihomo /mihomo -t -d /config -f /config/config.yaml
```

## Optional: enable TUN later

If you later need transparent proxy or gateway-style routing, add `/dev/net/tun`, `NET_ADMIN`, and the related Mihomo `tun:` config explicitly. That still does not require `host` mode.
