"""Discovery filters both online and cached candidates without queue mutations."""
import uuid

from fastapi.testclient import TestClient
from main import app
from ktv_pipeline.auth import create_access_token
from ktv_pipeline.database import get_db_session
from ktv_pipeline.models import Song


def test_cached_search_hides_compilations_but_library_keeps_them():
    tag = uuid.uuid4().hex[:8]
    titles = [f'{tag} 單曲完整版 Live', f'{tag} 合集', f'{tag} 20首金曲', f'{tag} 長片']
    with get_db_session() as s:
        for i, title in enumerate(titles):
            s.add(Song(id=f'{tag}-{i}', title=title, status='ready', duration_sec=180 if i < 3 else 3600))
    c = TestClient(app)
    result = c.get('/api/songs/search', params={'q':tag}).json()
    assert [s['title'] for s in result] == [titles[0]]
    library = c.get('/api/songs/library', params={'q':tag}).json()
    assert library['total'] == 4


def test_online_search_overfetches_then_filters(monkeypatch):
    calls = []
    class FakeYdl:
        def __init__(self, opts): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def extract_info(self, query, download=False):
            calls.append(query)
            return {'entries':[
                {'id':'bad00000001','title':'熱門歌曲合集','duration':200},
                {'id':'bad00000002','title':'medley','duration':200},
                *[{'id':f'good{i:07d}','title':f'單曲 {i} Official MV','duration':200} for i in range(15)],
            ]}
    monkeypatch.setattr('yt_dlp.YoutubeDL', FakeYdl)
    token = create_access_token('search-'+uuid.uuid4().hex, 'test')
    response = TestClient(app).get('/api/songs/youtube-search', params={'q':'song','limit':10}, headers={'Authorization':'Bearer '+token})
    assert response.status_code == 200
    assert len(response.json()) == 10
    assert all(r['id'].startswith('good') for r in response.json())
    assert calls == ['ytsearch30:song']
