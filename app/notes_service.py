from __future__ import annotations

import asyncio
import uuid

from .joplin_client import JoplinNotFound, joplin_client
from .models import Note, NoteCreate, NoteSummary, NoteUpdate, Notebook, NotebookCreate
from .note_format import (
    TYPE_FOLDER,
    TYPE_NOTE,
    TYPE_RESOURCE,
    now_iso,
    parse_item,
    serialize_item,
)

_FETCH_CONCURRENCY = 20


def _new_id() -> str:
    return uuid.uuid4().hex


def _note_from_fields(fields: dict[str, str]) -> Note:
    return Note(
        id=fields["id"],
        parent_id=fields.get("parent_id", ""),
        title=fields.get("title", ""),
        body=fields.get("body", ""),
        is_todo=fields.get("is_todo") == "1",
        todo_completed=fields.get("todo_completed", "0") not in ("0", ""),
        created_time=fields.get("created_time"),
        updated_time=fields.get("updated_time"),
    )


def _note_summary_from_fields(fields: dict[str, str]) -> NoteSummary:
    return NoteSummary(
        id=fields["id"],
        parent_id=fields.get("parent_id", ""),
        title=fields.get("title", ""),
        is_todo=fields.get("is_todo") == "1",
        todo_completed=fields.get("todo_completed", "0") not in ("0", ""),
        created_time=fields.get("created_time"),
        updated_time=fields.get("updated_time"),
    )


def _notebook_from_fields(fields: dict[str, str]) -> Notebook:
    return Notebook(
        id=fields["id"],
        parent_id=fields.get("parent_id", ""),
        title=fields.get("title", ""),
    )


async def _get_fields(item_id: str) -> dict[str, str]:
    content = await joplin_client.get_content(item_id)
    return parse_item(content)


async def get_note(note_id: str) -> Note:
    fields = await _get_fields(note_id)
    if fields.get("type_") != str(TYPE_NOTE):
        raise JoplinNotFound(404, f"Item is not a note: {note_id}")
    return _note_from_fields(fields)


async def get_notebook(notebook_id: str) -> Notebook:
    fields = await _get_fields(notebook_id)
    if fields.get("type_") != str(TYPE_FOLDER):
        raise JoplinNotFound(404, f"Item is not a notebook: {notebook_id}")
    return _notebook_from_fields(fields)


async def create_note(data: NoteCreate) -> Note:
    note_id = _new_id()
    ts = now_iso()
    props = {
        "id": note_id,
        "parent_id": data.parent_id,
        "created_time": ts,
        "updated_time": ts,
        "is_conflict": "0",
        "latitude": "0.00000000",
        "longitude": "0.00000000",
        "altitude": "0.0000",
        "author": "",
        "source_url": "",
        "is_todo": "1" if data.is_todo else "0",
        "todo_due": "0",
        "todo_completed": "0",
        "source": "notes-api",
        "source_application": "net.ajvc.notes-api",
        "application_data": "",
        "order": "0",
        "user_created_time": ts,
        "user_updated_time": ts,
        "encryption_cipher_text": "",
        "encryption_applied": "0",
        "markup_language": "1",
        "is_shared": "0",
        "share_id": "",
        "conflict_original_id": "",
        "master_key_id": "",
        "type_": str(TYPE_NOTE),
    }
    content = serialize_item(data.title, data.body, props)
    await joplin_client.put_content(note_id, content)
    return await get_note(note_id)


async def update_note(note_id: str, data: NoteUpdate) -> Note:
    fields = await _get_fields(note_id)
    if fields.get("type_") != str(TYPE_NOTE):
        raise JoplinNotFound(404, f"Item is not a note: {note_id}")

    title = data.title if data.title is not None else fields.get("title", "")
    body = data.body if data.body is not None else fields.get("body", "")
    if data.parent_id is not None:
        fields["parent_id"] = data.parent_id
    if data.is_todo is not None:
        fields["is_todo"] = "1" if data.is_todo else "0"
    if data.todo_completed is not None:
        fields["todo_completed"] = "1" if data.todo_completed else "0"
    fields["updated_time"] = now_iso()
    fields["user_updated_time"] = fields["updated_time"]

    props = {k: v for k, v in fields.items() if k not in ("title", "body")}
    content = serialize_item(title, body, props)
    await joplin_client.put_content(note_id, content)
    return await get_note(note_id)


