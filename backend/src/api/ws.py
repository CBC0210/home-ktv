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
                "type": "song.progress",
                "positionSec": position,
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
            await _handle_queue_add(room_id, guest_id, msg)

        elif msg_type == "queue.remove":
            await _handle_queue_remove(room_id, msg)

        elif msg_type == "queue.reorder":
            await _handle_queue_reorder(room_id, msg)

    # ── Admin messages ─────────────────────────────────────────────────────────
    elif role == ClientRole.ADMIN:
        # Admin has full access; delegate to queue/rooms routers
        await manager.send_to_client(client_id, {"type": "system.error", "message": "Admin WS commands not yet implemented"})


async def _handle_queue_add(room_id: str, guest_id: str, msg: dict) -> None:
    """Handle queue.add from remote — add song via QueueManager."""
    song_id = msg.get("song_id") or msg.get("youtubeId")
    if not song_id:
        await manager.broadcast_system_error(room_id, "queue.add: missing song_id")
        return
    from ktv_pipeline.queue_manager import QueueManager
    from ktv_pipeline.database import get_db_session
    try:
        with get_db_session() as session:
            mgr = QueueManager(session)
            try:
                item = mgr.add_song(room_id=room_id, song_id=song_id, guest_id=guest_id, position="end")
            except ValueError as exc:
                await manager.broadcast_system_error(room_id, str(exc))
                return
            # Reload song + guest for broadcast
            from ktv_pipeline.models import Song, Guest
            song = session.query(Song).filter_by(id=song_id).first()
            guest = session.query(Guest).filter_by(id=guest_id).first()
            queue = mgr.get_queue(room_id)
            await manager.broadcast_queue_updated(room_id, [_qi_to_dict(qi, song if qi.song_id == song_id else None, guest if qi.guest_id == guest_id else None) for qi in queue])
    except Exception as exc:
        await manager.broadcast_system_error(room_id, f"queue.add failed: {exc}")


async def _handle_queue_remove(room_id: str, msg: dict) -> None:
    """Handle queue.remove from remote — remove item via QueueManager."""
    item_id = msg.get("queueItemId")
    if not item_id:
        await manager.broadcast_system_error(room_id, "queue.remove: missing queueItemId")
        return
    from ktv_pipeline.queue_manager import QueueManager
    from ktv_pipeline.database import get_db_session
    try:
        with get_db_session() as session:
            mgr = QueueManager(session)
            removed = mgr.remove_item(int(item_id))
            if removed:
                queue = mgr.get_queue(room_id)
                from ktv_pipeline.models import Song, Guest
                song_map = {s.id: s for s in session.query(Song).all()}
                guest_map = {g.id: g for g in session.query(Guest).all()}
                await manager.broadcast_queue_updated(room_id, [_qi_to_dict(qi, song_map.get(qi.song_id), guest_map.get(qi.guest_id)) for qi in queue])
            else:
                await manager.broadcast_system_error(room_id, "Queue item not found")
    except Exception as exc:
        await manager.broadcast_system_error(room_id, f"queue.remove failed: {exc}")


async def _handle_queue_reorder(room_id: str, msg: dict) -> None:
    """Handle queue.reorder from remote/admin — reorder queue positions."""
    item_ids = msg.get("queueItemIds", [])
    if not item_ids:
        await manager.broadcast_system_error(room_id, "queue.reorder: missing queueItemIds")
        return
    from ktv_pipeline.queue_manager import QueueManager
    from ktv_pipeline.database import get_db_session
    try:
        with get_db_session() as session:
            mgr = QueueManager(session)
            mgr.reorder(room_id, [int(i) for i in item_ids])
            queue = mgr.get_queue(room_id)
            from ktv_pipeline.models import Song, Guest
            song_map = {s.id: s for s in session.query(Song).all()}
            guest_map = {g.id: g for g in session.query(Guest).all()}
            await manager.broadcast_queue_updated(room_id, [_qi_to_dict(qi, song_map.get(qi.song_id), guest_map.get(qi.guest_id)) for qi in queue])
    except Exception as exc:
        await manager.broadcast_system_error(room_id, f"queue.reorder failed: {exc}")


def _qi_to_dict(qi, song, guest) -> dict:
    """Convert a QueueItem + related objects to a broadcastable dict."""
    return {
        "id": qi.id,
        "room_id": qi.room_id,
        "song_id": qi.song_id,
        "guest_id": qi.guest_id,
        "added_at": qi.added_at.isoformat() if qi.added_at else None,
        "position": qi.position,
        "status": qi.status,
        "played_at": qi.played_at.isoformat() if qi.played_at else None,
        "manually_moved": qi.manually_moved,
        "song": {
            "id": song.id,
            "title": song.title,
            "artist": song.artist,
            "duration_sec": song.duration_sec,
            "thumbnail_url": song.thumbnail_url,
            "status": song.status,
            "has_timing": song.has_timing,
            "lyrics_source": song.lyrics_source,
        } if song else None,
        "guest": {
            "id": guest.id,
            "nickname": guest.nickname,
            "avatar_color": guest.avatar_color,
            "is_admin": guest.is_admin,
        } if guest else None,
    }