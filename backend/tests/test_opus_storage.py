"""Exercise real encoders and playback after WAV retirement."""
import subprocess
from pathlib import Path
from unittest.mock import patch
import uuid
import pytest
from fastapi.testclient import TestClient
from main import app
from ktv_pipeline.config import settings
from ktv_pipeline.database import get_db_session
from ktv_pipeline.models import Song
from ktv_pipeline.pipeline.demucs import DemucsWrapper, _outputs_exist
from ktv_pipeline.pipeline_orchestrator import PipelineOrchestrator


def wav(path, duration=1):
    path.parent.mkdir(parents=True,exist_ok=True)
    subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-f','lavfi','-i','sine=frequency=440:sample_rate=44100','-t',str(duration),'-ac','2','-c:a','pcm_f32le',str(path)],check=True)


@pytest.mark.asyncio
async def test_opus_only_plays_supports_ranges_and_reuses_separation(tmp_path):
    sid='opus-'+uuid.uuid4().hex[:8]
    root=settings.data_dir/'cache'/'demucs'/sid
    orig=root/'vocals.wav';wav(orig)
    wav(root/'no_vocals.wav')
    orch=PipelineOrchestrator()
    for p in (orig,root/'no_vocals.wav'):
        assert await orch._convert_opus_async(p)==p.with_suffix('.opus')
    assert orch._cleanup_verified_wavs(orig,root/'no_vocals.wav')
    assert not orig.exists()
    assert _outputs_exist(root)
    wrapper=DemucsWrapper(cache_dir=root.parent,device='cpu')
    result=await wrapper.separate(sid,tmp_path/'nonexistent-input.mp4')
    assert result.vocal_path.suffix=='.opus'
    with get_db_session() as s: s.add(Song(id=sid,title='Opus',status='ready'))
    c=TestClient(app)
    for name in ['vocals.wav','no_vocals.wav']:
        response=c.get(f'/songs/{sid}/audio/{name}')
        assert response.status_code==200 and 'opus' in response.headers['content-type']
        assert response.content==orig.with_name(name).with_suffix('.opus').read_bytes()
        response=c.get(f'/songs/{sid}/audio/{name}',headers={'Range':'bytes=0-99'})
        assert response.status_code==206 and len(response.content)==100


@pytest.mark.asyncio
async def test_failed_encoder_preserves_wav_and_invalid_only_opus(tmp_path):
    p=tmp_path/'vocals.wav';wav(p)
    orch=PipelineOrchestrator()
    with patch('ktv_pipeline.pipeline_orchestrator.subprocess.run',side_effect=OSError('no encoder')):
        assert await orch._convert_opus_async(p) is None
    assert p.exists() and not p.with_suffix('.opus').exists()
    only=tmp_path/'no_vocals.opus';only.write_bytes(b'broken')
    assert await orch._convert_opus_async(only) is None
    assert only.read_bytes()==b'broken'


@pytest.mark.asyncio
async def test_short_valid_opus_cannot_justify_deleting_long_wav(tmp_path):
    orch=PipelineOrchestrator()
    p=tmp_path/'vocals.wav';wav(p,1)
    opus=await orch._convert_opus_async(p)
    wav(p,2)
    assert not orch._is_valid_opus(opus,p)
    assert p.exists()
