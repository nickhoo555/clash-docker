#!/usr/bin/env python3
import argparse
import json
import os
import signal
import sqlite3
import sys
import time
from hashlib import sha1
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_API_URL = "http://127.0.0.1:9090"
DEFAULT_DB_PATH = "/data/traffic.sqlite3"
DEFAULT_INTERVAL_SECONDS = 5
DEFAULT_TIMEOUT_SECONDS = 5
DEFAULT_RETENTION_DAYS = 30

STOP_REQUESTED = False

APP_PATTERNS = [
    ("GitHub Copilot", ["githubcopilot.com", "copilot-telemetry.githubusercontent.com"]),
    ("ChatGPT/OpenAI", ["chatgpt.com", "openai.com", "oaistatic.com", "oaiusercontent.com"]),
    ("VS Code", ["vscode-cdn.net", "visualstudio.com", "applicationinsights.azure.com", "exp-tas.com"]),
    ("Microsoft", ["microsoft.com", "microsoftonline.com", "windows.net", "events.data.microsoft.com"]),
    ("GitHub", ["github.com", "githubusercontent.com", "githubassets.com"]),
    ("Sentry", ["sentry.io"]),
    ("Subscription", ["sub-store"]),
]


def handle_stop(_signum, _frame):
    global STOP_REQUESTED
    STOP_REQUESTED = True


def getenv_int(name, default, minimum=None):
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        print(f"Invalid integer for {name}: {raw!r}; using {default}", file=sys.stderr)
        return default
    if minimum is not None and value < minimum:
        print(f"{name} must be >= {minimum}; using {default}", file=sys.stderr)
        return default
    return value


def open_db(path):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.execute("PRAGMA busy_timeout=5000")
    migrate(db)
    return db


