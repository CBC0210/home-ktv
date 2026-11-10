import uuid
from types import SimpleNamespace

import pytest

from ktv_pipeline.config import settings
from ktv_pipeline.database import get_db_session
from ktv_pipeline.models import Room, Guest, Song, QueueItem
from ktv_pipeline.queue_manager import QueueManager
from ktv_pipeline.playback_assets import playback_assets_ready


def assets(sid, complete=True):
    video = settings.data_dir / 'media' / sid / 'video.mp4'
    video.parent.mkdir(parents=True, exist_ok=True)
    video.write_bytes(b'video fixture')
    if complete:
        audio = settings.data_dir / 'cache' / 'demucs' / sid
        audio.mkdir(parents=True, exist_ok=True)
        for stem in ('vocals', 'no_vocals'):
            (audio / (stem + '.opus')).write_bytes(b'verified fixture')


def test_video_only_is_not_playable_and_both_tracks_required():
    sid = uuid.uuid4().hex
    song = SimpleNamespace(id=sid, extra_metadata={})
    assets(sid, False)
    assert not playback_assets_ready(song)
    assets(sid)
    assert playback_assets_ready(song)
    (settings.data_dir / 'cache/demucs' / sid / 'no_vocals.opus').write_bytes(b'')
    assert not playback_assets_ready(song)


def test_pick_skips_processing_and_false_ready_without_interrupting_current():
    tag = uuid.uuid4().hex
    with get_db_session() as s:
        room = Room(id=tag, name='Ready gate')
        guest = Guest(nickname=tag)
        s.add_all([room, guest]);s.flush()
        rows = []
        for index, (status, complete) in enumerate([('separating',False),('ready',False),('ready',True)]):
            sid = f'{tag}-{index}'
            song = Song(id=sid, title=sid, status=status)
            s.add(song);s.flush()
            row = QueueItem(room_id=tag, song_id=sid, guest_id=guest.id, position=index+1, status=status)
            s.add(row);rows.append(row);assets(sid, complete)
        s.commit()
        mgr = QueueManager(s)
        assert mgr.pick_next_ready(tag).id == rows[2].id
        assert mgr.mark_playing(rows[2].id).id == rows[2].id
        assert mgr.mark_playing(rows[1].id) is None
        assert mgr.mark_playing(rows[0].id) is None
        assert mgr.get_currently_playing(tag).id == rows[2].id
