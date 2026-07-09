from __future__ import annotations

import re
from datetime import date, datetime


def today_kst() -> date:
    # 서버 로컬 시간이 한국 시간이라고 가정한다. 배포 시 zoneinfo를 붙여도 된다.
    return datetime.now().date()


def days_until(date_text: str) -> str:
    """YYYY-MM-DD 또는 YYYY.MM.DD 형태의 날짜까지 남은 기간을 계산한다."""
    normalized = re.sub(r"[./]", "-", date_text.strip())
    target = datetime.strptime(normalized, "%Y-%m-%d").date()
    delta = (target - today_kst()).days

    if delta > 0:
        return f"{target.isoformat()}까지 {delta}일 남았습니다."
    if delta == 0:
        return f"{target.isoformat()}은 오늘입니다."
    return f"{target.isoformat()}은 이미 {-delta}일 지났습니다."
