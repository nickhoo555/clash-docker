# mihomo + zashboard Docker Compose 方案

[English](README.md)

这个目录提供了一套基于 Docker Compose 的 mihomo + zashboard 部署方案。
服务运行在 bridge 网络中，不使用 host 模式。

## 文件说明

- `docker-compose.yml`：mihomo 和 zashboard 的服务定义
- `.env`：本地运行时环境变量
- `config/mihomo/config.yaml`：容器启动后自动生成的 mihomo 实际配置
- `config/mihomo/render-config.sh`：按环境变量渲染多订阅配置的启动脚本
- `config/mihomo/config.multi-sub.example.yaml`：多订阅结构示例
- `config/zashboard/Caddyfile`：zashboard 静态站点配置

## 启动

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
2. 当前默认配置会生成一个 `MOCK` 节点，保证在没有订阅时也能正常启动。
3. 要接入真实节点，优先在 `.env` 里填写订阅链接，不需要再手工改主配置结构。
4. 如果你修改了 `CONTROLLER_PORT`、`DASHBOARD_PORT` 或 `MIHOMO_SECRET`，记得同步更新 zashboard 初始化地址。
5. 当前 mihomo 已开启适合面板访问的 CORS 配置，所以 zashboard 直接访问已发布的 API 端口即可。

## 校验配置

```bash
docker compose up -d --force-recreate mihomo
docker compose exec mihomo /mihomo -t -d /config -f /config/config.yaml
```

## 添加多个订阅

现在这套 compose 已经支持通过环境变量传入多个订阅，启动时会自动渲染成 `proxy-providers` 配置。

直接在 [.env](.env) 里填写：

```env
SUBSCRIPTION_1_URL=https://example.com/sub-1
SUBSCRIPTION_2_URL=https://example.com/sub-2
SUBSCRIPTION_3_URL=https://example.com/sub-3
```

留空的订阅会被自动忽略。

推荐用 `proxy-providers` 管理多个订阅，不要把多个订阅展开后的节点直接手工贴进 `proxies:`。

最常见的做法：

1. 在 `.env` 里填写 `SUBSCRIPTION_1_URL` 到 `SUBSCRIPTION_3_URL`。
2. 容器启动时会自动生成 `proxy-providers:`。
3. 每个订阅都会使用单独的缓存文件路径，比如 `./providers/sub1.yaml`。
4. 生成后的策略组会自动把多个 provider 合并到 `PROXY`、`AUTO`、`FALLBACK`，并额外生成 `香港`、`台湾`、`日本`、`新加坡`、`美国` 五个按地区筛选的策略组。
5. 订阅更新会强制走 `DIRECT`，避免 mihomo 启动时因为 provider 尚未拉取完成、却又先命中 `MATCH,PROXY` 规则而卡死。
6. `DIRECT` 出口的域名解析会显式走 `system`，同时默认 DNS 上游改成更容易直连的 `doh.pub` 和 `dns.alidns.com`，避免容器里系统 DNS 可用、但 mihomo 自己的 DoH/DoT 上游不可达。

示例文件已经放在 [config/mihomo/config.multi-sub.example.yaml](config/mihomo/config.multi-sub.example.yaml)。

核心写法如下：

```yaml
proxy-providers:
  sub-a:
    type: http
    url: "https://example.com/sub-a"
    path: ./providers/sub-a.yaml
    interval: 3600
    proxy: DIRECT

  sub-b:
    type: http
    url: "https://example.com/sub-b"
    path: ./providers/sub-b.yaml
    interval: 3600
    proxy: DIRECT

proxy-groups:
  - name: PROXY
    type: select
    proxies:
      - AUTO
      - 香港
      - 台湾
      - 日本
      - 新加坡
      - 美国
      - DIRECT
    use:
      - sub-a
      - sub-b

  - name: 香港
    type: url-test
    url: https://www.gstatic.com/generate_204
    interval: 300
    tolerance: 50
    use:
      - sub-a
      - sub-b
    filter: "香港|HK|Hong Kong|🇭🇰"

  - name: AUTO
    type: url-test
    url: https://www.gstatic.com/generate_204
    interval: 300
    use:
      - sub-a
      - sub-b
```

说明：

1. `SUBSCRIPTION_1_URL` 到 `SUBSCRIPTION_3_URL` 填你的订阅链接。
2. `path` 是 mihomo 在容器内缓存订阅内容的本地文件路径，已经自动分配，必须一订阅一文件。
3. `proxy: DIRECT` 用来保证订阅拉取本身不依赖代理组，避免首次启动时出现循环依赖。
4. `direct-nameserver: system` 用来让直连流量复用容器系统解析器，适合订阅地址能被系统 DNS 正常解析、但默认公共 DoH/DoT 上游不可达的环境。
5. `use` 表示把这些订阅里的节点全部并入当前策略组。
6. 地区组使用 Mihomo 的 `filter` 正则从 provider 里筛节点，组内只保留命中的真实节点，不再额外混入 `AUTO`、`FALLBACK`、`DIRECT`。
7. 地区组本身使用 `url-test`，会在各自地区内自动选延迟最低的节点。
8. `AUTO` 适合全量节点里自动测速选节点，`PROXY` 适合手动切换。
9. 如果三个订阅不够用，继续按相同模式扩展 [config/mihomo/render-config.sh](config/mihomo/render-config.sh) 就行。

改完后执行：

```bash
docker compose up -d --force-recreate mihomo
docker compose exec mihomo /mihomo -t -d /config -f /config/config.yaml
```

如果要看容器最终生成出来的配置，可以执行：

```bash
docker compose exec mihomo sed -n '1,220p' /config/config.yaml
```

## 后续可选：开启 TUN

如果后面需要透明代理、旁路由或网关模式，可以再为 mihomo 增加 `/dev/net/tun`、`NET_ADMIN` 以及对应的 `tun:` 配置。
这些都不要求改成 host 网络。