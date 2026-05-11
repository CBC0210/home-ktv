"""WebSocket connection manager — handles rooms, broadcasting, client state."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
from enum import Enum

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class ClientRole(Enum):
    REMOTE = "remote"   # mobile / remote control
    PLAYER = "player"   # TV / display
    ADMIN = "admin"     # admin panel


@dataclass
class WSClient:
    websocket: WebSocket
    client_id: str
    role: ClientRole
    room_id: str
    guest_id: Optional[str] = None
    nickname: Optional[str] = None


class ConnectionManager:
    """Manages all WebSocket connections, room state, and broadcasting."""

    def __init__(self):
        # room_id -> set of client_ids
        self._rooms: Dict[str, Set[str]] = {}
        # client_id -> WSClient
        self._clients: Dict[str, WSClient] = {}
        # client_id -> asyncio.Lock (per-client send lock)
        self._client_locks: Dict[str, asyncio.Lock] = {}
        # Background task handles for cleanup
        self._background_tasks: Dict[str, asyncio.Task] = {}

    # ── Connection ─────────────────────────────────────────────────────────────

    async def connect(self, websocket: WebSocket, client_id: str, role: ClientRole, room_id: str, guest_id: Optional[str] = None, nickname: Optional[str] = None) -> None:
        """Register a new WebSocket client."""
        await websocket.accept()
        client = WSClient(
            websocket=websocket,
            client_id=client_id,
            role=role,
            room_id=room_id,
            guest_id=guest_id,
            nickname=nickname,
        )
        self._clients[client_id] = client
        self._client_locks[client_id] = asyncio.Lock()

        if room_id not in self._rooms:
            self._rooms[room_id] = set()
        self._rooms[room_id].add(client_id)

        logger.info(f"[WS] Client {client_id} ({role.value}) joined room {room_id}")

    async def disconnect(self, client_id: str) -> None:
        """Remove a client on disconnect."""
        if client_id not in self._clients:
            return
        client = self._clients[client_id]
        room_id = client.room_id

        if room_id in self._rooms:
            self._rooms[room_id].discard(client_id)
            if not self._rooms[room_id]:
                del self._rooms[room_id]

        del self._clients[client_id]
        if client_id in self._client_locks:
            del self._client_locks[client_id]

        logger.info(f"[WS] Client {client_id} disconnected from room {room_id}")

    def get_room_clients(self, room_id: str) -> List[WSClient]:
        """Return all clients in a room."""
        return [self._clients[cid] for cid in self._rooms.get(room_id, []) if cid in self._clients]

    def get_clients_by_role(self, room_id: str, role: ClientRole) -> List[WSClient]:
        """Return clients in a room filtered by role."""
        return [c for c in self.get_room_clients(room_id) if c.role == role]

    # ── Send helpers ──────────────────────────────────────────────────────────

    async def _send_json(self, client_id: str, data: dict) -> None:
        """Send a JSON dict to a specific client (thread-safe)."""
        if client_id not in self._client_locks:
            return
        lock = self._client_locks[client_id]
        async with lock:
            if client_id not in self._clients:
                return
            try:
                await self._clients[client_id].websocket.send_text(json.dumps(data))
            except Exception as exc:
                logger.warning(f"[WS] Failed to send to {client_id}: {exc}")

    async def send_to_client(self, client_id: str, data: dict) -> None:
        await self._send_json(client_id, data)

    async def send_to_room(self, room_id: str, data: dict, exclude: Optional[str] = None) -> None:
        """Broadcast a message to all clients in a room, optionally excluding one."""
        coros = []
        for client in self.get_room_clients(room_id):
            if exclude and client.client_id == exclude:
                continue
            coros.append(self._send_json(client.client_id, data))
        if coros:
            await asyncio.gather(*coros, return_exceptions=True)

    async def send_to_role(self, room_id: str, role: ClientRole, data: dict) -> None:
        """Send a message to all clients of a specific role in a room."""
        coros = [self._send_json(c.client_id, data) for c in self.get_clients_by_role(room_id, role)]
        if coros:
            await asyncio.gather(*coros, return_exceptions=True)

    # ── Server-initiated events ────────────────────────────────────────────────

    async def broadcast_queue_updated(self, room_id: str, queue: List[dict]) -> None:
        await self.send_to_room(room_id, {"type": "queue.updated", "queue": queue})

    async def broadcast_song_started(self, room_id: str, song: dict, queue_item: dict) -> None:
        await self.send_to_room(room_id, {"type": "song.started", "song": song, "queueItem": queue_item})

    async def broadcast_song_progress(self, room_id: str, position_sec: float) -> None:
        await self.send_to_room(room_id, {"type": "song.progress", "positionSec": position_sec})

    async def broadcast_song_ended(self, room_id: str, queue_item_id: int) -> None:
        await self.send_to_room(room_id, {"type": "song.ended", "queueItemId": queue_item_id})

    async def broadcast_song_processing(self, room_id: str, queue_item_id: int, stage: str, percent: float) -> None:
        await self.send_to_room(room_id, {
            "type": "song.processing",
            "queueItemId": queue_item_id,
            "stage": stage,
            "percent": percent,
        })

    async def broadcast_guests_updated(self, room_id: str, guests: List[dict]) -> None:
        await self.send_to_room(room_id, {"type": "guests.updated", "guests": guests})

    async def broadcast_playback_state(self, room_id: str, state: dict) -> None:
        await self.send_to_room(room_id, {"type": "playback.state", "state": state})

    async def broadcast_reaction(self, room_id: str, emoji: str, from_nickname: str) -> None:
        await self.send_to_room(room_id, {"type": "reaction", "emoji": emoji, "from": from_nickname})

    async def broadcast_system_error(self, room_id: str, message: str) -> None:
        await self.send_to_room(room_id, {"type": "system.error", "message": message})

    async def broadcast_lyrics_updated(self, room_id: str, song_id: str) -> None:
        """Notify Player clients in a room that lyrics.ass has been replaced."""
        await self.send_to_role(room_id, ClientRole.PLAYER, {
            "type": "lyrics.updated",
            "songId": song_id,
        })


# Global singleton
manager = ConnectionManager()