def migrate(db):
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS connection_state (
          connection_id TEXT PRIMARY KEY,
          first_seen INTEGER NOT NULL,
          last_seen INTEGER NOT NULL,
          upload_total INTEGER NOT NULL,
          download_total INTEGER NOT NULL,
          host TEXT,
          destination_ip TEXT,
          destination_port TEXT,
          network TEXT,
          conn_type TEXT,
          rule TEXT,
          rule_payload TEXT,
          proxy_chain TEXT,
          proxy TEXT,
          source_ip TEXT,
          source_port TEXT,
          inbound_name TEXT,
          process TEXT,
          process_path TEXT,
          app TEXT
        );

        CREATE TABLE IF NOT EXISTS traffic_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          sampled_at INTEGER NOT NULL,
          connection_id TEXT NOT NULL,
          host TEXT,
          destination_ip TEXT,
          destination_port TEXT,
          network TEXT,
          conn_type TEXT,
          rule TEXT,
          rule_payload TEXT,
          proxy_chain TEXT,
          proxy TEXT,
          source_ip TEXT,
          source_port TEXT,
          inbound_name TEXT,
          process TEXT,
          process_path TEXT,
          app TEXT,
          upload_delta INTEGER NOT NULL,
          download_delta INTEGER NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_traffic_events_time
          ON traffic_events(sampled_at);
        CREATE INDEX IF NOT EXISTS idx_traffic_events_host
          ON traffic_events(host);
        CREATE INDEX IF NOT EXISTS idx_traffic_events_rule
          ON traffic_events(rule, rule_payload);
        CREATE INDEX IF NOT EXISTS idx_traffic_events_proxy
          ON traffic_events(proxy);

        CREATE TABLE IF NOT EXISTS collector_samples (
          sampled_at INTEGER PRIMARY KEY,
          active_connections INTEGER NOT NULL,
          api_upload_total INTEGER,
          api_download_total INTEGER,
          delta_upload INTEGER NOT NULL,
          delta_download INTEGER NOT NULL,
          error TEXT
        );
        """
    )
    ensure_columns(
        db,
        "connection_state",
        {
            "source_ip": "TEXT",
            "source_port": "TEXT",
            "inbound_name": "TEXT",
            "process": "TEXT",
            "process_path": "TEXT",
            "app": "TEXT",
        },
    )
    ensure_columns(
        db,
        "traffic_events",
        {
            "source_ip": "TEXT",
            "source_port": "TEXT",
            "inbound_name": "TEXT",
            "process": "TEXT",
            "process_path": "TEXT",
            "app": "TEXT",
        },
    )
    db.execute("CREATE INDEX IF NOT EXISTS idx_traffic_events_app ON traffic_events(app)")
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_traffic_events_process ON traffic_events(process)"
    )
    db.commit()


def ensure_columns(db, table, columns):
    existing = {
        row["name"]
        for row in db.execute(f"PRAGMA table_info({table})").fetchall()
    }
    for name, definition in columns.items():
        if name not in existing:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def fetch_connections(api_url, secret, timeout):
    url = api_url.rstrip("/") + "/connections"
    headers = {"Accept": "application/json"}
    if secret:
        headers["Authorization"] = f"Bearer {secret}"

    request = Request(url, headers=headers)
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def as_int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def as_text(value):
    if value is None:
        return ""
    return str(value)


def classify_app(host, process, process_path):
    process = as_text(process).strip()
    process_path = as_text(process_path).strip()
    if process:
        return process
    if process_path:
        return os.path.basename(process_path.rstrip("/")) or process_path

    normalized_host = as_text(host).strip().lower().rstrip(".")
    for label, patterns in APP_PATTERNS:
        for pattern in patterns:
            normalized_pattern = pattern.lower()
            if (
                normalized_host == normalized_pattern
                or normalized_host.endswith("." + normalized_pattern)
                or normalized_pattern in normalized_host
            ):
                return label

    return host or "(unknown)"


def connection_id_for(connection):
    value = connection.get("id")
    if value:
        return str(value)

    metadata = connection.get("metadata") or {}
    seed = {
        "start": connection.get("start"),
        "network": metadata.get("network"),
        "type": metadata.get("type"),
        "sourceIP": metadata.get("sourceIP"),
        "sourcePort": metadata.get("sourcePort"),
        "destinationIP": metadata.get("destinationIP"),
        "destinationPort": metadata.get("destinationPort"),
        "host": metadata.get("host"),
    }
    encoded = json.dumps(seed, sort_keys=True, separators=(",", ":"))
    return "synthetic-" + sha1(encoded.encode("utf-8")).hexdigest()


def parse_connection(connection):
    metadata = connection.get("metadata") or {}
    chains = connection.get("chains") or []
    if not isinstance(chains, list):
        chains = [chains]
    chains = [as_text(item) for item in chains if as_text(item)]

    host = (
        metadata.get("host")
        or metadata.get("destinationHost")
        or metadata.get("sniffHost")
        or metadata.get("remoteDestination")
        or ""
    )
    destination_ip = metadata.get("destinationIP") or metadata.get("remoteAddress") or ""
    destination_port = metadata.get("destinationPort") or metadata.get("remotePort") or ""
    process = as_text(metadata.get("process"))
    process_path = as_text(metadata.get("processPath"))

    return {
        "connection_id": connection_id_for(connection),
        "upload_total": as_int(connection.get("upload")),
        "download_total": as_int(connection.get("download")),
        "host": as_text(host),
        "destination_ip": as_text(destination_ip),
        "destination_port": as_text(destination_port),
        "network": as_text(metadata.get("network") or connection.get("network")),
        "conn_type": as_text(metadata.get("type") or connection.get("type")),
        "rule": as_text(connection.get("rule")),
        "rule_payload": as_text(connection.get("rulePayload")),
        "proxy_chain": " > ".join(chains),
        "proxy": chains[0] if chains else "",
        "source_ip": as_text(metadata.get("sourceIP")),
        "source_port": as_text(metadata.get("sourcePort")),
        "inbound_name": as_text(metadata.get("inboundName")),
        "process": process,
        "process_path": process_path,
        "app": classify_app(host, process, process_path),
    }


def record_error_sample(db, sampled_at, message):
    db.execute(
        """
        INSERT OR REPLACE INTO collector_samples (
          sampled_at, active_connections, api_upload_total, api_download_total,
          delta_upload, delta_download, error
        ) VALUES (?, 0, NULL, NULL, 0, 0, ?)
        """,
        (sampled_at, message[:500]),
    )
    db.commit()


def record_sample(db, payload, sampled_at):
    if not isinstance(payload, dict):
        payload = {}
    raw_connections = payload.get("connections") or []
    if not isinstance(raw_connections, list):
        raw_connections = []

    connections = [parse_connection(item) for item in raw_connections if isinstance(item, dict)]
    api_upload_total = as_int(payload.get("uploadTotal"))
    api_download_total = as_int(payload.get("downloadTotal"))
    delta_upload_total = 0
    delta_download_total = 0

    with db:
        for item in connections:
            previous = db.execute(
                """
                SELECT upload_total, download_total
                FROM connection_state
                WHERE connection_id = ?
                """,
                (item["connection_id"],),
            ).fetchone()

            if previous is None:
                upload_delta = item["upload_total"]
                download_delta = item["download_total"]
                first_seen = sampled_at
            else:
                upload_delta = item["upload_total"] - previous["upload_total"]
                download_delta = item["download_total"] - previous["download_total"]
                if upload_delta < 0:
                    upload_delta = item["upload_total"]
                if download_delta < 0:
                    download_delta = item["download_total"]
                first_seen = None

            delta_upload_total += upload_delta
            delta_download_total += download_delta

            if upload_delta > 0 or download_delta > 0:
                db.execute(
                    """
                    INSERT INTO traffic_events (
                      sampled_at, connection_id, host, destination_ip, destination_port,
                      network, conn_type, rule, rule_payload, proxy_chain, proxy,
                      source_ip, source_port, inbound_name, process, process_path, app,
                      upload_delta, download_delta
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sampled_at,
                        item["connection_id"],
                        item["host"],
                        item["destination_ip"],
                        item["destination_port"],
                        item["network"],
                        item["conn_type"],
                        item["rule"],
                        item["rule_payload"],
                        item["proxy_chain"],
                        item["proxy"],
                        item["source_ip"],
                        item["source_port"],
                        item["inbound_name"],
                        item["process"],
                        item["process_path"],
                        item["app"],
                        upload_delta,
                        download_delta,
                    ),
                )

            if first_seen is None:
                db.execute(
                    """
                    UPDATE connection_state
                    SET last_seen = ?,
                        upload_total = ?,
                        download_total = ?,
                        host = ?,
                        destination_ip = ?,
                        destination_port = ?,
                        network = ?,
                        conn_type = ?,
                        rule = ?,
                        rule_payload = ?,
                        proxy_chain = ?,
                        proxy = ?,
                        source_ip = ?,
                        source_port = ?,
                        inbound_name = ?,
                        process = ?,
                        process_path = ?,
                        app = ?
                    WHERE connection_id = ?
                    """,
                    (
                        sampled_at,
                        item["upload_total"],
                        item["download_total"],
                        item["host"],
                        item["destination_ip"],
                        item["destination_port"],
                        item["network"],
                        item["conn_type"],
                        item["rule"],
                        item["rule_payload"],
                        item["proxy_chain"],
                        item["proxy"],
                        item["source_ip"],
                        item["source_port"],
                        item["inbound_name"],
                        item["process"],
                        item["process_path"],
                        item["app"],
                        item["connection_id"],
                    ),
                )
            else:
                db.execute(
                    """
                    INSERT INTO connection_state (
                      connection_id, first_seen, last_seen, upload_total, download_total,
                      host, destination_ip, destination_port, network, conn_type,
                      rule, rule_payload, proxy_chain, proxy,
                      source_ip, source_port, inbound_name, process, process_path, app
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item["connection_id"],
                        first_seen,
                        sampled_at,
                        item["upload_total"],
                        item["download_total"],
                        item["host"],
                        item["destination_ip"],
                        item["destination_port"],
                        item["network"],
                        item["conn_type"],
                        item["rule"],
                        item["rule_payload"],
                        item["proxy_chain"],
                        item["proxy"],
                        item["source_ip"],
                        item["source_port"],
                        item["inbound_name"],
                        item["process"],
                        item["process_path"],
                        item["app"],
                    ),
                )

        db.execute(
            """
            INSERT OR REPLACE INTO collector_samples (
              sampled_at, active_connections, api_upload_total, api_download_total,
              delta_upload, delta_download, error
            ) VALUES (?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                sampled_at,
                len(connections),
                api_upload_total,
                api_download_total,
                delta_upload_total,
                delta_download_total,
            ),
        )

    return len(connections), delta_upload_total, delta_download_total


