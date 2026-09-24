from typing import Any
from urllib.parse import quote

import httpx
from fastapi import HTTPException, status

from app.config import Settings


class SupabaseClient:
    _shared_http: httpx.AsyncClient | None = None

    def __init__(self, settings: Settings):
        self.settings = settings

    @classmethod
    def _http(cls) -> httpx.AsyncClient:
        if (
            cls._shared_http is None
            or getattr(
                cls._shared_http,
                "is_closed",
                False,
            )
        ):
            cls._shared_http = httpx.AsyncClient(
                timeout=30,
                limits=httpx.Limits(
                    max_connections=50,
                    max_keepalive_connections=20,
                    keepalive_expiry=30,
                ),
            )

        return cls._shared_http

    @classmethod
    async def close_shared_http(cls) -> None:
        if (
            cls._shared_http is not None
            and not getattr(
                cls._shared_http,
                "is_closed",
                False,
            )
        ):
            close = getattr(
                cls._shared_http,
                "aclose",
                None,
            )

            if close:
                await close()

        cls._shared_http = None

    def _headers(
        self,
        *,
        token: str | None = None,
        prefer: str | None = None,
    ) -> dict[str, str]:
        key = self.settings.supabase_secret_key

        headers = {
            "apikey": key,
            "Authorization": (
                f"Bearer {token or key}"
            ),
            "Content-Type": "application/json",
        }

        if prefer:
            headers["Prefer"] = prefer

        return headers

    async def query(
        self,
        table: str,
        query: str = "",
        *,
        token: str | None = None,
    ) -> list[dict[str, Any]]:
        self._require_config()

        response = await self._http().get(
            (
                f"{self.settings.supabase_url}"
                f"/rest/v1/{table}?{query}"
            ),
            headers=self._headers(token=token),
        )

        self._raise(response)

        return response.json()

    async def insert(
        self,
        table: str,
        payload: dict[str, Any],
        *,
        token: str | None = None,
    ) -> list[dict[str, Any]]:
        self._require_config()

        response = await self._http().post(
            (
                f"{self.settings.supabase_url}"
                f"/rest/v1/{table}"
            ),
            headers=self._headers(
                token=token,
                prefer="return=representation",
            ),
            json=payload,
        )

        self._raise(response)

        return response.json()

    async def update(
        self,
        table: str,
        query: str,
        payload: dict[str, Any],
        *,
        token: str | None = None,
    ) -> list[dict[str, Any]]:
        self._require_config()

        response = await self._http().patch(
            (
                f"{self.settings.supabase_url}"
                f"/rest/v1/{table}?{query}"
            ),
            headers=self._headers(
                token=token,
                prefer="return=representation",
            ),
            json=payload,
        )

        self._raise(response)

        return response.json()

    async def delete(
        self,
        table: str,
        query: str,
        *,
        token: str | None = None,
    ) -> None:
        self._require_config()

        response = await self._http().delete(
            (
                f"{self.settings.supabase_url}"
                f"/rest/v1/{table}?{query}"
            ),
            headers=self._headers(token=token),
        )

        self._raise(response)

    async def login(
        self,
        email: str,
        password: str,
    ) -> dict[str, Any]:
        response = await self._http().post(
            (
                f"{self.settings.supabase_url}"
                "/auth/v1/token"
                "?grant_type=password"
            ),
            headers={
                "apikey": (
                    self.settings
                    .supabase_publishable_key
                ),
                "Content-Type": (
                    "application/json"
                ),
            },
            json={
                "email": email,
                "password": password,
            },
        )

        if response.status_code >= 400:
            raise HTTPException(
                status_code=(
                    status.HTTP_401_UNAUTHORIZED
                ),
                detail=(
                    "Invalid login credentials"
                ),
            )

        return response.json()

    async def auth_user(
        self,
        token: str,
    ) -> dict[str, Any]:
        response = await self._http().get(
            (
                f"{self.settings.supabase_url}"
                "/auth/v1/user"
            ),
            headers={
                "apikey": (
                    self.settings
                    .supabase_publishable_key
                ),
                "Authorization": (
                    f"Bearer {token}"
                ),
            },
        )

        if response.status_code >= 400:
            raise HTTPException(
                status_code=(
                    status.HTTP_401_UNAUTHORIZED
                ),
                detail=(
                    "Session is invalid or expired"
                ),
            )

        return response.json()

    async def create_user(
        self,
        email: str,
        password: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        response = await self._http().post(
            (
                f"{self.settings.supabase_url}"
                "/auth/v1/admin/users"
            ),
            headers=self._headers(),
            json={
                "email": email,
                "password": password,
                "email_confirm": True,
                "user_metadata": metadata,
            },
        )

        self._raise(response)

        return response.json()

    async def find_auth_user_by_email(
        self,
        email: str,
    ) -> dict[str, Any] | None:
        response = await self._http().get(
            (
                f"{self.settings.supabase_url}"
                "/auth/v1/admin/users"
                "?page=1&per_page=1000"
            ),
            headers=self._headers(),
        )

        self._raise(response)

        target = email.strip().lower()

        response_data = response.json()
        users = response_data.get(
            "users",
            [],
        )

        for user in users:
            user_email = str(
                user.get("email") or ""
            ).strip().lower()

            if user_email == target:
                return user

        return None

    async def update_user_password(
        self,
        auth_user_id: str,
        password: str,
    ) -> None:
        response = await self._http().put(
            (
                f"{self.settings.supabase_url}"
                "/auth/v1/admin/users/"
                f"{auth_user_id}"
            ),
            headers=self._headers(),
            json={
                "password": password,
            },
        )

        self._raise(response)

    async def update_own_password(
        self,
        token: str,
        password: str,
    ) -> None:
        response = await self._http().put(
            (
                f"{self.settings.supabase_url}"
                "/auth/v1/user"
            ),
            headers={
                "apikey": (
                    self.settings
                    .supabase_publishable_key
                ),
                "Authorization": (
                    f"Bearer {token}"
                ),
                "Content-Type": (
                    "application/json"
                ),
            },
            json={
                "password": password,
            },
        )

        self._raise(response)

    async def refresh(
        self,
        refresh_token: str,
    ) -> dict[str, Any]:
        response = await self._http().post(
            (
                f"{self.settings.supabase_url}"
                "/auth/v1/token"
                "?grant_type=refresh_token"
            ),
            headers={
                "apikey": (
                    self.settings
                    .supabase_publishable_key
                ),
                "Content-Type": (
                    "application/json"
                ),
            },
            json={
                "refresh_token": refresh_token,
            },
        )

        if response.status_code >= 400:
            raise HTTPException(
                status_code=(
                    status.HTTP_401_UNAUTHORIZED
                ),
                detail=(
                    "Session is invalid or expired"
                ),
            )

        return response.json()

    async def upload_object(
        self,
        bucket: str,
        path: str,
        content: bytes,
        content_type: str,
    ) -> None:
        self._require_config()

        safe_path = quote(
            path,
            safe="/",
        )

        response = await self._http().post(
            (
                f"{self.settings.supabase_url}"
                "/storage/v1/object/"
                f"{bucket}/{safe_path}"
            ),
            headers={
                **self._headers(),
                "Content-Type": content_type,
                "x-upsert": "false",
            },
            content=content,
        )

        self._raise(response)

    async def signed_object_url(
        self,
        bucket: str,
        path: str,
        expires_in: int = 300,
    ) -> str:
        self._require_config()

        safe_path = quote(
            path,
            safe="/",
        )

        response = await self._http().post(
            (
                f"{self.settings.supabase_url}"
                "/storage/v1/object/sign/"
                f"{bucket}/{safe_path}"
            ),
            headers=self._headers(),
            json={
                "expiresIn": expires_in,
            },
        )

        self._raise(response)

        response_data = response.json()

        signed = (
            response_data.get("signedURL")
            or response_data.get("signedUrl")
        )

        if not signed:
            raise HTTPException(
                status_code=502,
                detail=(
                    "Document link could not "
                    "be created"
                ),
            )

        if signed.startswith("http"):
            return signed

        return (
            f"{self.settings.supabase_url}"
            f"/storage/v1{signed}"
        )

    async def delete_object(
        self,
        bucket: str,
        path: str,
    ) -> None:
        self._require_config()

        response = await self._http().request(
            "DELETE",
            (
                f"{self.settings.supabase_url}"
                "/storage/v1/object/"
                f"{bucket}"
            ),
            headers=self._headers(),
            json={
                "prefixes": [path],
            },
        )

        self._raise(response)

    async def download_object(
        self,
        bucket: str,
        path: str,
    ) -> bytes:
        """
        Download a private object using the
        service-role credentials.
        """

        self._require_config()

        safe_path = quote(
            path,
            safe="/",
        )

        response = await self._http().get(
            (
                f"{self.settings.supabase_url}"
                "/storage/v1/object/"
                "authenticated/"
                f"{bucket}/{safe_path}"
            ),
            headers=self._headers(),
        )

        self._raise(response)

        return response.content

    def _require_config(self) -> None:
        if not self.settings.supabase_ready:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Database is not configured"
                ),
            )

    @staticmethod
    def eq(value: str) -> str:
        return (
            f"eq.{quote(value, safe='')}"
        )

    @staticmethod
    def _raise(
        response: httpx.Response,
    ) -> None:
        if response.status_code < 400:
            return

        detail: Any = "Database request failed"

        try:
            response_data = response.json()

            if isinstance(response_data, dict):
                detail = (
                    response_data.get("message")
                    or response_data.get("msg")
                    or response_data.get(
                        "error_description"
                    )
                    or response_data.get("error")
                    or detail
                )
        except ValueError:
            pass

        if isinstance(detail, dict):
            detail = (
                detail.get("message")
                or detail.get("msg")
                or "Database request failed"
            )

        raise HTTPException(
            status_code=502,
            detail=str(detail),
        )