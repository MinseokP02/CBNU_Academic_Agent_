from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from langchain_core.documents import Document


@dataclass
class CrawledPage:
    title: str
    url: str
    text: str


class CrawlerError(RuntimeError):
    pass


def _clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text


def _is_allowed_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _is_probably_notice_link(text: str, href: str, query: str) -> bool:
    target = f"{text} {href} {query}".lower()
    keywords = [
        "공지", "학사", "수강", "장학", "졸업", "등록", "휴학", "복학", "시험",
        "schdul", "schedule", "bbs", "ntt", "notice", "select",
    ]
    return any(k.lower() in target for k in keywords)


def extract_text_from_html(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "lxml")

    for tag in soup(["script", "style", "noscript", "svg", "canvas"]):
        tag.decompose()

    title = _clean_text(soup.title.get_text(" ") if soup.title else "제목 없음")

    # 본문 후보를 넓게 잡는다. 학교 CMS가 바뀌어도 최소한 텍스트는 얻기 위함.
    main = soup.find("main") or soup.find(id=re.compile("content|container|body", re.I)) or soup.body or soup
    text = _clean_text(main.get_text(" "))
    return title, text


def extract_candidate_links(base_url: str, html: str, query: str, limit: int = 10) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    links: list[str] = []
    seen: set[str] = set()

    for a in soup.find_all("a", href=True):
        text = _clean_text(a.get_text(" "))
        href = urljoin(base_url, a["href"])
        if href in seen or not _is_allowed_url(href):
            continue
        if not _is_probably_notice_link(text, href, query):
            continue
        seen.add(href)
        links.append(href)
        if len(links) >= limit:
            break
    return links


def fetch_page(url: str, timeout: int = 10) -> CrawledPage:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; CBNUAcademicPlannerAgent/1.0; +https://github.com/)"
    }
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
            response = client.get(url)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise CrawlerError(f"크롤링 실패: {url} ({exc})") from exc

    title, text = extract_text_from_html(response.text)
    return CrawledPage(title=title, url=str(response.url), text=text)


def crawl_realtime_sources(
    query: str,
    seed_urls: Iterable[str],
    timeout: int = 10,
    max_links: int = 12,
) -> list[Document]:
    """실시간으로 seed URL과 후보 링크를 크롤링해 LangChain Document로 변환한다."""
    docs: list[Document] = []
    visited: set[str] = set()
    queue: list[str] = list(dict.fromkeys(seed_urls))

    while queue and len(visited) < max_links:
        url = queue.pop(0)
        if url in visited or not _is_allowed_url(url):
            continue
        visited.add(url)

        try:
            page = fetch_page(url, timeout=timeout)
        except CrawlerError:
            continue

        if page.text:
            docs.append(
                Document(
                    page_content=page.text[:12000],
                    metadata={"title": page.title, "source": page.url},
                )
            )

        # 최초 seed 또는 본문 페이지에서 관련 링크를 조금 더 확장한다.
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                html = client.get(url).text
            for link in extract_candidate_links(url, html, query=query, limit=max(3, max_links // 2)):
                if link not in visited and link not in queue:
                    queue.append(link)
        except httpx.HTTPError:
            pass

    return docs