def cleanup(db, retention_days, now):
    if retention_days <= 0:
        return
    cutoff = now - retention_days * 86400
    with db:
        db.execute("DELETE FROM traffic_events WHERE sampled_at < ?", (cutoff,))
        db.execute("DELETE FROM collector_samples WHERE sampled_at < ?", (cutoff,))
        db.execute("DELETE FROM connection_state WHERE last_seen < ?", (cutoff,))


def collect(args):
    signal.signal(signal.SIGTERM, handle_stop)
    signal.signal(signal.SIGINT, handle_stop)

    db_path = args.db or os.getenv("TRAFFIC_COLLECTOR_DB", DEFAULT_DB_PATH)
    api_url = args.api_url or os.getenv("MIHOMO_API_URL", DEFAULT_API_URL)
    secret = args.secret if args.secret is not None else os.getenv("MIHOMO_SECRET", "")
    interval = args.interval or getenv_int(
        "TRAFFIC_COLLECTOR_INTERVAL", DEFAULT_INTERVAL_SECONDS, minimum=1
    )
    timeout = args.timeout or getenv_int(
        "TRAFFIC_COLLECTOR_TIMEOUT", DEFAULT_TIMEOUT_SECONDS, minimum=1
    )
    retention_days = args.retention_days
    if retention_days is None:
        retention_days = getenv_int(
            "TRAFFIC_COLLECTOR_RETENTION_DAYS", DEFAULT_RETENTION_DAYS, minimum=0
        )

    db = open_db(db_path)
    cleanup_every = max(1, 3600 // interval)
    sample_count = 0

    print(
        f"collecting mihomo traffic from {api_url} every {interval}s into {db_path}",
        flush=True,
    )

    while not STOP_REQUESTED:
        sampled_at = int(time.time())
        try:
            payload = fetch_connections(api_url, secret, timeout)
            active, upload_delta, download_delta = record_sample(db, payload, sampled_at)
            sample_count += 1
            if sample_count == 1 or sample_count % 12 == 0:
                transferred = format_bytes(upload_delta + download_delta)
                print(
                    f"sample={sample_count} active={active} delta={transferred}",
                    flush=True,
                )
            if sample_count % cleanup_every == 0:
                cleanup(db, retention_days, sampled_at)
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            print(f"collector error: {message}", file=sys.stderr, flush=True)
            record_error_sample(db, sampled_at, message)

        deadline = time.time() + interval
        while not STOP_REQUESTED and time.time() < deadline:
            time.sleep(min(0.5, deadline - time.time()))

    db.close()
    print("collector stopped", flush=True)


def format_bytes(value):
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    size = float(value or 0)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} TiB"


