from __future__ import annotations

import logging
import shutil
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app.agent.graph import agent_graph, invoke_agent
from app.config import get_settings
from app.middleware.logging import RequestLoggingMiddleware
from app.schemas import (
    CalendarEvent,
    ChangeItem,
    ChatRequest,
    ChatResponse,
    CrawlSyncResponse,
    TodoBreakdownRequest,
    TodoBreakdownResponse,
    UploadResponse,
)
from app.services.change_store import (
    connect,
    detect_and_store_changes,
    insert_calendar_event,
    list_calendar_events,
    list_changes,
)
from app.services.crawler import crawl_realtime_sources
from app.services.todo import breakdown_todos
from app.services.vector_db import PROFILE_COLLECTION, index_academic_documents, index_profile_pdf

settings = get_settings()
logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s - %(message)s")

app = FastAPI(title=settings.app_name, version="0.1.0")
app.add_middleware(RequestLoggingMiddleware)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    with open("app/static/index.html", "r", encoding="utf-8") as f:
        return f.read()


@app.get("/api/health")
def health():
    return {"status": "ok", "service": settings.app_name}


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    if not settings.openai_api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY가 설정되어 있지 않습니다. .env를 확인하세요.")

    try:
        result = invoke_agent(message=req.message, session_id=req.session_id)
        store_schedules_to_calendar(result.get("schedules", []))
        return ChatResponse(**result)
    except Exception as exc:
        logging.getLogger(__name__).exception("chat failed: %s", exc)
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Agent 실행 중 오류가 발생했습니다.",
                "hint": "API Key, 네트워크, 크롤링 대상 URL, 패키지 버전을 확인하세요.",
            },
        )


@app.get("/api/graph/mermaid", response_class=PlainTextResponse)
def graph_mermaid() -> str:
    return agent_graph.get_graph().draw_mermaid()


@app.get("/api/sources")
def sources():
    return {"sources": settings.default_sources}


@app.post("/api/profile/upload", response_model=UploadResponse)
def upload_profile_pdf(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="PDF 파일만 업로드할 수 있습니다.")

    safe_name = Path(file.filename).name
    target_path = settings.upload_dir / safe_name
    with target_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    chunks = index_profile_pdf(target_path, safe_name)
    return UploadResponse(
        filename=safe_name,
        chunks=chunks,
        collection=PROFILE_COLLECTION,
        message="사용자 프로필 PDF를 Chroma에 저장했습니다.",
    )


@app.post("/api/crawl/sync", response_model=CrawlSyncResponse)
def sync_crawl_to_chroma():
    docs = crawl_realtime_sources(
        query="충북대학교 학사 일정 공지 수강 장학 등록 졸업 시험",
        seed_urls=settings.default_sources,
        timeout=settings.crawl_timeout,
        max_links=settings.max_links,
    )
    indexed_count = index_academic_documents(docs)
    change_result = detect_and_store_changes(docs)
    stats = change_result["stats"]
    return CrawlSyncResponse(
        indexed_documents=indexed_count,
        new_count=stats["new"],
        changed_count=stats["changed"],
        unchanged_count=stats["unchanged"],
        calendar_events=change_result["events"],
    )


@app.get("/api/calendar", response_model=list[CalendarEvent])
def calendar_events():
    return list_calendar_events()


@app.get("/api/changes", response_model=list[ChangeItem])
def changes():
    return list_changes()


@app.post("/api/todos/breakdown", response_model=TodoBreakdownResponse)
def todos_breakdown(req: TodoBreakdownRequest):
    return TodoBreakdownResponse(todos=breakdown_todos(req.goal))


def store_schedules_to_calendar(schedules: list[dict]) -> None:
    if not schedules:
        return
    with connect() as conn:
        for schedule in schedules:
            insert_calendar_event(
                conn,
                {
                    "title": schedule.get("title", "학사 일정"),
                    "category": schedule.get("category", "기타"),
                    "start_date": schedule.get("start_date"),
                    "end_date": schedule.get("end_date"),
                    "deadline": schedule.get("deadline"),
                    "importance": schedule.get("importance", "medium"),
                    "source_url": schedule.get("source_url"),
                    "evidence": schedule.get("evidence", ""),
                    "change_type": "chat_extract",
                },
            )
        conn.commit()
