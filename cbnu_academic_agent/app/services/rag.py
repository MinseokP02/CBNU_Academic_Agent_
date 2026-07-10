from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import get_settings
from app.services.vector_db import search_persistent_knowledge


def split_documents(docs: list[Document]) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=900,
        chunk_overlap=120,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    return splitter.split_documents(docs)


def _collection_name(query: str) -> str:
    digest = hashlib.sha1(query.encode("utf-8")).hexdigest()[:12]
    return f"cbnu_runtime_{digest}"


def retrieve_with_runtime_vectorstore(query: str, docs: list[Document], k: int = 5) -> list[Document]:
    """실시간 크롤링 문서로 임시 VectorStore를 만들고 유사 문서를 검색한다."""
    if not docs:
        return []

    settings = get_settings()
    chunks = split_documents(docs)
    if not chunks:
        return []

    # 평가용 MVP: 요청마다 임시 Chroma를 만들어 '실시간 웹 RAG'를 보장한다.
    persist_dir = Path(tempfile.mkdtemp(prefix="cbnu_chroma_"))
    embeddings = OpenAIEmbeddings(model=settings.openai_embedding_model)
    vectorstore = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        collection_name=_collection_name(query),
        persist_directory=str(persist_dir),
    )
    return vectorstore.similarity_search(query, k=k)


def retrieve_with_hybrid_vectorstore(query: str, docs: list[Document], k: int = 5) -> list[Document]:
    """영구 Chroma 지식과 요청 시점 크롤링 문서를 함께 검색한다."""
    runtime_results = retrieve_with_runtime_vectorstore(query=query, docs=docs, k=k)
    persistent_results = search_persistent_knowledge(query, k=k)

    merged: list[Document] = []
    seen: set[str] = set()
    for doc in [*runtime_results, *persistent_results]:
        key = f"{doc.metadata.get('source', '')}:{doc.page_content[:120]}"
        if key in seen:
            continue
        seen.add(key)
        merged.append(doc)
        if len(merged) >= k:
            break
    return merged
