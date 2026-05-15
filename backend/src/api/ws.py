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

        elif msg_type == "lyrics.offset":
            await _handle_lyrics_offset(room_id, msg)

        elif msg_type == "guest.kick":
            await _handle_guest_kick(room_id, guest_id, msg)

        elif msg_type == "autoplay.set":
            await _handle_autoplay_set(room_id, guest_id, msg)

    # ── Admin messages ─────────────────────────────────────────────────────────
    elif role == ClientRole.ADMIN:
        # Admin has full access; delegate to queue/rooms routers
        await manager.send_to_client(client_id, {"type": "system.error", "message": "Admin WS commands not yet implemented"})


def _drop_pending_autopicks(room_id: str) -> None:
    """Remove not-yet-playing auto-picked items so autoplay re-evaluates
    against the new last song after a real user adds one."""
    from ktv_pipeline.models import QueueItem
    with get_db_session() as s:
        ap_gid = _autoplay_guest_id(s)
        s.query(QueueItem).filter(
            QueueItem.room_id == room_id,
            QueueItem.guest_id == ap_gid,
            QueueItem.status != "playing",
        ).delete(synchronize_session=False)
        s.commit()


async def _handle_queue_add(room_id: str, guest_id: str, nickname: str, msg: dict) -> None:
    """Handle queue.add from remote — add song via QueueManager."""
    song_id = msg.get("song_id") or msg.get("youtubeId")
    if not song_id:
        await manager.broadcast_system_error(room_id, "queue.add: missing song_id")
        return
    _drop_pending_autopicks(room_id)
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
            "subtitle_offset_ms": (song.extra_metadata or {}).get("subtitle_offset_ms", 0),
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

    # Autoplay: if near the end of the queue, pre-pick a recommendation.
    await _maybe_autopick(room_id)


AUTOPLAY_GUEST_NICK = "__autoplay__"


def _autoplay_guest_id(session) -> str:
    """Get/create the synthetic guest that owns auto-picked songs."""
    from ktv_pipeline.models import Guest
    g = session.query(Guest).filter_by(nickname=AUTOPLAY_GUEST_NICK).first()
    if not g:
        g = Guest(nickname=AUTOPLAY_GUEST_NICK, avatar_color="#6366f1", is_admin=False)
        session.add(g)
        session.commit()
        session.refresh(g)
    return g.id


async def _handle_autoplay_set(room_id: str, requester_id: str, msg: dict) -> None:
    """Admin-only toggle of the room's autoplay flag."""
    from ktv_pipeline.models import Guest
    with get_db_session() as s:
        r = s.query(Guest).filter_by(id=requester_id).first()
        if not r or not r.is_admin:
            await manager.broadcast_system_error(room_id, "autoplay: 需要管理員權限")
            return
    enabled = bool(msg.get("enabled"))
    manager.set_autoplay(room_id, enabled)
    state = manager.get_playback_state(room_id)
    await manager.send_to_role(room_id, ClientRole.REMOTE, {
        "type": "playback.state", "state": state,
    })
    await manager.broadcast_activity(
        room_id, f"🔀 自動播放{'開啟' if enabled else '關閉'}", "管理員",
    )
    if enabled:
        await _maybe_autopick(room_id)


