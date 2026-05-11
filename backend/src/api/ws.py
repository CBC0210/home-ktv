"""WebSocket endpoint — connection, authentication, message dispatch."""
import uuid
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, HTTPException

from ktv_pipeline.ws_manager import manager, ClientRole
from ktv_pipeline.auth import decode_access_token
from ktv_pipeline.database import get_db_session
from ktv_pipeline.models import Room, Guest

router = APIRouter()


def authenticate_websocket_token(token: str) -> dict:
    """Verify JWT and return payload. Raises WebSocket 4001 on failure."""
    try:
        payload = decode_access_token(token)
        return payload
    except HTTPException:
        # Convert HTTPException to WS close code 4001
        raise WebSocketDisconnect(code=4001)


@router.websocket("/ws")
async def ws_endpoint(
    websocket: WebSocket,
    token: str = Query(...),
):
    """WebSocket endpoint. Auth via ?token=<jwt>.
    
    After auth, the connection is registered in the manager.
    Incoming messages are handled in the dispatch loop.
    """
    # Authenticate
    try:
        payload = authenticate_websocket_token(token)
    except WebSocketDisconnect:
        await websocket.close(code=4001, reason="Invalid or expired session")
        return

    guest_id: str = payload["sub"]
    room_id: str = payload["room_id"]

    # Determine client role from query params (player / remote / admin)
    role_str = websocket.query_params.get("role", "remote")
    try:
        role = ClientRole(role_str)
    except ValueError:
        role = ClientRole.REMOTE

    client_id = str(uuid.uuid4())

    # Verify room still exists
    with get_db_session() as session:
        room = session.query(Room).filter_by(id=room_id).first()
        if not room:
            await websocket.close(code=4004, reason="Room not found")
            return

    # Register connection
    await manager.connect(
        websocket,
        client_id=client_id,
        role=role,
        room_id=room_id,
        guest_id=guest_id,
    )

    try:
        # Get guest nickname for broadcasts
        with get_db_session() as session:
            guest = session.query(Guest).filter_by(id=guest_id).first()
            nickname = guest.nickname if guest else "Unknown"

        # Dispatch loop
        while True:
            raw = await websocket.receive_text()
            await dispatch_message(client_id, room_id, guest_id, nickname, raw, role)

    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(client_id)


async def dispatch_message(
    client_id: str,
    room_id: str,
    guest_id: str,
    nickname: str,
    raw: str,
    role: ClientRole,
) -> None:
    """Parse and handle an inbound client message."""
    import json
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        await manager.send_to_client(client_id, {"type": "system.error", "message": "Invalid JSON"})
        return

    msg_type = msg.get("type", "")

    # ── Player status messages ─────────────────────────────────────────────────
    if role == ClientRole.PLAYER:
        if msg_type == "player.ready":
            await manager.send_to_role(room_id, ClientRole.REMOTE, {
                "type": "playback.state",
                "state": {"playing": False, "ready": True},
            })
        elif msg_type == "player.playing":
            position = msg.get("positionSec", 0)
            await manager.send_to_role(room_id, ClientRole.REMOTE, {
                "type": "playback.state",
                "state": {"playing": True, "positionSec": position},
            })
        elif msg_type == "player.buffering":
            await manager.send_to_role(room_id, ClientRole.REMOTE, {
                "type": "playback.state",
                "state": {"buffering": True},
            })
        elif msg_type == "player.error":
            await manager.broadcast_system_error(room_id, msg.get("error", "Unknown player error"))

    # ── Remote control messages ───────────────────────────────────────────────
    elif role == ClientRole.REMOTE:
        if msg_type == "reaction.send":
            emoji = msg.get("emoji", "👍")
            await manager.broadcast_reaction(room_id, emoji, nickname)

        elif msg_type == "playback.play":
            await manager.send_to_role(room_id, ClientRole.PLAYER, {"type": "playback.play"})
        elif msg_type == "playback.pause":
            await manager.send_to_role(room_id, ClientRole.PLAYER, {"type": "playback.pause"})
        elif msg_type == "playback.skip":
            await manager.send_to_role(room_id, ClientRole.PLAYER, {"type": "playback.skip"})
        elif msg_type == "playback.replay":
            await manager.send_to_role(room_id, ClientRole.PLAYER, {"type": "playback.replay"})
        elif msg_type == "playback.seek":
            position = msg.get("positionSec", 0)
            await manager.send_to_role(room_id, ClientRole.PLAYER, {"type": "playback.seek", "positionSec": position})

        elif msg_type == "queue.add":
            # This will be handled by queue router / pipeline trigger
            await manager.broadcast_system_error(room_id, "queue.add not yet implemented in WS")

        elif msg_type == "queue.remove":
            await manager.broadcast_system_error(room_id, "queue.remove not yet implemented in WS")

        elif msg_type == "queue.reorder":
            await manager.broadcast_system_error(room_id, "queue.reorder not yet implemented in WS")

    # ── Admin messages ─────────────────────────────────────────────────────────
    elif role == ClientRole.ADMIN:
        # Admin has full access; delegate to queue/rooms routers
        await manager.send_to_client(client_id, {"type": "system.error", "message": "Admin WS commands not yet implemented"})