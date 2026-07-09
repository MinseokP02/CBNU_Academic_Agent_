from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.config import get_settings
from app.schemas import TodoItem

logger = logging.getLogger(__name__)


class TodoPlan(BaseModel):
    todos: list[TodoItem] = Field(default_factory=list)


def breakdown_todos(goal: str) -> list[TodoItem]:
    settings = get_settings()
    if not settings.openai_api_key:
        return fallback_todos(goal)

    llm = ChatOpenAI(model=settings.openai_model, temperature=0)
    system = SystemMessage(
        content=(
            "너는 충북대학교 학생의 학사 업무를 실행 가능한 Todo로 쪼개는 플래너다. "
            "각 Todo는 한 번에 실행 가능한 짧은 행동이어야 한다. "
            "날짜가 명시되어 있으면 due_date를 YYYY-MM-DD로 넣고, 모르면 null로 둔다."
        )
    )
    human = HumanMessage(content=f"목표 또는 일정: {goal}")

    try:
        plan = llm.with_structured_output(TodoPlan).invoke([system, human])
        return plan.todos
    except Exception as exc:
        logger.exception("todo breakdown failed: %s", exc)
        return fallback_todos(goal)


def fallback_todos(goal: str) -> list[TodoItem]:
    return [
        TodoItem(title=f"관련 공지 확인: {goal}", priority="high", reason="일정과 제출 조건을 먼저 확인해야 합니다."),
        TodoItem(title="필요 서류와 신청 자격 정리", priority="medium", reason="누락된 준비물을 줄이기 위한 단계입니다."),
        TodoItem(title="마감 전 제출 또는 신청 완료", priority="high", reason="학사 업무는 마감 초과 시 처리가 어려울 수 있습니다."),
    ]
