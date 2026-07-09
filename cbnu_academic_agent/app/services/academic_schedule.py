from __future__ import annotations

import re
from datetime import date
from typing import Any

import httpx
from bs4 import BeautifulSoup
from langchain_core.documents import Document

from app.config import get_settings
from app.services.change_store import infer_category


SCHEDULE_URL = "https://www.cbnu.ac.kr/www/selectWebSchdulList.do"
DATE_TOKEN_PATTERN = re.compile(r"(\d{1,2})\.(\d{1,2})\.?")


def academic_schedule_url(year: int) -> str:
    return f"{SCHEDULE_URL}?currentY={year}&key=455&month=all&schdulSeNo=1"


def fetch_academic_schedule_html(year: int) -> str:
    settings = get_settings()
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; CBNUAcademicPlannerAgent/1.0; +https://github.com/)"
    }
    with httpx.Client(timeout=settings.crawl_timeout, follow_redirects=True, headers=headers) as client:
        response = client.get(academic_schedule_url(year))
        response.raise_for_status()
        return response.text


def load_academic_schedule_range(start: date, end: date) -> tuple[list[dict[str, Any]], list[Document]]:
    years = range(start.year, end.year + 1)
    events: list[dict[str, Any]] = []
    docs: list[Document] = []

    for year in years:
        html = fetch_academic_schedule_html(year)
        year_events = parse_academic_schedule_html(html, year, start, end)
        events.extend(year_events)
        docs.append(
            Document(
                page_content="\n".join(
                    format_event_for_document(event)
                    for event in year_events
                ),
                metadata={
                    "title": f"충북대학교 {year}학년도 학부일정",
                    "source": academic_schedule_url(year),
                    "kind": "academic_schedule",
                },
            )
        )

    return events, [doc for doc in docs if doc.page_content.strip()]


def parse_academic_schedule_html(html: str, schedule_year: int, start: date, end: date) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    text_rows = extract_schedule_rows(soup)
    events: list[dict[str, Any]] = []
    current_month: int | None = None

    for row in text_rows:
        month_match = re.fullmatch(r"(\d{1,2})월", row)
        if month_match:
            current_month = int(month_match.group(1))
            continue

        tokens = list(DATE_TOKEN_PATTERN.finditer(row))
        if not tokens:
            continue

        title = DATE_TOKEN_PATTERN.sub("", row)
        title = re.sub(r"\s*[~～-]\s*", " ", title)
        title = re.sub(r"\([^)]*\)", "", title)
        title = re.sub(r"\s+", " ", title).strip(" -~")
        if not title:
            continue

        start_date = infer_schedule_date(schedule_year, current_month, int(tokens[0].group(1)), int(tokens[0].group(2)))
        end_date = None
        if len(tokens) >= 2:
            end_date = infer_schedule_date(schedule_year, current_month, int(tokens[1].group(1)), int(tokens[1].group(2)))
            if end_date < start_date:
                end_date = date(end_date.year + 1, end_date.month, end_date.day)

        if not overlaps_range(start_date, end_date or start_date, start, end):
            continue

        event_text = f"{title} {row}"
        event = {
            "title": title,
            "category": infer_category(event_text),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat() if end_date else None,
            "deadline": (end_date or start_date).isoformat() if is_deadline_like(event_text) else None,
            "importance": "high" if is_deadline_like(event_text) else "medium",
            "source_url": academic_schedule_url(schedule_year),
            "evidence": row,
            "change_type": "academic_schedule",
        }
        events.append(event)

    return dedupe_events(events)


def extract_schedule_rows(soup: BeautifulSoup) -> list[str]:
    rows: list[str] = []
    for tr in soup.find_all("tr"):
        cells = [clean_text(cell.get_text(" ")) for cell in tr.find_all(["th", "td"])]
        cells = [cell for cell in cells if cell]
        if cells:
            rows.append(" ".join(cells))

    if rows:
        return rows

    text = soup.get_text("\n")
    return [clean_text(line) for line in text.splitlines() if clean_text(line)]


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def infer_schedule_date(schedule_year: int, section_month: int | None, month: int, day: int) -> date:
    year = schedule_year
    if section_month in {1, 2} and month == 12:
        year = schedule_year - 1
    elif section_month == 12 and month in {1, 2}:
        year = schedule_year + 1
    return date(year, month, day)


def overlaps_range(start_date: date, end_date: date, range_start: date, range_end: date) -> bool:
    return start_date <= range_end and end_date >= range_start


def is_deadline_like(text: str) -> bool:
    return any(word in text for word in ("신청", "접수", "제출", "등록", "납부", "마감", "수강"))


def dedupe_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str | None]] = set()
    for event in events:
        key = (event["title"], event["start_date"], event.get("end_date"))
        if key in seen:
            continue
        seen.add(key)
        result.append(event)
    return result


def format_event_for_document(event: dict[str, Any]) -> str:
    end_date = f" ~ {event['end_date']}" if event.get("end_date") else ""
    return f"{event['start_date']}{end_date} {event['title']} ({event['category']})"
