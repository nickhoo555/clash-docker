# mihomo + zashboard Docker Compose 方案

[English](README.md)

这个目录提供了一套基于 Docker Compose 的 mihomo + zashboard 部署方案。
服务运行在 bridge 网络中，不使用 host 模式。

## 文件说明

- `docker-compose.yml`：mihomo、zashboard 和流量采集服务定义
- `.env`：本地运行时环境变量
- `config/mihomo/configs/local/`：按名称存放本地 Config
- `config/mihomo/configs/remote/`：按名称存放远程订阅 URL 描述文件
- `config/mihomo/configs/cache/`：自动维护的远程 Config 缓存
- `config/mihomo/start-mihomo.sh`：解析选择、加载对应类型并管理更新
- `config/zashboard/Caddyfile`：zashboard 静态站点配置

## 启动

首次使用先创建环境变量文件：

```bash
cp .env.example .env
```

然后选择一种配置模式。

本地配置模式：

```bash
cp config/mihomo/configs/local/default.example.yaml \
  config/mihomo/configs/local/default.yaml
```

```env
MIHOMO_CONFIG=local:default
```

远程 Config 订阅模式：

```bash
cp config/mihomo/configs/remote/example.url.example \
  config/mihomo/configs/remote/home.url
```

把 `home.url` 的唯一一行改为直接返回完整 Mihomo YAML 的 URL，然后选择它：

```env
MIHOMO_CONFIG=remote:home
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
2. `MIHOMO_CONFIG` 必须是 `local:<名称>` 或 `remote:<名称>`；类型与名称共同确定当前 Config。
3. 每个远程 Config 拥有独立缓存；下载或校验失败时只回退到该名称的上一份有效缓存。
4. 如果你修改了 `CONTROLLER_PORT`、`DASHBOARD_PORT` 或 `MIHOMO_SECRET`，记得同步更新 zashboard 初始化地址。
5. `.env` 中的 `MIHOMO_SECRET` 和控制口地址会通过 Mihomo 命令行参数覆盖 YAML 中的 `secret` 与 `external-controller`。
6. 旧的 `config/mihomo/config.yaml` 和 `MIHOMO_CONFIG_URL` 仍兼容，但新配置建议使用命名目录结构。


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

## 多 Config 与切换

选择器格式是 `<类型>:<名称>`：

| 选择器 | 配置来源 |
| --- | --- |
| `local:home` | `configs/local/home.yaml` |
| `local:work` | `configs/local/work.yaml` |
| `remote:airport-a` | `configs/remote/airport-a.url` |
| `remote:airport-b` | `configs/remote/airport-b.url` |

同一时刻只会激活一个 Config。切换时修改 `.env` 中的 `MIHOMO_CONFIG`，然后重建 Mihomo：

```bash
docker compose up -d --force-recreate mihomo
```

也可以单次覆盖选择而不修改 `.env`：

```bash
MIHOMO_CONFIG=remote:airport-b docker compose up -d --force-recreate mihomo
```

名称只能包含字母、数字、`.`、`_` 和 `-`。新增 Config 只需要增加对应文件，不需要修改启动脚本。

## 本地 Config

本地 Config 放在 `config/mihomo/configs/local/<名称>.yaml`。例如 `MIHOMO_CONFIG=local:work` 对应：

```text
config/mihomo/configs/local/work.yaml
```

这些本地 YAML 默认被 Git 忽略，避免提交节点与密钥；`*.example.yaml` 示例文件可以正常纳入版本控制。

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

## 远程 Config 订阅

远程类型订阅的是**完整的 Mihomo Config**，不是 `proxy-providers` 节点订阅。每个远程 Config 使用一个同名 `.url` 描述文件，其中只能有一行 URL。

例如创建 `remote:home`：

```bash
cp config/mihomo/configs/remote/example.url.example \
  config/mihomo/configs/remote/home.url
```

编辑 `home.url`：

```text
https://example.com/config.yaml
```

再编辑 `.env` 并重建：

```env
MIHOMO_CONFIG=remote:home
MIHOMO_CONFIG_UPDATE_INTERVAL=3600
```

```bash
docker compose up -d --force-recreate mihomo
```

工作方式：

1. 启动时下载完整配置并执行 `/mihomo -t` 校验。
2. 有效配置缓存到 `config/mihomo/configs/cache/home.yaml`，缓存目录已被 Git 忽略。
3. 按 `MIHOMO_CONFIG_UPDATE_INTERVAL` 秒重新下载；内容有变化且校验通过时自动热重载 Mihomo。
4. 下载失败或新配置无效时保留当前配置，不会用坏配置覆盖缓存。
5. 把更新间隔设为 `0` 可以只在容器启动时更新。
6. 只有当前激活的远程 Config 会被定时更新。

在线配置必须使用容器内 `mixed-port: 7890`，并保留 zashboard 所需的 `external-controller-cors`。`external-controller` 会被启动参数统一覆盖为 `0.0.0.0:9090`。

## 后续可选：开启 TUN

如果后面需要透明代理、旁路由或网关模式，可以再为 mihomo 增加 `/dev/net/tun`、`NET_ADMIN` 以及对应的 `tun:` 配置。
这些都不要求改成 host 网络。
