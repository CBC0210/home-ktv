"""Regression tests for the playback-advance flow.

Covers the root causes of「Player 播完不回待機畫面」and「Remote 失控」:
1. Pipeline status writes must never stomp a 'playing' queue item back to
   'ready' (stomped rows made get_currently_playing return None, so
   song.ended was never broadcast and the room wedged on the last song).
2. _handle_song_advance must broadcast song.ended even when no 'playing'
   row exists, so the TV always returns to the standby/QR screen.
3. A stale player.ended for a song that is no longer playing is ignored.
4. WS auth rejection must be visible to the browser as close code 4001
   (accept-then-close), not an opaque HTTP 403 handshake failure.
"""
import pytest
from unittest.mock import AsyncMock, patch

from ktv_pipeline.database import get_db_session, init_db
from ktv_pipeline.models import Room, Guest, Song, QueueItem, PlayHistory
from ktv_pipeline.pipeline_orchestrator import (
    PipelineConfig,
    PipelineOrchestrator,
    SongState,
)

ROOM = "test-advance-room"
SONG = "advsong1"


@pytest.fixture(autouse=True)
def _db():
    init_db()


def _reset_room():
    with get_db_session() as s:
        s.query(QueueItem).filter_by(room_id=ROOM).delete(synchronize_session=False)
        s.query(PlayHistory).filter_by(room_id=ROOM).delete(synchronize_session=False)
        s.query(Room).filter_by(id=ROOM).delete(synchronize_session=False)
        s.query(Song).filter_by(id=SONG).delete(synchronize_session=False)
        g = s.query(Guest).filter_by(nickname="AdvTester").first()
        if not g:
            g = Guest(nickname="AdvTester", avatar_color="#123456")
            s.add(g)
        s.add(Room(id=ROOM, name="Advance Test"))
        s.add(Song(id=SONG, title="Adv Song", artist="X", status="ready", duration_sec=200))
        s.commit()
        return g.id


@pytest.fixture
def playing_item():
    guest_id = _reset_room()
    with get_db_session() as s:
        item = QueueItem(room_id=ROOM, song_id=SONG, guest_id=guest_id,
                         position=1, status="playing")
        s.add(item)
        s.commit()
        s.refresh(item)
        return {"item_id": item.id, "guest_id": guest_id}


@pytest.fixture
def pending_item():
    guest_id = _reset_room()
    with get_db_session() as s:
        item = QueueItem(room_id=ROOM, song_id=SONG, guest_id=guest_id,
                         position=1, status="pending")
        s.add(item)
        s.commit()
        s.refresh(item)
        return {"item_id": item.id, "guest_id": guest_id}


def _item_status(item_id: int) -> str:
    with get_db_session() as s:
        return s.query(QueueItem).filter_by(id=item_id).first().status


class TestPipelineNeverStompsPlaying:
    async def test_run_from_queue_keeps_playing(self, playing_item):
        orch = PipelineOrchestrator(config=PipelineConfig())

        async def fake_run(song_id):
            return {"ok": True}

        orch.run = fake_run
        result = await orch.run_from_queue(playing_item["item_id"])
        assert result["ok"] is True
        assert _item_status(playing_item["item_id"]) == "playing"

    async def test_run_from_queue_still_marks_pending_ready(self, pending_item):
        orch = PipelineOrchestrator(config=PipelineConfig())

        async def fake_run(song_id):
            return {"ok": True}

        orch.run = fake_run
        await orch.run_from_queue(pending_item["item_id"])
        assert _item_status(pending_item["item_id"]) == "ready"

    async def test_update_state_keeps_playing(self, playing_item):
        orch = PipelineOrchestrator(config=PipelineConfig())
        orch._queue_item_id = playing_item["item_id"]
        orch._room_id = None  # skip the broadcast branch
        await orch._update_state(SONG, SongState.DOWNLOADING)
        assert _item_status(playing_item["item_id"]) == "playing"

    async def test_update_state_still_writes_stage_when_pending(self, pending_item):
        orch = PipelineOrchestrator(config=PipelineConfig())
        orch._queue_item_id = pending_item["item_id"]
        orch._room_id = None
        await orch._update_state(SONG, SongState.DOWNLOADING)
        assert _item_status(pending_item["item_id"]) == "downloading"


class TestSongAdvanceBroadcast:
    async def test_song_ended_broadcast_even_without_playing_row(self):
        _reset_room()  # room exists, queue empty
        from api import ws as ws_mod
        with patch.object(ws_mod.manager, "broadcast_song_ended", new=AsyncMock()) as ended, \
             patch.object(ws_mod, "_start_next_song", new=AsyncMock()) as start_next:
            await ws_mod._handle_song_advance(ROOM)
            ended.assert_awaited_once_with(ROOM, -1)
            start_next.assert_awaited_once()

    async def test_matching_song_marks_done_and_broadcasts(self, playing_item):
        from api import ws as ws_mod
        with patch.object(ws_mod.manager, "broadcast_song_ended", new=AsyncMock()) as ended, \
             patch.object(ws_mod, "_start_next_song", new=AsyncMock()):
            await ws_mod._handle_song_advance(ROOM, expected_song_id=SONG)
            ended.assert_awaited_once_with(ROOM, playing_item["item_id"])
        assert _item_status(playing_item["item_id"]) == "done"

    async def test_stale_event_for_other_song_is_ignored(self, playing_item):
        from api import ws as ws_mod
        with patch.object(ws_mod.manager, "broadcast_song_ended", new=AsyncMock()) as ended, \
             patch.object(ws_mod, "_start_next_song", new=AsyncMock()) as start_next:
            await ws_mod._handle_song_advance(ROOM, expected_song_id="some-other-song")
            ended.assert_not_awaited()
            start_next.assert_not_awaited()
        assert _item_status(playing_item["item_id"]) == "playing"

    async def test_skip_below_80pct_not_counted_as_play(self, playing_item):
        from api import ws as ws_mod
        with patch.object(ws_mod.manager, "broadcast_song_ended", new=AsyncMock()), \
             patch.object(ws_mod, "_start_next_song", new=AsyncMock()):
            await ws_mod._handle_song_advance(ROOM, final_position_sec=30)
        assert _item_status(playing_item["item_id"]) == "done"
        with get_db_session() as s:
            assert s.query(PlayHistory).filter_by(room_id=ROOM).count() == 0
            song = s.query(Song).filter_by(id=SONG).first()
            assert (song.play_count or 0) == 0


