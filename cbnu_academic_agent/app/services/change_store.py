from __future__ import annotations

import hashlib
import re
import sqlite3
from datetime import datetime
from typing import Any

from langchain_core.documents import Document

from app.config import get_settings


DATE_PATTERN = re.compile(r"(20\d{2})[.\-/년\s]+(\d{1,2})[.\-/월\s]+(\d{1,2})")


def connect() -> sqlite3.Connection:
    settings = get_settings()
    conn = sqlite3.connect(settings.sqlite_path)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection | None = None) -> None:
    should_close = conn is None
    conn = conn or sqlite3.connect(get_settings().sqlite_path)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS notices (
            source_url TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            last_seen_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS notice_changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_url TEXT NOT NULL,
            title TEXT NOT NULL,
            change_type TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            detected_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS calendar_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT '기타',
            start_date TEXT,
            end_date TEXT,
            deadline TEXT,
            importance TEXT NOT NULL DEFAULT 'medium',
            source_url TEXT,
            evidence TEXT NOT NULL DEFAULT '',
            change_type TEXT NOT NULL DEFAULT 'manual',
            created_at TEXT NOT NULL
        );
        """
    )
    conn.commit()
    if should_close:
        conn.close()


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def detect_and_store_changes(docs: list[Document]) -> dict[str, Any]:
    now = datetime.now().isoformat(timespec="seconds")
    stats = {"new": 0, "changed": 0, "unchanged": 0}
    events: list[dict[str, Any]] = []

    with connect() as conn:
        for doc in docs:
            source_url = doc.metadata.get("source", "")
            title = doc.metadata.get("title", "제목 없음")
            if not source_url:
                continue

            digest = content_hash(doc.page_content)
            previous = conn.execute(
                "SELECT content_hash FROM notices WHERE source_url = ?",
                (source_url,),
            ).fetchone()

            if previous is None:
                change_type = "new"
                stats["new"] += 1
                conn.execute(
                    "INSERT INTO notices(source_url, title, content_hash, last_seen_at) VALUES (?, ?, ?, ?)",
                    (source_url, title, digest, now),
                )
            elif previous["content_hash"] != digest:
                change_type = "changed"
                stats["changed"] += 1
                conn.execute(
                    "UPDATE notices SET title = ?, content_hash = ?, last_seen_at = ? WHERE source_url = ?",
                    (title, digest, now, source_url),
                )
            else:
                stats["unchanged"] += 1
                conn.execute(
                    "UPDATE notices SET last_seen_at = ? WHERE source_url = ?",
                    (now, source_url),
                )
                continue

            conn.execute(
                """
                INSERT INTO notice_changes(source_url, title, change_type, content_hash, detected_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (source_url, title, change_type, digest, now),
            )

            event = event_from_document(doc, change_type)
            if event:
                event_id = insert_calendar_event(conn, event)
                event["id"] = event_id
                events.append(event)

        conn.commit()

    return {"stats": stats, "events": events}


def event_from_document(doc: Document, change_type: str) -> dict[str, Any] | None:
    text = doc.page_content
    match = DATE_PATTERN.search(text)
    if not match:
        return None

    year, month, day = match.groups()
    date_text = f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    title = doc.metadata.get("title", "충북대학교 공지")
    evidence_start = max(0, match.start() - 80)
    evidence_end = min(len(text), match.end() + 160)
    return {
        "title": title,
        "category": infer_category(f"{title} {text[:500]}"),
        "start_date": date_text,
        "end_date": None,
        "deadline": date_text if "마감" in text[:1000] or "신청" in text[:1000] else None,
        "importance": "high" if any(word in text[:1000] for word in ("마감", "신청", "등록", "수강")) else "medium",
        "source_url": doc.metadata.get("source", ""),
        "evidence": text[evidence_start:evidence_end].strip(),
        "change_type": change_type,
    }


def infer_category(text: str) -> str:
    if "수강" in text:
        return "수강"
    if "장학" in text:
        return "장학"
    if "졸업" in text:
        return "졸업"
    if "등록" in text:
        return "등록"
    if "시험" in text:
        return "시험"
    if "휴학" in text or "복학" in text:
        return "휴복학"
    if "학사" in text or "일정" in text:
        return "학사"
    return "기타"


def insert_calendar_event(conn: sqlite3.Connection, event: dict[str, Any]) -> int:
    created_at = datetime.now().isoformat(timespec="seconds")
    cursor = conn.execute(
        """
        INSERT INTO calendar_events(
            title, category, start_date, end_date, deadline, importance,
            source_url, evidence, change_type, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event["title"],
            event["category"],
            event.get("start_date"),
            event.get("end_date"),
            event.get("deadline"),
            event["importance"],
            event.get("source_url"),
            event.get("evidence", ""),
            event.get("change_type", "manual"),
            created_at,
        ),
    )
    return int(cursor.lastrowid)


def list_calendar_events() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, title, category, start_date, end_date, deadline, importance,
                   source_url, evidence, change_type
            FROM calendar_events
            ORDER BY COALESCE(deadline, start_date, end_date) ASC, id DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def list_changes(limit: int = 30) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, title, source_url, change_type, content_hash, detected_at
            FROM notice_changes
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]
