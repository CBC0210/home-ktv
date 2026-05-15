"""WebSocket endpoint — connection, authentication, message dispatch."""
import logging
import uuid
from typing import List, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, HTTPException

from ktv_pipeline.ws_manager import manager, ClientRole
from ktv_pipeline.auth import decode_access_token
from ktv_pipeline.database import get_db_session
from ktv_pipeline.models import Room, Guest

log = logging.getLogger(__name__)
router = APIRouter()


async def _get_room_guests_info(room_id: str) -> List[dict]:
    """Return guest info dicts for all guests currently connected to a room."""
    clients = manager.get_room_clients(room_id)
    guest_ids = list({c.guest_id for c in clients if c.guest_id})
    if not guest_ids:
        return []
    with get_db_session() as session:
        guests = session.query(Guest).filter(Guest.id.in_(guest_ids)).all()
        return [
            {"id": g.id, "nickname": g.nickname, "avatar_color": g.avatar_color, "is_admin": g.is_admin}
            for g in guests
        ]


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
    token: Optional[str] = Query(None),
    room_id: Optional[str] = Query(None),
    role: str = Query("remote"),
):
    """WebSocket endpoint. Auth via ?token=<jwt>.

    Player role (TV display) may connect without a token — it is a trusted
    local display device. All other roles require a valid guest JWT.
    After auth, the connection is registered in the manager.
    """
    role_str = role

    if token:
        try:
            payload = authenticate_websocket_token(token)
        except WebSocketDisconnect:
            await websocket.close(code=4001, reason="Invalid or expired session")
            return
        guest_id: str = payload["sub"]
        room_id_resolved: str = payload["room_id"]
    else:
        # Unauthenticated — only allowed for the player role (TV screen)
        if role_str != "player":
            await websocket.close(code=4001, reason="Token required for non-player roles")
            return
        if not room_id:
            await websocket.close(code=4004, reason="room_id required for player")
            return
        room_id_resolved = room_id
        guest_id = f"__player__{room_id_resolved}"

    # Determine client role enum
    try:
        client_role = ClientRole(role_str)
    except ValueError:
        client_role = ClientRole.REMOTE

    client_id = str(uuid.uuid4())

    # Verify room exists
    with get_db_session() as session:
        room_obj = session.query(Room).filter_by(id=room_id_resolved).first()
        if not room_obj:
            await websocket.close(code=4004, reason="Room not found")
            return

    # Register connection
    await manager.connect(
        websocket,
        client_id=client_id,
        role=client_role,
        room_id=room_id_resolved,
        guest_id=guest_id,
    )

    try:
        # Resolve nickname (players get a static label; guests look up DB)
        if token:
            with get_db_session() as session:
                guest = session.query(Guest).filter_by(id=guest_id).first()
                nickname = guest.nickname if guest else "Unknown"
        else:
            nickname = "Player"

        # Notify room of new guest (only for real guests, not the player device)
        if token:
            guests_info = await _get_room_guests_info(room_id_resolved)
            await manager.broadcast_guests_updated(room_id_resolved, guests_info)

        # Send the current playback state to the newly-connected client so a
        # refreshed Remote immediately shows correct volume / play state.
        await manager.send_to_client(client_id, {
            "type": "playback.state",
            "state": manager.get_playback_state(room_id_resolved),
        })

        # Dispatch loop
        while True:
            raw = await websocket.receive_text()
            await dispatch_message(client_id, room_id_resolved, guest_id, nickname, raw, client_role)

    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(client_id)
        # Notify remaining room members of the departure (only for real guests)
        if token:
            remaining = await _get_room_guests_info(room_id_resolved)
            await manager.broadcast_guests_updated(room_id_resolved, remaining)


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

    # Heartbeat — keep latency low and avoid log spam
    if msg_type == "ping":
        await manager.send_to_client(client_id, {"type": "pong"})
        return

    log.info("[WS in] room=%s role=%s msg_type=%s", room_id, role.value, msg_type)

    # ── Player status messages ─────────────────────────────────────────────────
    if role == ClientRole.PLAYER:
        if msg_type == "player.ready":
            # Send the full known state — covers Remote refresh case so the
            # phone immediately shows current volume / play state on connect.
            state = manager.get_playback_state(room_id)
            await manager.send_to_role(room_id, ClientRole.REMOTE, {
                "type": "playback.state",
                "state": state,
            })
        elif msg_type == "player.playing":
            position = msg.get("positionSec", 0)
            manager.update_playback_state(room_id, position_sec=position, is_playing=True)
            await manager.send_to_role(room_id, ClientRole.REMOTE, {
                "type": "song.progress",
                "positionSec": position,
            })
        elif msg_type == "player.buffering":
            # Just relay; frontend has no buffering UI yet
            pass
        elif msg_type == "player.ended":
            # Natural end of song — advance to next
            manager.update_playback_state(room_id, is_playing=False, position_sec=0)
            await _handle_song_advance(room_id)
        elif msg_type == "player.error":
            await manager.broadcast_system_error(room_id, msg.get("error", "Unknown player error"))

    # ── Remote control messages ───────────────────────────────────────────────
    elif role == ClientRole.REMOTE:
        if msg_type == "reaction.send":
            emoji = msg.get("emoji", "👍")
            await manager.broadcast_reaction(room_id, emoji, nickname)
            await manager.broadcast_activity(room_id, f"{emoji}", nickname)

        elif msg_type == "playback.play":
            manager.update_playback_state(room_id, is_playing=True)
            await manager.send_to_role(room_id, ClientRole.PLAYER, {"type": "playback.play"})
            await manager.send_to_role(room_id, ClientRole.REMOTE, {
                "type": "playback.state", "state": {"is_playing": True}
            })
            await manager.broadcast_activity(room_id, "▶ 播放", nickname)
        elif msg_type == "playback.pause":
            manager.update_playback_state(room_id, is_playing=False)
            await manager.send_to_role(room_id, ClientRole.PLAYER, {"type": "playback.pause"})
            await manager.send_to_role(room_id, ClientRole.REMOTE, {
                "type": "playback.state", "state": {"is_playing": False}
            })
            await manager.broadcast_activity(room_id, "⏸ 暫停", nickname)
        elif msg_type == "playback.skip":
            manager.update_playback_state(room_id, is_playing=False, position_sec=0)
            await manager.broadcast_activity(room_id, "⏭ 切下一首", nickname)
            await _handle_song_advance(room_id)
        elif msg_type == "playback.replay":
            manager.update_playback_state(room_id, is_playing=True, position_sec=0)
            await manager.send_to_role(room_id, ClientRole.PLAYER, {"type": "playback.replay"})
            await manager.send_to_role(room_id, ClientRole.REMOTE, {
                "type": "playback.state", "state": {"is_playing": True}
            })
            await manager.broadcast_activity(room_id, "🔁 重播", nickname)
        elif msg_type == "playback.seek":
            position = msg.get("positionSec", 0)
            manager.update_playback_state(room_id, position_sec=position)
            await manager.send_to_role(room_id, ClientRole.PLAYER, {"type": "playback.seek", "positionSec": position})
            mm = int(position // 60); ss = int(position % 60)
            await manager.broadcast_activity(room_id, f"⏩ 跳轉至 {mm}:{ss:02d}", nickname)

        elif msg_type == "playback.setVolume":
            main_v = float(msg["main"]) if "main" in msg else None
            vocal_v = float(msg["vocal"]) if "vocal" in msg else None
            manager.update_playback_state(room_id, main_volume=main_v, vocal_volume=vocal_v)
            fwd: dict = {"type": "playback.setVolume"}
            if main_v is not None:
                fwd["main"] = main_v
            if vocal_v is not None:
                fwd["vocal"] = vocal_v
            await manager.send_to_role(room_id, ClientRole.PLAYER, fwd)
            await manager.send_to_role(room_id, ClientRole.REMOTE, fwd)
            if main_v is not None:
                await manager.broadcast_activity(room_id, f"🔊 主音量 {int(main_v * 100)}%", nickname)
            if vocal_v is not None:
                await manager.broadcast_activity(room_id, f"🎤 人聲 {int(vocal_v * 100)}%", nickname)

        elif msg_type == "queue.add":
            await _handle_queue_add(room_id, guest_id, nickname, msg)

        elif msg_type == "queue.remove":
            await _handle_queue_remove(room_id, nickname, msg)

        elif msg_type == "queue.reorder":
            await _handle_queue_reorder(room_id, nickname, msg)

        elif msg_type == "lyrics.edit":
            await _handle_lyrics_edit(room_id, msg)

    # ── Admin messages ─────────────────────────────────────────────────────────
    elif role == ClientRole.ADMIN:
        # Admin has full access; delegate to queue/rooms routers
        await manager.send_to_client(client_id, {"type": "system.error", "message": "Admin WS commands not yet implemented"})


async def _handle_queue_add(room_id: str, guest_id: str, nickname: str, msg: dict) -> None:
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
            if song:
                await manager.broadcast_activity(room_id, f"➕ {song.title[:30]}", nickname)
    except Exception as exc:
        await manager.broadcast_system_error(room_id, f"queue.add failed: {exc}")


async def _handle_queue_remove(room_id: str, nickname: str, msg: dict) -> None:
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
            qi = session.query(QueueItem).filter_by(id=int(item_id)).first()
            song_title = None
            if qi:
                from ktv_pipeline.models import Song
                s = session.query(Song).filter_by(id=qi.song_id).first()
                song_title = s.title if s else None
            removed = mgr.remove_item(int(item_id))
            if removed:
                queue = mgr.get_queue(room_id)
                from ktv_pipeline.models import Song, Guest
                song_map = {s.id: s for s in session.query(Song).all()}
                guest_map = {g.id: g for g in session.query(Guest).all()}
                await manager.broadcast_queue_updated(room_id, [_qi_to_dict(qi, song_map.get(qi.song_id), guest_map.get(qi.guest_id)) for qi in queue])
                if song_title:
                    await manager.broadcast_activity(room_id, f"➖ {song_title[:30]}", nickname)
            else:
                await manager.broadcast_system_error(room_id, "Queue item not found")
    except Exception as exc:
        await manager.broadcast_system_error(room_id, f"queue.remove failed: {exc}")


async def _handle_queue_reorder(room_id: str, nickname: str, msg: dict) -> None:
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
            await manager.broadcast_activity(room_id, "🔀 重新排序隊列", nickname)
    except Exception as exc:
        await manager.broadcast_system_error(room_id, f"queue.reorder failed: {exc}")


async def _handle_song_advance(room_id: str) -> None:
    """Mark the currently-playing queue item as done, then start the next one."""
    from ktv_pipeline.queue_manager import QueueManager

    current_item_id = None
    with get_db_session() as session:
        mgr = QueueManager(session)
        playing = mgr.get_currently_playing(room_id)
        if playing:
            current_item_id = playing.id
            mgr.mark_done(playing.id)

    log.info("[advance] room=%s marked_done=%s", room_id, current_item_id)
    if current_item_id:
        await manager.broadcast_song_ended(room_id, current_item_id)

    await _start_next_song(room_id)


async def _start_next_song(room_id: str) -> None:
    """Find the next ready queue item and broadcast song.started.

    No-ops if a song is already playing — never interrupts current playback.
    """
    from ktv_pipeline.queue_manager import QueueManager
    from ktv_pipeline.models import Song, Guest, QueueItem

    with get_db_session() as session:
        mgr = QueueManager(session)

        # Guard: never interrupt a song that is already playing
        playing = mgr.get_currently_playing(room_id)
        if playing:
            log.info("[start_next] room=%s blocked by currently-playing QI#%s", room_id, playing.id)
            return

        # First, promote any 'pending' items whose song is already processed
        pending_items = (
            session.query(QueueItem)
            .filter_by(room_id=room_id, status="pending")
            .all()
        )
        for qi in pending_items:
            s = session.query(Song).filter_by(id=qi.song_id).first()
            if s and s.status == "ready":
                qi.status = "ready"
        session.commit()

        next_item = (
            session.query(QueueItem)
            .filter_by(room_id=room_id, status="ready")
            .order_by(QueueItem.position)
            .first()
        )
        if not next_item:
            # No ready song. Refresh queue and notify caller; pipeline completion
            # of any processing item will retrigger _start_next_song.
            queue = mgr.get_queue(room_id)
            song_map = {s.id: s for s in session.query(Song).all()}
            guest_map = {g.id: g for g in session.query(Guest).all()}
            await manager.broadcast_queue_updated(
                room_id,
                [_qi_to_dict(qi, song_map.get(qi.song_id), guest_map.get(qi.guest_id)) for qi in queue],
            )
            # If anything is mid-pipeline, surface its progress
            processing = next(
                (qi for qi in queue if qi.status in (
                    "pending", "processing", "downloading", "separating",
                    "fetching_lyrics", "aligning", "packaging",
                )), None,
            )
            if processing:
                await manager.broadcast_song_processing(
                    room_id, processing.id, processing.status, 0,
                )
            return

        log.info("[start_next] room=%s picked QI#%s song=%s", room_id, next_item.id, next_item.song_id)
        item = mgr.mark_playing(next_item.id)
        if not item:
            return

        song = session.query(Song).filter_by(id=item.song_id).first()
        guest = session.query(Guest).filter_by(id=item.guest_id).first()

        song_dict = {
            "id": song.id,
            "title": song.title,
            "artist": song.artist,
            "duration_sec": song.duration_sec,
            "thumbnail_url": song.thumbnail_url,
            "status": song.status,
            "has_timing": song.has_timing,
            "lyrics_source": song.lyrics_source,
            "error_message": song.error_message,
        } if song else {}

        qi_dict = _qi_to_dict(item, song, guest)

        queue = mgr.get_queue(room_id)
        song_map = {s.id: s for s in session.query(Song).all()}
        guest_map = {g.id: g for g in session.query(Guest).all()}
        queue_dicts = [_qi_to_dict(qi, song_map.get(qi.song_id), guest_map.get(qi.guest_id)) for qi in queue]

    await manager.broadcast_song_started(room_id, song_dict, qi_dict)
    await manager.broadcast_queue_updated(room_id, queue_dicts)

    # Anything still pending in the queue should be in pipeline.
    await _preload_upcoming(room_id, skip_item_id=item.id)


async def _preload_upcoming(room_id: str, *, skip_item_id: int) -> None:
    """Trigger pipeline for every pending queue item.

    No-op for items whose Song is already in-flight or ready. Pipeline tasks
    are idempotent (each stage checks cache), so triggering twice is safe.
    GPU stages serialize internally via _gpu_lock.
    """
    import asyncio
    from ktv_pipeline.models import Song, QueueItem
    from api.songs import _run_pipeline_task

    started = 0
    with get_db_session() as session:
        upcoming = (
            session.query(QueueItem)
            .filter(
                QueueItem.room_id == room_id,
                QueueItem.id != skip_item_id,
                QueueItem.status == "pending",
            )
            .order_by(QueueItem.position)
            .all()
        )
        for qi in upcoming:
            s = session.query(Song).filter_by(id=qi.song_id).first()
            if not s:
                continue
            if s.status in ("processing", "downloading", "separating",
                            "fetching_lyrics", "aligning", "packaging", "ready"):
                continue
            asyncio.create_task(_run_pipeline_task(qi.id, room_id))
            started += 1
    if started:
        log.info("[preload] room=%s kicked %d pending pipelines", room_id, started)


async def _handle_lyrics_edit(room_id: str, msg: dict) -> None:
    """Handle lyrics.edit from remote — overwrite cached ASS and notify Player."""
    song_id = msg.get("songId")
    ass_content = msg.get("ass", "")
    if not song_id or not ass_content.strip():
        await manager.broadcast_system_error(room_id, "lyrics.edit: missing songId or ass content")
        return
    try:
        from ktv_pipeline.config import settings
        ass_path = settings.data_dir / "media" / song_id / "lyrics.ass"
        ass_path.parent.mkdir(parents=True, exist_ok=True)
        ass_path.write_text(ass_content, encoding="utf-8")
        await manager.broadcast_lyrics_updated(room_id, song_id)
    except Exception as exc:
        await manager.broadcast_system_error(room_id, f"lyrics.edit failed: {exc}")


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