class TestStartupPromotion:
    async def test_pending_item_with_ready_song_promoted_not_repipelined(self, pending_item):
        """Startup must promote pending items whose Song is already processed
        instead of re-running the pipeline (the re-run's final status write
        raced the playback flow and stomped 'playing' — the wedge bug)."""
        from main import _kick_all_pending_pipelines
        with patch("api.songs._run_pipeline_task", new=AsyncMock()) as run_task:
            await _kick_all_pending_pipelines()
            kicked_ids = [c.args[0] for c in run_task.call_args_list]
            assert pending_item["item_id"] not in kicked_ids
        assert _item_status(pending_item["item_id"]) == "ready"


class TestRequeuePlayingSong:
    def test_readd_currently_playing_song_allowed(self, playing_item):
        """spec §6.2「🔁 加回隊列」— re-queueing the song being sung right now."""
        from ktv_pipeline.queue_manager import QueueManager
        with get_db_session() as s:
            mgr = QueueManager(s)
            item = mgr.add_song(room_id=ROOM, song_id=SONG,
                                guest_id=playing_item["guest_id"])
            assert item.id != playing_item["item_id"]
            assert item.status == "ready"

    def test_duplicate_pending_still_rejected(self, pending_item):
        from ktv_pipeline.queue_manager import QueueManager
        with get_db_session() as s:
            mgr = QueueManager(s)
            with pytest.raises(ValueError, match="already in queue"):
                mgr.add_song(room_id=ROOM, song_id=SONG,
                             guest_id=pending_item["guest_id"])


class TestPlayerReadySnapshot:
    def test_reconnecting_player_receives_song_started(self, playing_item):
        """A TV that missed the song.started broadcast (disconnected at the
        time) must get a targeted snapshot on player.ready, or it sits on
        the standby screen against a DB that says a song is playing."""
        import json
        from fastapi.testclient import TestClient
        from main import app

        client = TestClient(app)
        with client.websocket_connect(f"/ws?room_id={ROOM}&role=player") as ws:
            first = ws.receive_json()
            assert first["type"] == "playback.state"
            ws.send_text(json.dumps({"type": "player.ready"}))
            evt = ws.receive_json()
            assert evt["type"] == "song.started"
            assert evt["song"]["id"] == SONG
            assert evt["queueItem"]["id"] == playing_item["item_id"]


class TestWrongLyricsReport:
    def test_wrong_lyrics_report_disables_subtitles(self, playing_item):
        """「字幕是別首歌」report must kill the wrong-song subtitles at once:
        has_timing→False, lyrics_source→'none', lyrics.ass removed (cached
        lyrics_<src>.ass alternates stay for the source picker)."""
        from fastapi.testclient import TestClient
        from ktv_pipeline.config import settings
        from main import app

        media_dir = settings.data_dir / "media" / SONG
        media_dir.mkdir(parents=True, exist_ok=True)
        (media_dir / "lyrics.ass").write_text("[Script Info]\n", encoding="utf-8")
        (media_dir / "lyrics_netease.ass").write_text("[Script Info]\n", encoding="utf-8")
        with get_db_session() as s:
            song = s.query(Song).filter_by(id=SONG).first()
            song.has_timing = True
            song.lyrics_source = "qq"
            s.commit()

        client = TestClient(app)
        resp = client.post(f"/api/songs/{SONG}/report", json={"issue": "wrong_lyrics"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["has_timing"] is False
        assert body["use_original_audio"] is False  # not an audio-class issue

        assert not (media_dir / "lyrics.ass").exists()
        assert (media_dir / "lyrics_netease.ass").exists()  # alternates kept
        with get_db_session() as s:
            song = s.query(Song).filter_by(id=SONG).first()
            assert song.has_timing is False
            assert song.lyrics_source == "none"
            reports = ((song.extra_metadata or {}).get("playback") or {}).get("reports", [])
            assert reports and reports[-1]["issue"] == "wrong_lyrics"

    def test_audio_report_keeps_subtitles(self, playing_item):
        from fastapi.testclient import TestClient
        from main import app

        with get_db_session() as s:
            song = s.query(Song).filter_by(id=SONG).first()
            song.has_timing = True
            s.commit()

        client = TestClient(app)
        resp = client.post(f"/api/songs/{SONG}/report", json={"issue": "clipping"})
        assert resp.status_code == 200
        assert resp.json()["use_original_audio"] is True
        with get_db_session() as s:
            assert s.query(Song).filter_by(id=SONG).first().has_timing is True


class TestWsAuthCloseCode:
    def test_invalid_token_closes_with_4001(self):
        """The browser must SEE 4001 — requires accept-then-close, because a
        pre-accept close surfaces as HTTP 403 and the client only gets 1006."""
        from fastapi.testclient import TestClient
        from starlette.websockets import WebSocketDisconnect
        from main import app

        client = TestClient(app)
        with client.websocket_connect("/ws?token=not.a.jwt&role=remote") as ws:
            with pytest.raises(WebSocketDisconnect) as excinfo:
                ws.receive_text()
        assert excinfo.value.code == 4001
