# mihomo + zashboard Docker Compose 方案

[English](README.md)

这个目录提供了一套基于 Docker Compose 的 mihomo + zashboard 部署方案。
服务运行在 bridge 网络中，不使用 host 模式。

## 文件说明

- `docker-compose.yml`：mihomo、zashboard 和流量采集服务定义
- `.env`：本地运行时环境变量
- `config/mihomo/config.yaml`：本地模式使用的完整 Mihomo 配置
- `config/mihomo/config.example.yaml`：最小可运行配置示例
- `config/mihomo/remote/config.yaml`：在线模式自动维护的远程配置缓存
- `config/mihomo/start-mihomo.sh`：选择本地/在线配置、校验并定时更新
- `config/zashboard/Caddyfile`：zashboard 静态站点配置

## 启动

首次使用先创建环境变量文件：

```bash
cp .env.example .env
```

然后选择一种配置模式。

本地配置模式：

```bash
cp config/mihomo/config.example.yaml config/mihomo/config.yaml
```

在线 Config 订阅模式：在 `.env` 中填写一个直接返回完整 Mihomo YAML 的地址：

```env
MIHOMO_CONFIG_URL="https://example.com/config.yaml"
MIHOMO_CONFIG_UPDATE_INTERVAL=3600
```

最后启动：

```bash
docker compose up -d
```

## 停止

```bash
docker compose down
```

## 访问地址

- 代理端口：`http://127.0.0.1:${MIXED_PORT}` 或 `socks5://127.0.0.1:${MIXED_PORT}`
- Mihomo 控制口：`http://127.0.0.1:${CONTROLLER_PORT}`
- Zashboard 面板：`http://127.0.0.1:${DASHBOARD_PORT}`

推荐直接使用下面这个 zashboard 初始化地址：

```text
http://127.0.0.1:8080/#/setup?hostname=127.0.0.1&port=19090&secret=change-this-secret&disableUpgradeCore=1
```

## 局域网访问 zashboard

zashboard 一般是给局域网里的手机、平板或其他电脑访问的。

如果你要让局域网客户端访问面板：

1. 用宿主机的局域网 IP 打开面板，而不是 `127.0.0.1`。
2. zashboard 初始化参数里的 `hostname` 也要填写宿主机的局域网 IP，因为面板会直接连接 mihomo 控制口。
3. 宿主机防火墙或安全组需要放行 `8080` 和 `19090`。
4. `MIHOMO_SECRET` 不要继续使用默认值，至少改成一个随机长字符串。

例如宿主机 IP 是 `192.168.31.10` 时：

```text
http://192.168.31.10:8080/#/setup?hostname=192.168.31.10&port=19090&secret=your-strong-secret&disableUpgradeCore=1
```

补充说明：

1. 当前方案里 zashboard 不是通过反代访问 mihomo，而是浏览器直接请求 `19090`。
2. 这意味着只开放 `8080` 还不够，局域网客户端还必须能访问 `19090`。
3. 如果你只想给局域网开放面板、不想直接暴露控制口，就需要额外加一层反向代理或防火墙规则。

## 注意事项

1. 如果控制口需要暴露到本机之外，先修改 `.env` 里的 `MIHOMO_SECRET`。
2. `MIHOMO_CONFIG_URL` 为空时使用本地 `config.yaml`；非空时使用在线配置，本地文件不会参与运行。
3. 在线配置下载后会先用 Mihomo 校验，校验成功才会替换缓存；下载或校验失败时会继续使用上一份有效缓存。
4. 如果你修改了 `CONTROLLER_PORT`、`DASHBOARD_PORT` 或 `MIHOMO_SECRET`，记得同步更新 zashboard 初始化地址。
5. `.env` 中的 `MIHOMO_SECRET` 和控制口地址会通过 Mihomo 命令行参数覆盖 YAML 中的 `secret` 与 `external-controller`。


## 流量统计 collector

这套 compose 里包含 `traffic-collector` 服务，用来做长期流量归因。它会定时拉取 mihomo 的 `/connections` API，把每条连接的上传/下载增量写入 SQLite，并把数据库持久化到宿主机的 `./data/traffic.sqlite3`。

可选 `.env` 配置：