async def delete_note(note_id: str) -> None:
    fields = await _get_fields(note_id)
    if fields.get("type_") != str(TYPE_NOTE):
        raise JoplinNotFound(404, f"Item is not a note: {note_id}")
    await joplin_client.delete_item(note_id)


async def create_notebook(data: NotebookCreate) -> Notebook:
    notebook_id = _new_id()
    ts = now_iso()
    props = {
        "id": notebook_id,
        "created_time": ts,
        "updated_time": ts,
        "user_created_time": ts,
        "user_updated_time": ts,
        "encryption_cipher_text": "",
        "encryption_applied": "0",
        "parent_id": data.parent_id,
        "is_shared": "0",
        "share_id": "",
        "master_key_id": "",
        "icon": "",
        "type_": str(TYPE_FOLDER),
    }
    content = serialize_item(data.title, None, props)
    await joplin_client.put_content(notebook_id, content)
    return await get_notebook(notebook_id)


async def delete_notebook(notebook_id: str) -> None:
    fields = await _get_fields(notebook_id)
    if fields.get("type_") != str(TYPE_FOLDER):
        raise JoplinNotFound(404, f"Item is not a notebook: {notebook_id}")
    await joplin_client.delete_item(notebook_id)


async def _fetch_all_fields() -> list[dict[str, str]]:
    ids = await joplin_client.list_all_item_names()
    semaphore = asyncio.Semaphore(_FETCH_CONCURRENCY)

    async def fetch(item_id: str) -> dict[str, str] | None:
        async with semaphore:
            try:
                return await _get_fields(item_id)
            except JoplinNotFound:
                return None

    results = await asyncio.gather(*(fetch(item_id) for item_id in ids))
    return [fields for fields in results if fields is not None]


async def list_notes(parent_id: str | None = None) -> list[NoteSummary]:
    """Lists notes without their body - Joplin Server has no metadata-only
    listing endpoint, so every note's content still has to be fetched and
    parsed to know its title/type/parent_id, but the (often large) body
    text is dropped before returning. Use get_note() for full content."""
    all_fields = await _fetch_all_fields()
    notes = [
        _note_summary_from_fields(fields)
        for fields in all_fields
        if fields.get("type_") == str(TYPE_NOTE)
    ]
    if parent_id is not None:
        notes = [note for note in notes if note.parent_id == parent_id]
    return notes


async def attach_file(note_id: str, filename: str, mime: str, content: bytes) -> Note:
    """Uploads `content` as a Joplin resource and appends it to the note's body."""
    fields = await _get_fields(note_id)
    if fields.get("type_") != str(TYPE_NOTE):
        raise JoplinNotFound(404, f"Item is not a note: {note_id}")

    resource_id = _new_id()
    ts = now_iso()
    extension = filename.rsplit(".", 1)[-1] if "." in filename else ""
    resource_props = {
        "id": resource_id,
        "mime": mime,
        "filename": "",
        "created_time": ts,
        "updated_time": ts,
        "user_created_time": ts,
        "user_updated_time": ts,
        "file_extension": extension,
        "encryption_cipher_text": "",
        "encryption_applied": "0",
        "encryption_blob_encrypted": "0",
        "size": str(len(content)),
        "is_shared": "0",
        "share_id": "",
        "master_key_id": "",
        "blob_updated_time": ts,
        "ocr_text": "",
        "ocr_status": "0",
        "ocr_error": "",
        "type_": str(TYPE_RESOURCE),
    }
    resource_content = serialize_item(filename, None, resource_props)
    await joplin_client.put_content(resource_id, resource_content)
    await joplin_client.put_blob(resource_id, content)

    markdown_ref = f"![{filename}](:/{resource_id})" if mime.startswith("image/") else f"[{filename}](:/{resource_id})"
    fields["body"] = f"{fields.get('body', '')}\n\n{markdown_ref}".strip()
    fields["updated_time"] = now_iso()
    fields["user_updated_time"] = fields["updated_time"]

    title = fields["title"]
    body = fields["body"]
    props = {k: v for k, v in fields.items() if k not in ("title", "body")}
    updated_content = serialize_item(title, body, props)
    await joplin_client.put_content(note_id, updated_content)
    return await get_note(note_id)


async def list_notebooks() -> list[Notebook]:
    all_fields = await _fetch_all_fields()
    return [
        _notebook_from_fields(fields)
        for fields in all_fields
        if fields.get("type_") == str(TYPE_FOLDER)
    ]
