from __future__ import annotations

import asyncio

import httpx

from .config import settings


class JoplinError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


class JoplinNotFound(JoplinError):
    pass


def _item_path(item_id: str) -> str:
    return f"root:/{item_id}.md:"


def _blob_path(resource_id: str) -> str:
    # Resource binary content lives under the flat ".resource/<id>" namespace,
    # separate from the "<id>.md" item that holds the resource's metadata.
    return f"root:/.resource%2F{resource_id}:"


class JoplinClient:
    """Thin async wrapper around Joplin Server's item (sync target) REST API."""

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(base_url=settings.joplin_base_url, timeout=30.0)
        self._session_id: str | None = None
        self._login_lock = asyncio.Lock()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _login(self) -> str:
        async with self._login_lock:
            resp = await self._client.post(
                "/api/sessions",
                json={"email": settings.joplin_email, "password": settings.joplin_password},
            )
            if resp.status_code != 200:
                raise JoplinError(resp.status_code, f"Joplin login failed: {resp.text}")
            self._session_id = resp.json()["id"]
            return self._session_id

    async def _request(self, method: str, path: str, retry: bool = True, **kwargs) -> httpx.Response:
        if self._session_id is None:
            await self._login()

        headers = kwargs.pop("headers", {})
        headers["X-API-AUTH"] = self._session_id
        resp = await self._client.request(method, path, headers=headers, **kwargs)

        if resp.status_code == 403 and retry:
            await self._login()
            return await self._request(method, path, retry=False, **kwargs)

        return resp

    async def get_content(self, item_id: str) -> str:
        resp = await self._request("GET", f"/api/items/{_item_path(item_id)}/content")
        if resp.status_code == 404:
            raise JoplinNotFound(404, f"Item not found: {item_id}")
        if resp.status_code != 200:
            raise JoplinError(resp.status_code, resp.text)
        return resp.text

    async def put_content(self, item_id: str, content: str) -> None:
        resp = await self._request(
            "PUT",
            f"/api/items/{_item_path(item_id)}/content",
            headers={"Content-Type": "application/octet-stream"},
            content=content.encode("utf-8"),
        )
        if resp.status_code != 200:
            raise JoplinError(resp.status_code, resp.text)

    async def delete_item(self, item_id: str) -> None:
        resp = await self._request("DELETE", f"/api/items/{_item_path(item_id)}")
        if resp.status_code == 404:
            raise JoplinNotFound(404, f"Item not found: {item_id}")
        if resp.status_code != 200:
            raise JoplinError(resp.status_code, resp.text)

    async def put_blob(self, resource_id: str, content: bytes) -> None:
        resp = await self._request(
            "PUT",
            f"/api/items/{_blob_path(resource_id)}/content",
            headers={"Content-Type": "application/octet-stream"},
            content=content,
        )
        if resp.status_code != 200:
            raise JoplinError(resp.status_code, resp.text)

    async def list_root_children(self, cursor: str | None = None, limit: int = 100) -> dict:
        params = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        resp = await self._request("GET", "/api/items/root:/:/children", params=params)
        if resp.status_code != 200:
            raise JoplinError(resp.status_code, resp.text)
        return resp.json()

    async def list_all_item_names(self) -> list[str]:
        """Returns the 32-char ids of every item (note or folder) on the server."""
        ids: list[str] = []
        cursor: str | None = None
        while True:
            page = await self.list_root_children(cursor=cursor)
            for entry in page["items"]:
                name = entry["name"]
                if name.endswith(".md"):
                    ids.append(name[: -len(".md")])
            if not page.get("has_more"):
                break
            cursor = page.get("cursor")
        return ids


joplin_client = JoplinClient()