def report(args):
    db_path = args.db or os.getenv("TRAFFIC_COLLECTOR_DB", DEFAULT_DB_PATH)
    db = open_db(db_path)
    cutoff = int(time.time()) - args.hours * 3600
    group_expr = group_expression(args.by)
    rows = db.execute(
        f"""
        SELECT
          {group_expr} AS bucket,
          SUM(upload_delta) AS upload,
          SUM(download_delta) AS download,
          SUM(upload_delta + download_delta) AS total,
          COUNT(DISTINCT connection_id) AS connections
        FROM traffic_events
        WHERE sampled_at >= ?
        GROUP BY bucket
        ORDER BY total DESC
        LIMIT ?
        """,
        (cutoff, args.limit),
    ).fetchall()

    if not rows:
        print(f"No traffic events found in the last {args.hours}h.")
        return

    print(f"Top {len(rows)} by {args.by} in the last {args.hours}h")
    print(f"{'rank':>4}  {'total':>11}  {'download':>11}  {'upload':>11}  {'conns':>6}  bucket")
    for index, row in enumerate(rows, start=1):
        print(
            f"{index:>4}  "
            f"{format_bytes(row['total']):>11}  "
            f"{format_bytes(row['download']):>11}  "
            f"{format_bytes(row['upload']):>11}  "
            f"{row['connections']:>6}  "
            f"{row['bucket']}"
        )


