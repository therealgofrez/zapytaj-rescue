import sqlite3
import os
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

class CoordinatorDB:
    def __init__(self, db_path: str = "./coordinator.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS chunks (
                    chunk_id INTEGER PRIMARY KEY,
                    start_id INTEGER NOT NULL,
                    end_id INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PENDING', -- PENDING, CLAIMED, DONE
                    claimed_by TEXT,
                    claimed_at REAL,
                    last_heartbeat REAL,
                    completed_at REAL,
                    items_saved INTEGER DEFAULT 0,
                    items_404 INTEGER DEFAULT 0,
                    warc_filename TEXT,
                    warc_size INTEGER DEFAULT 0,
                    checksum TEXT
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON chunks(status);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_claimed_by ON chunks(claimed_by);")
            conn.commit()

    def init_chunks(self, max_qid: int, min_qid: int = 1, chunk_size: int = 25000) -> int:
        """Inicjalizuje przestrzeń pytań w paczkach od najwyższego do najniższego ID."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM chunks")
            count = cursor.fetchone()[0]
            if count > 0:
                return count

            print(f"[DB] Generowanie paczek od ID {max_qid} w dół do {min_qid} (krok {chunk_size})...")
            rows = []
            chunk_id = 1
            current = max_qid
            while current >= min_qid:
                end = max(current - chunk_size + 1, min_qid)
                rows.append((chunk_id, current, end, "PENDING"))
                chunk_id += 1
                current = end - 1

            conn.executemany(
                "INSERT INTO chunks (chunk_id, start_id, end_id, status) VALUES (?, ?, ?, ?)",
                rows
            )
            conn.commit()
            print(f"[DB] Wygenerowano {len(rows)} paczek.")
            return len(rows)

    def claim_chunk(self, volunteer: str, lease_timeout_seconds: int = 1800) -> Optional[Dict[str, Any]]:
        now = time.time()
        stale_threshold = now - lease_timeout_seconds

        with self._get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            cursor = conn.cursor()
            cursor.execute("""
                SELECT chunk_id, start_id, end_id FROM chunks
                WHERE status = 'CLAIMED' AND last_heartbeat < ?
                ORDER BY chunk_id ASC
                LIMIT 1
            """, (stale_threshold,))
            row = cursor.fetchone()

            if not row:
                cursor.execute("""
                    SELECT chunk_id, start_id, end_id FROM chunks
                    WHERE status = 'PENDING'
                    ORDER BY chunk_id ASC
                    LIMIT 1
                """)
                row = cursor.fetchone()

            if not row:
                return None

            chunk_id, start_id, end_id = row["chunk_id"], row["start_id"], row["end_id"]

            cursor.execute("""
                UPDATE chunks
                SET status = 'CLAIMED',
                    claimed_by = ?,
                    claimed_at = ?,
                    last_heartbeat = ?
                WHERE chunk_id = ?
            """, (volunteer, now, now, chunk_id))
            conn.commit()

            return {
                "chunk_id": chunk_id,
                "start_id": start_id,
                "end_id": end_id,
                "volunteer": volunteer,
                "claimed_at": now
            }

    def heartbeat(self, chunk_id: int, volunteer: str) -> bool:
        """Przedłuża dzierżawę chunka."""
        now = time.time()
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE chunks
                SET last_heartbeat = ?
                WHERE chunk_id = ? AND claimed_by = ? AND status = 'CLAIMED'
            """, (now, chunk_id, volunteer))
            conn.commit()
            return cursor.rowcount > 0

    def complete_chunk(self, chunk_id: int, volunteer: str, items_saved: int, items_404: int,
                       warc_filename: str = "", warc_size: int = 0, checksum: str = "") -> bool:
        """Oznacza chunk jako ukończony i zapisuje statystyki."""
        now = time.time()
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE chunks
                SET status = 'DONE',
                    completed_at = ?,
                    items_saved = ?,
                    items_404 = ?,
                    warc_filename = ?,
                    warc_size = ?,
                    checksum = ?,
                    claimed_by = ?
                WHERE chunk_id = ? AND (claimed_by = ? OR status != 'DONE')
            """, (now, items_saved, items_404, warc_filename, warc_size, checksum, volunteer, chunk_id, volunteer))
            conn.commit()
            return cursor.rowcount > 0

    def get_stats(self) -> Dict[str, Any]:
        """Zwraca globalne statystyki postępu, listę aktywnych workerów i ranking."""
        now = time.time()
        with self._get_conn() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT
                    COUNT(*) as total_chunks,
                    SUM(CASE WHEN status = 'DONE' THEN 1 ELSE 0 END) as done_chunks,
                    SUM(CASE WHEN status = 'CLAIMED' AND last_heartbeat >= ? THEN 1 ELSE 0 END) as active_chunks,
                    SUM(items_saved) as total_items_saved,
                    SUM(items_404) as total_items_404,
                    SUM(warc_size) as total_warc_bytes
                FROM chunks
            """, (now - 300,)) # Aktywny jeśli heartbeat w ciągu ostatnich 5 minut
            stats_row = cursor.fetchone()

            cursor.execute("""
                SELECT chunk_id, start_id, end_id, claimed_by, last_heartbeat
                FROM chunks
                WHERE status = 'CLAIMED' AND last_heartbeat >= ?
                ORDER BY last_heartbeat DESC
            """, (now - 300,))
            active_workers = [
                {
                    "chunk_id": r["chunk_id"],
                    "range": f"{r['start_id']} -> {r['end_id']}",
                    "volunteer": r["claimed_by"],
                    "seconds_since_heartbeat": int(now - r["last_heartbeat"])
                }
                for r in cursor.fetchall()
            ]

            cursor.execute("""
                SELECT claimed_by, COUNT(*) as chunks_done, SUM(items_saved) as saved
                FROM chunks
                WHERE status = 'DONE' AND claimed_by IS NOT NULL
                GROUP BY claimed_by
                ORDER BY saved DESC
                LIMIT 20
            """)
            leaderboard = [
                {
                    "volunteer": r["claimed_by"],
                    "chunks_done": r["chunks_done"],
                    "items_saved": r["saved"] or 0
                }
                for r in cursor.fetchall()
            ]

            total_chunks = stats_row["total_chunks"] or 0
            done_chunks = stats_row["done_chunks"] or 0
            pct_done = (done_chunks / total_chunks * 100) if total_chunks > 0 else 0.0

            return {
                "total_chunks": total_chunks,
                "done_chunks": done_chunks,
                "pending_chunks": total_chunks - done_chunks - (stats_row["active_chunks"] or 0),
                "active_chunks": stats_row["active_chunks"] or 0,
                "percent_complete": round(pct_done, 2),
                "total_items_saved": stats_row["total_items_saved"] or 0,
                "total_items_404": stats_row["total_items_404"] or 0,
                "total_warc_bytes": stats_row["total_warc_bytes"] or 0,
                "active_workers": active_workers,
                "leaderboard": leaderboard
            }
