import argparse
import json
import sqlite3
from pathlib import Path


SEVERITIES = {"WARN", "ERROR", "CRITICAL"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("sqlite_path")
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args(argv)

    for row in safety_events(args.sqlite_path, args.limit):
        payload = json.loads(row["payload_json"] or "{}")
        detail = payload.get("reason") or payload.get("message") or ""
        print(
            f"{row['event_id']} {row['event_time']} [{payload['severity']}] "
            f"{row['event_type']} {row['symbol']} {row['side'] or '-'} {detail}"
        )
    return 0


def safety_events(sqlite_path: str, limit: int) -> list[sqlite3.Row]:
    uri = f"file:{Path(sqlite_path).resolve()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT event_id, event_type, symbol, side, event_time, payload_json
            FROM live_trade_events
            WHERE payload_json IS NOT NULL
            ORDER BY event_id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    finally:
        connection.close()
    return [row for row in rows if json.loads(row["payload_json"] or "{}").get("severity") in SEVERITIES]


if __name__ == "__main__":
    raise SystemExit(main())
