# mihomo + zashboard via Docker Compose

[中文说明](README.zh-CN.md)

This stack runs mihomo and zashboard with Docker Compose on a bridge network.
It does not use host networking.

## Files

- `docker-compose.yml`: mihomo, zashboard, and traffic collector services
- `.env`: local runtime variables
- `config/mihomo/configs/local/`: named local configs
- `config/mihomo/configs/remote/`: named remote-subscription URL descriptors
- `config/mihomo/configs/cache/`: automatically managed remote config caches
- `config/mihomo/start-mihomo.sh`: resolves the selection, loads its type, and manages updates
- `config/zashboard/Caddyfile`: static zashboard site config

## Start

Create the environment file first:

```bash
cp .env.example .env
```

Then select one config mode.

Local config mode:

```bash
cp config/mihomo/configs/local/default.example.yaml \
  config/mihomo/configs/local/default.yaml
```

```env
MIHOMO_CONFIG=local:default
```

Remote config subscription mode:

```bash
cp config/mihomo/configs/remote/example.url.example \
  config/mihomo/configs/remote/home.url
```

Change the only line in `home.url` to a URL that directly returns a complete Mihomo YAML document, then select it:

```env
MIHOMO_CONFIG=remote:home
MIHOMO_CONFIG_UPDATE_INTERVAL=3600
```

Finally, start the stack:

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
2. `MIHOMO_CONFIG` must be `local:<name>` or `remote:<name>`; the type and name identify the active config.
3. Each remote config has an independent cache. Download or validation failures fall back only to that name's last valid cache.
4. If you change `CONTROLLER_PORT`, `DASHBOARD_PORT`, or `MIHOMO_SECRET`, update the zashboard setup URL accordingly.
5. `MIHOMO_SECRET` and the controller address override YAML `secret` and `external-controller` through Mihomo command-line options.
6. The old `config/mihomo/config.yaml` and `MIHOMO_CONFIG_URL` remain compatible, but new configs should use the named directory layout.


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
docker compose exec mihomo /mihomo -t -d /config -f /config/.runtime-config.yaml
```

## Multiple configs and switching

The selector format is `<type>:<name>`:

| Selector | Config source |
| --- | --- |
| `local:home` | `configs/local/home.yaml` |
| `local:work` | `configs/local/work.yaml` |
| `remote:airport-a` | `configs/remote/airport-a.url` |
| `remote:airport-b` | `configs/remote/airport-b.url` |

Only one config is active at a time. To switch, change `MIHOMO_CONFIG` in `.env` and recreate Mihomo:

```bash
docker compose up -d --force-recreate mihomo
```

You can also override the selection once without editing `.env`:

```bash
MIHOMO_CONFIG=remote:airport-b docker compose up -d --force-recreate mihomo
```

Names may contain only letters, numbers, `.`, `_`, and `-`. Adding a config requires only a corresponding file, not a startup-script change.

## Local configs

Put local configs at `config/mihomo/configs/local/<name>.yaml`. For example, `MIHOMO_CONFIG=local:work` resolves to:

```text
config/mihomo/configs/local/work.yaml
```

Local YAML files are ignored by Git by default to avoid committing nodes and credentials; `*.example.yaml` files remain trackable.

To work with the current Compose port mappings and zashboard, keep at least:

```yaml
mixed-port: 7890
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
docker compose exec mihomo /mihomo -t -d /config -f /config/.runtime-config.yaml
```

## Remote config subscriptions

The remote type subscribes to the **complete Mihomo config**, not a `proxy-providers` node subscription. Each remote config has a same-named `.url` descriptor containing exactly one URL.

For example, create `remote:home`:

```bash
cp config/mihomo/configs/remote/example.url.example \
  config/mihomo/configs/remote/home.url
```

Edit `home.url`:

```text
https://example.com/config.yaml
```

Then edit `.env` and recreate Mihomo:

```env
MIHOMO_CONFIG=remote:home
MIHOMO_CONFIG_UPDATE_INTERVAL=3600
```

```bash
docker compose up -d --force-recreate mihomo
```

How it works:

1. On startup, the complete config is downloaded and checked with `/mihomo -t`.
2. A valid config is cached at `config/mihomo/configs/cache/home.yaml`; the cache directory is ignored by Git.
3. It is downloaded again every `MIHOMO_CONFIG_UPDATE_INTERVAL` seconds. Changed, valid content triggers a Mihomo hot reload.
4. Download failures or invalid updates leave the current config and cache untouched.
5. Set the interval to `0` to update only when the container starts.
6. Only the active remote config is refreshed periodically.

The online config must use the container port `mixed-port: 7890` and keep `external-controller-cors` for zashboard. `external-controller` is overridden at startup to `0.0.0.0:9090`.

## Optional: enable TUN later

If you later need transparent proxy or gateway-style routing, add `/dev/net/tun`, `NET_ADMIN`, and the related Mihomo `tun:` config explicitly. That still does not require `host` mode.
