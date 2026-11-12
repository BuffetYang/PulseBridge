"""SQLite 存储层。

所有数据落在单个数据库文件中，采用 WAL 模式，接收线程与 UI 线程共享连接，
通过一把可重入锁串行化访问（每秒最多一次写入，无性能压力）。
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS samples (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid        TEXT NOT NULL UNIQUE,
    type        TEXT NOT NULL,
    start_ts    INTEGER NOT NULL,
    end_ts      INTEGER NOT NULL,
    value       REAL,
    value_text  TEXT,
    unit        TEXT,
    source      TEXT,
    device      TEXT,
    metadata    TEXT,
    received_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_samples_type_start ON samples(type, start_ts);
CREATE INDEX IF NOT EXISTS idx_samples_start ON samples(start_ts);

CREATE TABLE IF NOT EXISTS workouts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid          TEXT NOT NULL UNIQUE,
    activity_type TEXT NOT NULL,
    start_ts      INTEGER NOT NULL,
    end_ts        INTEGER NOT NULL,
    duration_s    REAL,
    distance_m    REAL,
    energy_kcal   REAL,
    avg_hr        REAL,
    max_hr        REAL,
    source        TEXT,
    metadata      TEXT,
    received_at   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_workouts_start ON workouts(start_ts);

CREATE TABLE IF NOT EXISTS ingest_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at   INTEGER NOT NULL,
    remote        TEXT,
    device        TEXT,
    samples_new   INTEGER NOT NULL DEFAULT 0,
    samples_dupe  INTEGER NOT NULL DEFAULT 0,
    workouts_new  INTEGER NOT NULL DEFAULT 0,
    workouts_dupe INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'ok',
    message       TEXT
);
CREATE INDEX IF NOT EXISTS idx_ingest_received ON ingest_events(received_at);
"""


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(self.path), check_same_thread=False, timeout=10.0
        )
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(_SCHEMA)
            self._conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------
    def insert_samples(self, samples: Iterable[dict[str, Any]]) -> tuple[int, int]:
        rows = list(samples)
        if not rows:
            return 0, 0
        inserted = 0
        now = int(time.time())
        with self._lock, self._conn:
            for row in rows:
                cur = self._conn.execute(
                    """
                    INSERT OR IGNORE INTO samples
                        (uuid, type, start_ts, end_ts, value, value_text, unit,
                         source, device, metadata, received_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["uuid"],
                        row["type"],
                        int(row["start_ts"]),
                        int(row["end_ts"]),
                        row.get("value"),
                        row.get("value_text"),
                        row.get("unit"),
                        row.get("source"),
                        row.get("device"),
                        json.dumps(row["metadata"], ensure_ascii=False)
                        if row.get("metadata")
                        else None,
                        int(row.get("received_at") or now),
                    ),
                )
                inserted += cur.rowcount
        return inserted, len(rows) - inserted

    def insert_workouts(self, workouts: Iterable[dict[str, Any]]) -> tuple[int, int]:
        rows = list(workouts)
        if not rows:
            return 0, 0
        inserted = 0
        now = int(time.time())
        with self._lock, self._conn:
            for row in rows:
                cur = self._conn.execute(
                    """
                    INSERT OR IGNORE INTO workouts
                        (uuid, activity_type, start_ts, end_ts, duration_s,
                         distance_m, energy_kcal, avg_hr, max_hr, source,
                         metadata, received_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["uuid"],
                        row["activity_type"],
                        int(row["start_ts"]),
                        int(row["end_ts"]),
                        row.get("duration_s"),
                        row.get("distance_m"),
                        row.get("energy_kcal"),
                        row.get("avg_hr"),
                        row.get("max_hr"),
                        row.get("source"),
                        json.dumps(row["metadata"], ensure_ascii=False)
                        if row.get("metadata")
                        else None,
                        int(row.get("received_at") or now),
                    ),
                )
                inserted += cur.rowcount
        return inserted, len(rows) - inserted

    def record_ingest(
        self,
        remote: str | None,
        device: str | None,
        samples_new: int,
        samples_dupe: int,
        workouts_new: int,
        workouts_dupe: int,
        status: str = "ok",
        message: str | None = None,
        received_at: int | None = None,
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO ingest_events
                    (received_at, remote, device, samples_new, samples_dupe,
                     workouts_new, workouts_dupe, status, message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(received_at or time.time()),
                    remote,
                    device,
                    samples_new,
                    samples_dupe,
                    workouts_new,
                    workouts_dupe,
                    status,
                    message,
                ),
            )

    # ------------------------------------------------------------------
    # 读取：单点/区间
    # ------------------------------------------------------------------
    def _rows(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._conn.execute(sql, params).fetchall())

    def latest_sample(self, type_: str, since_ts: int | None = None) -> dict | None:
        sql = "SELECT * FROM samples WHERE type = ?"
        params: list[Any] = [type_]
        if since_ts is not None:
            sql += " AND start_ts >= ?"
            params.append(since_ts)
        sql += " ORDER BY start_ts DESC LIMIT 1"
        rows = self._rows(sql, tuple(params))
        return dict(rows[0]) if rows else None

    def samples_between(
        self, type_: str, start_ts: int, end_ts: int | None = None, limit: int = 20000
    ) -> list[dict]:
        sql = "SELECT * FROM samples WHERE type = ? AND start_ts >= ?"
        params: list[Any] = [type_, start_ts]
        if end_ts is not None:
            sql += " AND start_ts <= ?"
            params.append(end_ts)
        sql += " ORDER BY start_ts ASC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self._rows(sql, tuple(params))]

    def sleep_samples(self, since_ts: int) -> list[dict]:
        rows = self._rows(
            "SELECT * FROM samples WHERE type = 'sleep_analysis' AND end_ts >= ? "
            "ORDER BY start_ts ASC",
            (since_ts,),
        )
        return [dict(r) for r in rows]

    def workout_rows(self, since_ts: int, limit: int = 200) -> list[dict]:
        rows = self._rows(
            "SELECT * FROM workouts WHERE start_ts >= ? ORDER BY start_ts DESC LIMIT ?",
            (since_ts, limit),
        )
        return [dict(r) for r in rows]

    def daily_cumulative(self, type_: str, since_ts: int) -> list[dict]:
        """按自然日汇总累计型指标；多来源时取各来源合计的最大值，避免重复计数。"""
        rows = self._rows(
            """
            SELECT day, MAX(total) AS value FROM (
                SELECT date(start_ts, 'unixepoch', 'localtime') AS day,
                       ifnull(source, '') AS src,
                       SUM(value) AS total
                FROM samples
                WHERE type = ? AND start_ts >= ? AND value IS NOT NULL
                GROUP BY day, src
            )
            GROUP BY day
            ORDER BY day
            """,
            (type_, since_ts),
        )
        return [dict(r) for r in rows]

    def daily_stats(self, type_: str, since_ts: int) -> list[dict]:
        rows = self._rows(
            """
            SELECT day, AVG(value) AS avg, MIN(value) AS min,
                   MAX(value) AS max, SUM(value) AS total, COUNT(*) AS n
            FROM (
                SELECT date(start_ts, 'unixepoch', 'localtime') AS day, value
                FROM samples
                WHERE type = ? AND start_ts >= ? AND value IS NOT NULL
            )
            GROUP BY day
            ORDER BY day
            """,
            (type_, since_ts),
        )
        return [dict(r) for r in rows]

    def distinct_sources(self, type_: str, since_ts: int) -> list[str]:
        rows = self._rows(
            "SELECT DISTINCT source FROM samples "
            "WHERE type = ? AND start_ts >= ? AND source IS NOT NULL",
            (type_, since_ts),
        )
        return [str(r["source"]) for r in rows if r["source"]]

    # ------------------------------------------------------------------
    # 读取：汇总
    # ------------------------------------------------------------------
    def stats(self) -> dict[str, Any]:
        with self._lock:
            samples = self._conn.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
            workouts = self._conn.execute("SELECT COUNT(*) FROM workouts").fetchone()[0]
            first = self._conn.execute("SELECT MIN(start_ts) FROM samples").fetchone()[0]
            last_event = self._conn.execute(
                "SELECT * FROM ingest_events ORDER BY received_at DESC LIMIT 1"
            ).fetchone()
            last_ok = self._conn.execute(
                "SELECT MAX(received_at) FROM ingest_events WHERE status = 'ok'"
            ).fetchone()[0]
        return {
            "samples": samples,
            "workouts": workouts,
            "first_ts": first,
            "last_sync_ts": last_ok,
            "last_event": dict(last_event) if last_event else None,
        }

    def recent_events(self, limit: int = 8) -> list[dict]:
        rows = self._rows(
            "SELECT * FROM ingest_events ORDER BY received_at DESC LIMIT ?", (limit,)
        )
        return [dict(r) for r in rows]

    def sample_type_counts(self) -> dict[str, int]:
        rows = self._rows(
            "SELECT type, COUNT(*) AS n FROM samples GROUP BY type ORDER BY n DESC"
        )
        return {str(r["type"]): int(r["n"]) for r in rows}

    def export_payload(self, since_ts: int) -> dict[str, Any]:
        samples = [
            dict(r)
            for r in self._rows(
                "SELECT * FROM samples WHERE start_ts >= ? ORDER BY start_ts", (since_ts,)
            )
        ]
        workouts = [
            dict(r)
            for r in self._rows(
                "SELECT * FROM workouts WHERE start_ts >= ? ORDER BY start_ts", (since_ts,)
            )
        ]
        for row in samples + workouts:
            if row.get("metadata"):
                try:
                    row["metadata"] = json.loads(row["metadata"])
                except (TypeError, ValueError):
                    pass
        return {
            "exported_at": int(time.time()),
            "since": since_ts,
            "samples": samples,
            "workouts": workouts,
        }

    # ------------------------------------------------------------------
    # 维护
    # ------------------------------------------------------------------
    def delete_by_uuids(self, uuids: Iterable[str]) -> int:
        """按 UUID 删除样本/运动（PulsHealth 删除行使用）。"""
        values = {str(u).lower() for u in uuids}
        if not values:
            return 0
        deleted = 0
        with self._lock, self._conn:
            for uuid in values:
                deleted += self._conn.execute(
                    "DELETE FROM samples WHERE uuid = ?", (uuid,)
                ).rowcount
                deleted += self._conn.execute(
                    "DELETE FROM workouts WHERE uuid = ?", (uuid,)
                ).rowcount
        return deleted

    def purge_older_than(self, days: int) -> int:
        if days <= 0:
            return 0
        cutoff = int(time.time()) - days * 86400
        with self._lock, self._conn:
            cur1 = self._conn.execute("DELETE FROM samples WHERE start_ts < ?", (cutoff,))
            cur2 = self._conn.execute("DELETE FROM workouts WHERE start_ts < ?", (cutoff,))
            self._conn.execute(
                "DELETE FROM ingest_events WHERE received_at < ?", (cutoff,)
            )
        return max(0, cur1.rowcount) + max(0, cur2.rowcount)

    def clear_data(self) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM samples")
            self._conn.execute("DELETE FROM workouts")
            self._conn.execute("DELETE FROM ingest_events")