```env
TRAFFIC_COLLECTOR_INTERVAL=5
TRAFFIC_COLLECTOR_RETENTION_DAYS=30
```

启动或重建 collector：

```bash
docker compose up -d traffic-collector
```

查看 collector 日志：

```bash
docker compose logs -f traffic-collector
```

查看最近一段时间排行：

```bash
docker compose exec traffic-collector python /app/collector.py report --hours 24 --by app
docker compose exec traffic-collector python /app/collector.py report --hours 24 --by host
docker compose exec traffic-collector python /app/collector.py report --hours 24 --by proxy
docker compose exec traffic-collector python /app/collector.py report --hours 24 --by rule
```

`report` 支持按 `app`、`host`、`destination`、`rule`、`proxy`、`chain`、`network`、`process`、`source`、`inbound` 聚合。
`app` 会优先使用 mihomo 返回的进程名；当前 Docker 代理模式下进程字段通常为空，所以 collector 会按域名把流量归类到 ChatGPT/OpenAI、GitHub Copilot、VS Code、Microsoft、GitHub 等应用/服务。

如果升级 collector 后要把已有历史记录补上应用标签，执行：

```bash
docker compose exec traffic-collector python /app/collector.py reclassify
```

注意：

1. collector 采样的是当前活跃连接，两次采样之间打开又关闭的极短连接可能统计不到。
2. collector 启动后的第一次采样会把当时已经存在的活跃连接字节数计入数据库。
3. 示例 Mihomo 配置最后是 `MATCH,PROXY`，所以 `--by rule` 在补充分流规则后会更有价值。
4. 如果需要严格意义上的“宿主机进程/应用”流量统计，需要在宿主机侧用进程级工具，或改成能让 mihomo 获取进程信息的透明代理/TUN 部署方式。

## 校验配置

```bash
docker compose up -d --force-recreate mihomo
docker compose exec mihomo /mihomo -t -d /config -f /config/.runtime-config.yaml
```

## 自定义 Mihomo 配置

在本地模式中，`config/mihomo/config.yaml` 是配置源。你可以直接编辑它，也可以用已有的完整 Clash/Mihomo YAML 替换它。

为配合当前 Compose 端口映射和 zashboard，配置至少应保留：

```yaml
mixed-port: 7890
external-controller: 0.0.0.0:9090
external-controller-cors:
  allow-origins:
    - "*"
  allow-private-network: true
```

节点、`proxy-providers`、策略组、DNS 和分流规则全部由用户在该文件中自行定义。引用相对路径的 provider 文件时，请放在 `config/mihomo/` 目录下。

改完后重启并校验：

```bash
docker compose restart mihomo
docker compose exec mihomo /mihomo -t -d /config -f /config/.runtime-config.yaml
```

## 在线 Config 订阅

在线模式订阅的是**完整的 Mihomo Config**，不是 `proxy-providers` 节点订阅。URL 必须直接返回一份可用的 Mihomo YAML 配置。

在 `.env` 中配置：

```env
MIHOMO_CONFIG_URL="https://example.com/config.yaml"
MIHOMO_CONFIG_UPDATE_INTERVAL=3600
```

然后重建 Mihomo：

```bash
docker compose up -d --force-recreate mihomo
```

工作方式：

1. 启动时下载完整配置并执行 `/mihomo -t` 校验。
2. 有效配置缓存到 `config/mihomo/remote/config.yaml`，该目录已被 Git 忽略。
3. 按 `MIHOMO_CONFIG_UPDATE_INTERVAL` 秒重新下载；内容有变化且校验通过时自动热重载 Mihomo。
4. 下载失败或新配置无效时保留当前配置，不会用坏配置覆盖缓存。
5. 把更新间隔设为 `0` 可以只在容器启动时更新。

在线配置必须使用容器内 `mixed-port: 7890`，并保留 zashboard 所需的 `external-controller-cors`。`external-controller` 会被启动参数统一覆盖为 `0.0.0.0:9090`。

## 后续可选：开启 TUN

如果后面需要透明代理、旁路由或网关模式，可以再为 mihomo 增加 `/dev/net/tun`、`NET_ADMIN` 以及对应的 `tun:` 配置。
这些都不要求改成 host 网络。
