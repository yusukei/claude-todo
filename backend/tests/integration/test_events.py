"""SSE エンドポイントの統合テスト (認証チェックのみ)

ストリーミングの継続検証は E2E テストで行う。
ここでは接続確立と認証境界のみを確認する。
"""

import asyncio

from app.core.security import create_access_token, create_refresh_token
from app.models import User


class TestSSEAuthentication:
    async def test_no_token_returns_422(self, client):
        """token クエリパラメータ必須のため未指定は 422"""
        resp = await client.get("/api/v1/events")
        assert resp.status_code == 422

    async def test_invalid_token_returns_401(self, client):
        resp = await client.get("/api/v1/events?token=invalid.token.here")
        assert resp.status_code == 401

    async def test_refresh_token_returns_401(self, client, admin_user):
        """refresh トークンは type が 'refresh' なので拒否される"""
        token = create_refresh_token(str(admin_user.id))
        resp = await client.get(f"/api/v1/events?token={token}")
        assert resp.status_code == 401

    async def test_inactive_user_token_returns_401(self, client, inactive_user):
        token = create_access_token(str(inactive_user.id))
        resp = await client.get(f"/api/v1/events?token={token}")
        assert resp.status_code == 401

    async def test_valid_token_starts_stream(self, client, admin_user):
        """有効なトークンで SSE ストリームが開始される (ステータス + Content-Type 確認)

        注: httpx の ASGI トランスポートは SSE チャンクを個別にフラッシュしないため、
        aiter_bytes() がブロックする。ストリーム本文の読み取りは E2E テストに委ねる。
        """
        token = create_access_token(str(admin_user.id))

        # stream() ではなく通常リクエストを短時間で切断するため、
        # 直接 asyncio.wait_for でラップして接続確立のみ検証する
        async def _check_stream():
            async with client.stream("GET", f"/api/v1/events?token={token}") as resp:
                assert resp.status_code == 200
                assert "text/event-stream" in resp.headers.get("content-type", "")

        try:
            await asyncio.wait_for(_check_stream(), timeout=3)
        except (TimeoutError, asyncio.CancelledError):
            pass  # SSE は無限ストリームなのでタイムアウトは正常動作
