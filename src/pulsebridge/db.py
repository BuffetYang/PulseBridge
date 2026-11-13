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

from .util import (
    normalize_type,
    normalize_workout_type,
    sample_fingerprint,
    workout_fingerprint,
)

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS samples (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid        TEXT NOT NULL UNIQUE,
    fingerprint TEXT,
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
    fingerprint   TEXT,
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

CREATE TABLE IF NOT EXISTS activity_summaries (
    date            TEXT PRIMARY KEY,
    move_kcal       REAL,
    move_goal_kcal  REAL,
    exercise_min    REAL,
    exercise_goal_min REAL,
    stand_hours     REAL,
    stand_goal_hours REAL,
    updated_at      INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_activity_summaries_date ON activity_summaries(date);

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
            self._add_fingerprint_columns()
            # 把旧版本/第三方协议留下的原始类型转成可读类型
            activity_changed = False
            existing = self._conn.execute(
                "SELECT DISTINCT activity_type FROM workouts"
            ).fetchall()
            for (current,) in existing:
                normalized = normalize_workout_type(current)
                if normalized and normalized != current:
                    self._conn.execute(
                        "UPDATE workouts SET activity_type = ?, fingerprint = NULL "
                        "WHERE activity_type = ?",
                        (normalized, current),
                    )
                    activity_changed = True
            if activity_changed:
                self._conn.execute("DROP INDEX IF EXISTS idx_workouts_fingerprint")

            type_changed = False
            existing_types = self._conn.execute(
                "SELECT DISTINCT type FROM samples"
            ).fetchall()
            for (current,) in existing_types:
                normalized = normalize_type(current)
                if normalized and normalized != current:
                    self._conn.execute(
                        "UPDATE samples SET type = ?, fingerprint = NULL WHERE type = ?",
                        (normalized, current),
                    )
                    type_changed = True
            if type_changed:
                self._conn.execute("DROP INDEX IF EXISTS idx_samples_fingerprint")

            self._ensure_fingerprint_schema()
            self._conn.commit()

    def _add_fingerprint_columns(self) -> None:
        sample_cols = {
            row[1] for row in self._conn.execute("PRAGMA table_info(samples)")
        }
        if "fingerprint" not in sample_cols:
            self._conn.execute("ALTER TABLE samples ADD COLUMN fingerprint TEXT")
        workout_cols = {
            row[1] for row in self._conn.execute("PRAGMA table_info(workouts)")
        }
        if "fingerprint" not in workout_cols:
            self._conn.execute("ALTER TABLE workouts ADD COLUMN fingerprint TEXT")

    def _ensure_fingerprint_schema(self) -> None:
        """为旧数据库补 fingerprint 列、回填、去重并建立唯一索引。"""
        sample_cols = {
            row[1] for row in self._conn.execute("PRAGMA table_info(samples)")
        }
        if "fingerprint" not in sample_cols:
            self._conn.execute("ALTER TABLE samples ADD COLUMN fingerprint TEXT")
        workout_cols = {
            row[1] for row in self._conn.execute("PRAGMA table_info(workouts)")
        }
        if "fingerprint" not in workout_cols:
            self._conn.execute("ALTER TABLE workouts ADD COLUMN fingerprint TEXT")

        samples = self._conn.execute(
            "SELECT id, type, start_ts, end_ts, value, value_text, unit "
            "FROM samples WHERE fingerprint IS NULL"
        ).fetchall()
        sample_needs_dedupe = bool(samples)
        for row in samples:
            self._conn.execute(
                "UPDATE samples SET fingerprint = ? WHERE id = ?",
                (
                    sample_fingerprint(
                        row["type"],
                        row["start_ts"],
                        row["end_ts"],
                        row["value"],
                        row["value_text"],
                        row["unit"],
                    ),
                    row["id"],
                ),
            )

        workouts = self._conn.execute(
            "SELECT id, activity_type, start_ts, end_ts "
            "FROM workouts WHERE fingerprint IS NULL"
        ).fetchall()
        workout_needs_dedupe = bool(workouts)
        for row in workouts:
            self._conn.execute(
                "UPDATE workouts SET fingerprint = ? WHERE id = ?",
                (
                    workout_fingerprint(
                        row["activity_type"], row["start_ts"], row["end_ts"]
                    ),
                    row["id"],
                ),
            )

        sample_indexes = {
            row[1] for row in self._conn.execute("PRAGMA index_list(samples)")
        }
        workout_indexes = {
            row[1] for row in self._conn.execute("PRAGMA index_list(workouts)")
        }
        if "idx_samples_fingerprint" not in sample_indexes:
            sample_needs_dedupe = True
        if "idx_workouts_fingerprint" not in workout_indexes:
            workout_needs_dedupe = True

        # 旧数据库可能已有跨通道重复；保留最早的一条
        if sample_needs_dedupe:
            self._conn.execute(
                "DELETE FROM samples WHERE fingerprint IS NOT NULL AND id NOT IN "
                "(SELECT MIN(id) FROM samples WHERE fingerprint IS NOT NULL GROUP BY fingerprint)"
            )
        if workout_needs_dedupe:
            self._conn.execute(
                "DELETE FROM workouts WHERE fingerprint IS NOT NULL AND id NOT IN "
                "(SELECT MIN(id) FROM workouts WHERE fingerprint IS NOT NULL GROUP BY fingerprint)"
            )
        self._conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_samples_fingerprint "
            "ON samples(fingerprint)"
        )
        self._conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_workouts_fingerprint "
            "ON workouts(fingerprint)"
        )

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
        now = int(time.time())

        def values() -> Iterable[tuple[Any, ...]]:
            for row in rows:
                fingerprint = row.get("fingerprint") or sample_fingerprint(
                    row["type"],
                    row["start_ts"],
                    row["end_ts"],
                    row.get("value"),
                    row.get("value_text"),
                    row.get("unit"),
                )
                yield (
                    row["uuid"],
                    fingerprint,
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
                )

        with self._lock, self._conn:
            before = self._conn.total_changes
            self._conn.executemany(
                """
                INSERT OR IGNORE INTO samples
                    (uuid, fingerprint, type, start_ts, end_ts, value, value_text,
                     unit, source, device, metadata, received_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values(),
            )
            inserted = self._conn.total_changes - before
        return inserted, len(rows) - inserted

    def insert_workouts(self, workouts: Iterable[dict[str, Any]]) -> tuple[int, int]:
        rows = list(workouts)
        if not rows:
            return 0, 0
        now = int(time.time())

        def values() -> Iterable[tuple[Any, ...]]:
            for row in rows:
                fingerprint = row.get("fingerprint") or workout_fingerprint(
                    row["activity_type"], row["start_ts"], row["end_ts"]
                )
                yield (
                    row["uuid"],
                    fingerprint,
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
                )

        with self._lock, self._conn:
            before = self._conn.total_changes
            self._conn.executemany(
                """
                INSERT OR IGNORE INTO workouts
                    (uuid, fingerprint, activity_type, start_ts, end_ts, duration_s,
                     distance_m, energy_kcal, avg_hr, max_hr, source, metadata,
                     received_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values(),
            )
            inserted = self._conn.total_changes - before
        return inserted, len(rows) - inserted

    def upsert_activity_summaries(self, rows: Iterable[dict[str, Any]]) -> int:
        """每日活动圆环（Move / Exercise / Stand）按日期 upsert。"""
        values = list(rows)
        if not values:
            return 0
        now = int(time.time())
        with self._lock, self._conn:
            for row in values:
                self._conn.execute(
                    """
                    INSERT INTO activity_summaries
                        (date, move_kcal, move_goal_kcal, exercise_min,
                         exercise_goal_min, stand_hours, stand_goal_hours, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(date) DO UPDATE SET
                        move_kcal=excluded.move_kcal,
                        move_goal_kcal=excluded.move_goal_kcal,
                        exercise_min=excluded.exercise_min,
                        exercise_goal_min=excluded.exercise_goal_min,
                        stand_hours=excluded.stand_hours,
                        stand_goal_hours=excluded.stand_goal_hours,
                        updated_at=excluded.updated_at
                    """,
                    (
                        row["date"],
                        row.get("move_kcal"),
                        row.get("move_goal_kcal"),
                        row.get("exercise_min"),
                        row.get("exercise_goal_min"),
                        row.get("stand_hours"),
                        row.get("stand_goal_hours"),
                        now,
                    ),
                )
        return len(values)

    def activity_summaries(self, days: int = 7) -> list[dict]:
        from datetime import date, timedelta

        start = (date.today() - timedelta(days=max(1, days) - 1)).isoformat()
        return [
            dict(row)
            for row in self._rows(
                "SELECT * FROM activity_summaries WHERE date >= ? ORDER BY date",
                (start,),
            )
        ]

    def latest_activity_summary(self) -> dict | None:
        rows = self._rows(
            "SELECT * FROM activity_summaries ORDER BY date DESC LIMIT 1"
        )
        return dict(rows[0]) if rows else None

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

    def workout_rows(
        self,
        since_ts: int,
        limit: int = 200,
        until_ts: int | None = None,
        activity_type: str | None = None,
    ) -> list[dict]:
        sql = "SELECT * FROM workouts WHERE start_ts >= ?"
        params: list[Any] = [since_ts]
        if until_ts is not None:
            sql += " AND start_ts < ?"
            params.append(until_ts)
        if activity_type:
            sql += " AND activity_type = ?"
            params.append(activity_type)
        sql += " ORDER BY start_ts DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self._rows(sql, tuple(params))]

    def workout_type_counts(self) -> list[dict]:
        rows = self._rows(
            "SELECT activity_type, COUNT(*) AS n FROM workouts "
            "GROUP BY activity_type ORDER BY n DESC, activity_type"
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

    def hourly_step_totals(
        self, since_ts: int, end_ts: int | None = None
    ) -> list[dict]:
        """按本地小时汇总步数；每个小时取各来源合计的最大值，避免双计。"""
        sql = """
            SELECT hour, MAX(total) AS value FROM (
                SELECT strftime('%Y-%m-%d %H', start_ts, 'unixepoch', 'localtime') AS hour,
                       ifnull(source, '') AS src,
                       SUM(value) AS total
                FROM samples
                WHERE type = 'steps' AND start_ts >= ? AND value IS NOT NULL
        """
        params: list[Any] = [since_ts]
        if end_ts is not None:
            sql += " AND start_ts < ?"
            params.append(end_ts)
        sql += """
                GROUP BY hour, src
            )
            GROUP BY hour
            ORDER BY hour
        """
        return [dict(r) for r in self._rows(sql, tuple(params))]

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
