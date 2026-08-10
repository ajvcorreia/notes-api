from __future__ import annotations

import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from . import item_cache, notes_service, stats_service
from .config import settings
from .joplin_client import JoplinError, JoplinNotFound, joplin_client
from .models import (
    Note,
    NoteCreate,
    NoteSummary,
    NoteUpdate,
    Notebook,
    NotebookCreate,
    StatsSummary,
)

_STATS_PAGE = Path(__file__).parent / "static" / "stats.html"
_UNTRACKED_PATHS = {"/stats", "/stats/data", "/docs", "/redoc", "/openapi.json"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    stats_service.init_db()
    yield
    item_cache.shutdown()
    await joplin_client.aclose()


app = FastAPI(title="Joplin Notes API", version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def track_usage(request: Request, call_next):
    if request.url.path in _UNTRACKED_PATHS:
        return await call_next(request)
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    await run_in_threadpool(
        stats_service.record_request,
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


async def require_api_key(x_api_key: str = Header(...)) -> None:
    if x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


def _handle_joplin_error(exc: JoplinError):
    if isinstance(exc, JoplinNotFound):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    raise HTTPException(status_code=502, detail=f"Joplin Server error: {exc}") from exc


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/stats", include_in_schema=False)
async def stats_page() -> FileResponse:
    return FileResponse(_STATS_PAGE)


@app.get("/stats/data", response_model=StatsSummary, dependencies=[Depends(require_api_key)])
async def stats_data(exclude_health: bool = True) -> StatsSummary:
    return await run_in_threadpool(stats_service.get_summary, exclude_health=exclude_health)


@app.get("/notes", response_model=list[NoteSummary], dependencies=[Depends(require_api_key)])
async def list_notes(
    parent_id: str | None = None,
    limit: int | None = Query(None, ge=1),
    offset: int = Query(0, ge=0),
) -> list[NoteSummary]:
    try:
        return await notes_service.list_notes(parent_id=parent_id, limit=limit, offset=offset)
    except JoplinError as exc:
        _handle_joplin_error(exc)


@app.get("/search", response_model=list[NoteSummary], dependencies=[Depends(require_api_key)])
async def search_notes(
    q: str = Query(..., min_length=1),
    limit: int | None = Query(None, ge=1),
    offset: int = Query(0, ge=0),
) -> list[NoteSummary]:
    try:
        return await notes_service.search_notes(query=q, limit=limit, offset=offset)
    except JoplinError as exc:
        _handle_joplin_error(exc)


@app.get("/notes/{note_id}", response_model=Note, dependencies=[Depends(require_api_key)])
async def get_note(note_id: str) -> Note:
    try:
        return await notes_service.get_note(note_id)
    except JoplinError as exc:
        _handle_joplin_error(exc)


@app.post("/notes", response_model=Note, status_code=201, dependencies=[Depends(require_api_key)])
async def create_note(data: NoteCreate) -> Note:
    try:
        return await notes_service.create_note(data)
    except JoplinError as exc:
        _handle_joplin_error(exc)


@app.put("/notes/{note_id}", response_model=Note, dependencies=[Depends(require_api_key)])
async def update_note(note_id: str, data: NoteUpdate) -> Note:
    try:
        return await notes_service.update_note(note_id, data)
    except JoplinError as exc:
        _handle_joplin_error(exc)


@app.delete("/notes/{note_id}", status_code=204, response_model=None, dependencies=[Depends(require_api_key)])
async def delete_note(note_id: str) -> None:
    try:
        await notes_service.delete_note(note_id)
    except JoplinError as exc:
        _handle_joplin_error(exc)


@app.post("/notes/{note_id}/attachments", response_model=Note, dependencies=[Depends(require_api_key)])
async def add_attachment(note_id: str, file: UploadFile = File(...)) -> Note:
    try:
        content = await file.read()
        mime = file.content_type or "application/octet-stream"
        return await notes_service.attach_file(note_id, file.filename or "attachment", mime, content)
    except JoplinError as exc:
        _handle_joplin_error(exc)


@app.get("/notebooks", response_model=list[Notebook], dependencies=[Depends(require_api_key)])
async def list_notebooks() -> list[Notebook]:
    try:
        return await notes_service.list_notebooks()
    except JoplinError as exc:
        _handle_joplin_error(exc)


@app.post("/notebooks", response_model=Notebook, status_code=201, dependencies=[Depends(require_api_key)])
async def create_notebook(data: NotebookCreate) -> Notebook:
    try:
        return await notes_service.create_notebook(data)
    except JoplinError as exc:
        _handle_joplin_error(exc)


@app.delete("/notebooks/{notebook_id}", status_code=204, response_model=None, dependencies=[Depends(require_api_key)])
async def delete_notebook(notebook_id: str) -> None:
    try:
        await notes_service.delete_notebook(notebook_id)
    except JoplinError as exc:
        _handle_joplin_error(exc)
