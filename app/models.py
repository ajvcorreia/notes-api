from __future__ import annotations

from pydantic import BaseModel, Field


class Note(BaseModel):
    id: str
    parent_id: str = ""
    title: str
    body: str
    is_todo: bool = False
    todo_completed: bool = False
    created_time: str | None = None
    updated_time: str | None = None


class NoteCreate(BaseModel):
    title: str
    body: str = ""
    parent_id: str = Field("", description="Notebook id to file the note under, empty for none")
    is_todo: bool = False


class NoteUpdate(BaseModel):
    title: str | None = None
    body: str | None = None
    parent_id: str | None = None
    is_todo: bool | None = None
    todo_completed: bool | None = None


class Notebook(BaseModel):
    id: str
    parent_id: str = ""
    title: str


class NotebookCreate(BaseModel):
    title: str
    parent_id: str = ""