async def _maybe_autopick(room_id: str) -> None:
    """If autoplay is on and the queue is nearly empty, pick a song by the
    LAST queued song's artist/genre, enqueue + process it (cached ahead)."""
    if not manager.get_autoplay(room_id):
        return
    from ktv_pipeline.models import QueueItem, Song
    from ktv_pipeline.queue_manager import QueueManager

    with get_db_session() as s:
        ap_gid = _autoplay_guest_id(s)
        active = (
            s.query(QueueItem)
            .filter(QueueItem.room_id == room_id)
            .filter(QueueItem.status.in_(QueueManager.ACTIVE_STATUSES))
            .order_by(QueueItem.position)
            .all()
        )
        # User (non-auto) items still waiting after the playing one
        waiting_user = [
            qi for qi in active
            if qi.status != "playing" and qi.guest_id != ap_gid
        ]
        already_auto = [
            qi for qi in active
            if qi.guest_id == ap_gid and qi.status != "playing"
        ]
        # Trigger only when ≤1 user song remains and no auto pick pending
        if len(waiting_user) > 1 or already_auto:
            return
        # Seed = last queued song, else the currently playing one
        seed_qi = active[-1] if active else None
        if not seed_qi:
            return
        seed_song = s.query(Song).filter_by(id=seed_qi.song_id).first()
        if not seed_song:
            return
        seed_title = seed_song.title or ""
        seed_artist = seed_song.artist or ""
        existing_ids = {qi.song_id for qi in active}

    # Clean the seed to an artist via the LLM (cached) → regex fallback
    try:
        from ktv_pipeline.llm import clean_title_llm
        from ktv_pipeline.pipeline.lyrics import clean_song_query
        llm = await clean_title_llm(seed_title, seed_artist)
        if llm and llm.get("artist"):
            artist = llm["artist"]
            genre = llm.get("genre", "")
        else:
            _t, artist = clean_song_query(seed_title, seed_artist)
            genre = ""
    except Exception:
        artist = seed_artist or seed_title
        genre = ""

    query = (artist or seed_title).strip()
    if genre:
        query = f"{artist} {genre}".strip()
    if not query:
        return

    # YouTube-search a fresh song by the seed artist/genre
    try:
        import yt_dlp
        opts = {
            "quiet": True, "no_warnings": True,
            "extract_flat": "in_playlist", "noplaylist": True,
            "default_search": "ytsearch",
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            res = ydl.extract_info(f"ytsearch8:{query}", download=False)
        entries = (res or {}).get("entries", []) or []
    except Exception as exc:
        log.warning("[autopick] yt search failed: %s", exc)
        return

    pick_id = None
    for e in entries:
        vid = e.get("id")
        dur = e.get("duration") or 0
        if not vid or vid in existing_ids:
            continue
        if dur and (dur < 60 or dur > 600):  # skip clips / hour-long mixes
            continue
        pick_id = vid
        pick_title = e.get("title") or vid
        break
    if not pick_id:
        return

    # Enqueue under the autoplay guest + kick its pipeline
    from ktv_pipeline.models import Song as SongM
    with get_db_session() as s:
        ap_gid = _autoplay_guest_id(s)
        if not s.query(SongM).filter_by(id=pick_id).first():
            s.add(SongM(id=pick_id, title=f"YouTube:{pick_id}", artist="", status="pending"))
            s.commit()
        mgr = QueueManager(s)
        try:
            qi = mgr.add_song(room_id=room_id, song_id=pick_id,
                              guest_id=ap_gid, position="end")
        except ValueError:
            return
        qid = qi.id
    log.info("[autopick] room=%s seed=%r → %s (%s)", room_id, artist, pick_id, pick_title[:40])
    import asyncio
    from api.songs import _run_pipeline_task
    asyncio.create_task(_run_pipeline_task(qid, room_id))
    await manager.broadcast_activity(room_id, f"🎲 自動推薦：{pick_title[:24]}", "自動播放")
    await _broadcast_queue_update_safe(room_id)


async def _broadcast_queue_update_safe(room_id: str) -> None:
    try:
        from ktv_pipeline.queue_manager import QueueManager
        from ktv_pipeline.models import Song, Guest
        with get_db_session() as s:
            mgr = QueueManager(s)
            q = mgr.get_queue(room_id)
            sm = {x.id: x for x in s.query(Song).all()}
            gm = {x.id: x for x in s.query(Guest).all()}
            qd = [_qi_to_dict(qi, sm.get(qi.song_id), gm.get(qi.guest_id)) for qi in q]
        await manager.broadcast_queue_updated(room_id, qd)
    except Exception:
        pass


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


async def _handle_lyrics_offset(room_id: str, msg: dict) -> None:
    """Persist a per-song subtitle delay (ms) and live-push it to the Player."""
    song_id = msg.get("songId")
    try:
        offset_ms = int(msg.get("offsetMs", 0))
    except (TypeError, ValueError):
        offset_ms = 0
    if not song_id:
        return
    offset_ms = max(-5000, min(5000, offset_ms))
    try:
        from ktv_pipeline.models import Song
        with get_db_session() as s:
            song = s.query(Song).filter_by(id=song_id).first()
            if song:
                meta = dict(song.extra_metadata or {})
                meta["subtitle_offset_ms"] = offset_ms
                song.extra_metadata = meta
                s.commit()
        await manager.send_to_role(room_id, ClientRole.PLAYER, {
            "type": "lyrics.offset", "songId": song_id, "offsetMs": offset_ms,
        })
    except Exception as exc:
        await manager.broadcast_system_error(room_id, f"lyrics.offset failed: {exc}")


async def _handle_guest_kick(room_id: str, requester_id: str, msg: dict) -> None:
    """Admin-only: disconnect a guest's WS connections and remove them."""
    target = msg.get("guestId")
    if not target:
        return
    from ktv_pipeline.models import Guest
    with get_db_session() as s:
        requester = s.query(Guest).filter_by(id=requester_id).first()
        if not requester or not requester.is_admin:
            await manager.broadcast_system_error(room_id, "guest.kick: 需要管理員權限")
            return
        tg = s.query(Guest).filter_by(id=target).first()
        tname = tg.nickname if tg else target
    # Tell the target it was kicked, then force-close all its sockets
    for c in list(manager.get_room_clients(room_id)):
        if c.guest_id == target:
            try:
                await manager.send_to_client(c.client_id, {
                    "type": "guest.kicked", "guestId": target,
                })
            except Exception:
                pass
            await manager.disconnect(c.client_id)
            try:
                await c.websocket.close(code=4003, reason="Kicked by admin")
            except Exception:
                pass
    remaining = await _get_room_guests_info(room_id)
    await manager.broadcast_guests_updated(room_id, remaining)
    await manager.broadcast_activity(room_id, f"👢 踢出 {tname}", "管理員")


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