def reclassify(args):
    db_path = args.db or os.getenv("TRAFFIC_COLLECTOR_DB", DEFAULT_DB_PATH)
    db = open_db(db_path)
    updated_events = 0
    updated_state = 0

    with db:
        rows = db.execute(
            """
            SELECT id, host, process, process_path
            FROM traffic_events
            WHERE COALESCE(app, '') = ''
            """
        ).fetchall()
        for row in rows:
            app = classify_app(row["host"], row["process"], row["process_path"])
            db.execute("UPDATE traffic_events SET app = ? WHERE id = ?", (app, row["id"]))
            updated_events += 1

        rows = db.execute(
            """
            SELECT connection_id, host, process, process_path
            FROM connection_state
            WHERE COALESCE(app, '') = ''
            """
        ).fetchall()
        for row in rows:
            app = classify_app(row["host"], row["process"], row["process_path"])
            db.execute(
                "UPDATE connection_state SET app = ? WHERE connection_id = ?",
                (app, row["connection_id"]),
            )
            updated_state += 1

    print(f"reclassified traffic_events={updated_events} connection_state={updated_state}")


def group_expression(name):
    expressions = {
        "host": "COALESCE(NULLIF(host, ''), NULLIF(destination_ip, ''), '(unknown)')",
        "destination": (
            "COALESCE(NULLIF(destination_ip, ''), NULLIF(host, ''), '(unknown)')"
            " || CASE WHEN COALESCE(destination_port, '') = '' THEN ''"
            " ELSE ':' || destination_port END"
        ),
        "rule": (
            "CASE"
            " WHEN COALESCE(rule, '') = '' THEN '(unknown)'"
            " WHEN COALESCE(rule_payload, '') = '' THEN rule"
            " ELSE rule || ',' || rule_payload"
            " END"
        ),
        "proxy": "COALESCE(NULLIF(proxy, ''), '(unknown)')",
        "chain": "COALESCE(NULLIF(proxy_chain, ''), '(unknown)')",
        "network": "COALESCE(NULLIF(network, ''), '(unknown)')",
        "app": (
            "COALESCE(NULLIF(app, ''), NULLIF(process, ''),"
            " NULLIF(host, ''), NULLIF(destination_ip, ''), '(unknown)')"
        ),
        "process": (
            "COALESCE(NULLIF(process, ''), NULLIF(process_path, ''), '(unknown)')"
        ),
        "source": (
            "COALESCE(NULLIF(source_ip, ''), '(unknown)')"
            " || CASE WHEN COALESCE(source_port, '') = '' THEN ''"
            " ELSE ':' || source_port END"
        ),
        "inbound": "COALESCE(NULLIF(inbound_name, ''), '(unknown)')",
    }
    return expressions[name]


def build_parser():
    parser = argparse.ArgumentParser(description="Mihomo connection traffic collector")
    subparsers = parser.add_subparsers(dest="command")

    collect_parser = subparsers.add_parser("collect", help="run the collector loop")
    collect_parser.add_argument("--api-url")
    collect_parser.add_argument("--secret")
    collect_parser.add_argument("--db")
    collect_parser.add_argument("--interval", type=int)
    collect_parser.add_argument("--timeout", type=int)
    collect_parser.add_argument("--retention-days", type=int)
    collect_parser.set_defaults(func=collect)

    report_parser = subparsers.add_parser("report", help="print a traffic summary")
    report_parser.add_argument("--db")
    report_parser.add_argument("--hours", type=int, default=24)
    report_parser.add_argument("--limit", type=int, default=20)
    report_parser.add_argument(
        "--by",
        choices=[
            "app",
            "host",
            "destination",
            "rule",
            "proxy",
            "chain",
            "network",
            "process",
            "source",
            "inbound",
        ],
        default="host",
    )
    report_parser.set_defaults(func=report)

    reclassify_parser = subparsers.add_parser(
        "reclassify", help="backfill app labels for existing rows"
    )
    reclassify_parser.add_argument("--db")
    reclassify_parser.set_defaults(func=reclassify)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    if args.command is None:
        args = parser.parse_args(["collect"])
    args.func(args)


if __name__ == "__main__":
    main()
