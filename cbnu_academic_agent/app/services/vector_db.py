from __future__ import annotations

import hashlib
from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

from app.config import get_settings


PROFILE_COLLECTION = "user_profile_pdf"
ACADEMIC_COLLECTION = "cbnu_academic_docs"


def _embeddings() -> OpenAIEmbeddings:
    settings = get_settings()
    return OpenAIEmbeddings(model=settings.openai_embedding_model)


def get_vectorstore(collection_name: str) -> Chroma:
    settings = get_settings()
    persist_directory = settings.chroma_dir / collection_name
    persist_directory.mkdir(parents=True, exist_ok=True)
    return Chroma(
        collection_name=collection_name,
        embedding_function=_embeddings(),
        persist_directory=str(persist_directory),
    )


def split_documents(docs: list[Document]) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=900,
        chunk_overlap=120,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    return splitter.split_documents(docs)


def document_id(collection: str, source: str, text: str) -> str:
    payload = f"{collection}|{source}|{text[:500]}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def add_documents_to_collection(collection_name: str, docs: list[Document]) -> int:
    chunks = split_documents(docs)
    if not chunks:
        return 0

    ids = [
        document_id(collection_name, chunk.metadata.get("source", ""), chunk.page_content)
        for chunk in chunks
    ]
    vectorstore = get_vectorstore(collection_name)
    existing = set(vectorstore.get(ids=ids).get("ids", []))
    new_chunks = [chunk for chunk, chunk_id in zip(chunks, ids) if chunk_id not in existing]
    new_ids = [chunk_id for chunk_id in ids if chunk_id not in existing]
    if not new_chunks:
        return 0

    vectorstore.add_documents(new_chunks, ids=new_ids)
    return len(new_chunks)


def load_pdf_documents(path: Path, original_filename: str) -> list[Document]:
    reader = PdfReader(str(path))
    docs: list[Document] = []
    for page_number, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if not text:
            continue
        docs.append(
            Document(
                page_content=text,
                metadata={
                    "title": original_filename,
                    "source": str(path),
                    "page": page_number,
                    "kind": "profile_pdf",
                },
            )
        )
    return docs


def index_profile_pdf(path: Path, original_filename: str) -> int:
    return add_documents_to_collection(
        PROFILE_COLLECTION,
        load_pdf_documents(path, original_filename),
    )


def index_academic_documents(docs: list[Document]) -> int:
    normalized = []
    for doc in docs:
        metadata = dict(doc.metadata)
        metadata.setdefault("kind", "academic_web")
        normalized.append(Document(page_content=doc.page_content, metadata=metadata))
    return add_documents_to_collection(ACADEMIC_COLLECTION, normalized)


def search_persistent_knowledge(query: str, k: int = 5) -> list[Document]:
    results: list[Document] = []
    for collection in (ACADEMIC_COLLECTION, PROFILE_COLLECTION):
        vectorstore = get_vectorstore(collection)
        results.extend(vectorstore.similarity_search(query, k=k))
    return results[:k]
