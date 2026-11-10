"""Authorization boundaries without touching production or starting GPU jobs."""
import uuid
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from main import app
from ktv_pipeline.auth import create_access_token, decode_access_token, hash_password
from ktv_pipeline.config import settings
from ktv_pipeline.database import get_db_session
from ktv_pipeline.models import Room, Song, Guest
from ktv_pipeline import security

@pytest.fixture()
def event():
    tag = uuid.uuid4().hex[:8]
    a,b,sid = 'a-'+tag,'b-'+tag,'song-'+tag
    with get_db_session() as s:
        s.add_all([Room(id=a,name='A',password_hash=hash_password('room-password'),admin_password_hash=hash_password('room-admin-password')),
                   Room(id=b,name='B',password_hash=hash_password('room-password')),
                   Song(id=sid,title='Event',status='ready')])
    security._windows.clear()
    client = TestClient(app)
    joined = client.post('/api/guests/join',json={'room_id':a,'nickname':'Event '+tag,'password':'room-password'}).json()
    client.cookies.clear()
    guest = {'Authorization':'Bearer '+joined['access_token']}
    return client,a,b,sid,guest,joined


def test_shared_nickname_still_shared(event):
    c,a,b,sid,h,j=event
    second=c.post('/api/guests/join',json={'room_id':b,'nickname':j['guest']['nickname'],'password':'room-password'})
    assert second.json()['guest']['id']==j['guest']['id']


def test_room_membership_on_song_queue(event):
    c,a,b,sid,h,j=event
    assert c.post(f'/api/queue?room_id={b}',json={'song_id':sid},headers=h).status_code==403
    assert c.post(f'/api/queue?room_id={a}',json={'song_id':sid},headers=h).status_code==200
    assert c.post('/api/songs',json={'room_id':b,'youtube_url':'dQw4w9WgXcQ'},headers=h).status_code==403


def test_room_admin_cannot_manage_system_or_other_rooms(event):
    c,a,b,sid,h,j=event
    r=c.post(f'/api/rooms/{a}/admin/verify',json={'password':'room-admin-password'},headers=h)
    assert r.status_code==200
    elevated={'Authorization':'Bearer '+r.json()['access_token']}
    assert decode_access_token(r.json()['access_token'])['scope']=='room_admin'
    for path in ['/api/admin/rooms','/api/admin/system-status']:
        assert c.get(path,headers=elevated).status_code==403
    assert c.delete(f'/api/admin/songs/{sid}',headers=elevated).status_code==403
    assert c.delete(f'/api/songs/{sid}/report',headers=elevated).status_code==403
    assert c.patch(f'/api/rooms/{b}/password?new_password=bad',headers=elevated).status_code==403
    assert c.patch(f'/api/queue/room/{b}/reorder',json=[],headers=elevated).status_code==403
    assert c.patch(f'/api/queue/room/{a}/reorder',json=[],headers=elevated).status_code==200
    with get_db_session() as s:
        assert not s.query(Guest).filter_by(id=j['guest']['id']).one().is_admin


def test_system_admin_and_owner_room_access(event):
    c,a,b,sid,h,j=event
    token=c.post('/api/auth/admin/login',json={'password':settings.admin_password}).json()['access_token']
    assert c.get('/api/admin/rooms',headers={'Authorization':'Bearer '+token}).status_code==200
    assert c.delete(f'/api/songs/{sid}/report',headers={'Authorization':'Bearer '+token}).status_code==200
    assert c.post(f'/api/rooms/{a}/admin/verify',json={'password':settings.admin_password},headers=h).status_code==200


def test_predictable_default_does_not_authorize(event):
    c,a,b,sid,h,j=event
    with get_db_session() as s: s.query(Room).filter_by(id=a).one().admin_password_hash=hash_password(a+'admin')
    assert c.post(f'/api/rooms/{a}/admin/verify',json={'password':a+'admin'},headers=h).status_code==403


def test_anonymous_mutations_blocked_and_source_allowlisted(event):
    c,a,b,sid,h,j=event
    assert c.post(f'/api/songs/{sid}/lyrics/source',json={'source':'none'}).status_code==401
    assert c.post(f'/api/songs/{sid}/report',json={'issue':'wrong_lyrics'}).status_code==401
    assert c.post(f'/api/songs/{sid}/lyrics/source',json={'source':'../../bad'},headers=h).status_code==422
    assert c.post(f'/api/songs/{sid}/lyrics/source',json={'source':'none'},headers=h).status_code==200
    assert c.put(f'/songs/{sid}/lyrics',json={'ass':'data'},headers=h).status_code==403


def test_player_pairing_scopes_and_reconnect(event):
    c,a,b,sid,h,j=event
    assert c.post(f'/api/rooms/{a}/player-session',json={'password':'wrong'}).status_code==403
    token=c.post(f'/api/rooms/{a}/player-session',json={'password':'room-password'}).json()['access_token']
    assert c.post(f'/api/queue?room_id={a}',json={'song_id':sid},headers={'Authorization':'Bearer '+token}).status_code==403
    for url in [f'/ws?room_id={a}&role=player',f'/ws?room_id={a}&role=player&token={j["access_token"]}',f'/ws?room_id={b}&role=player&token={token}',f'/ws?room_id={a}&role=remote&token={token}']:
        with pytest.raises(WebSocketDisconnect) as e:
            with c.websocket_connect(url) as ws: ws.receive_json()
        assert e.value.code==4001
    for _ in range(2):
        with c.websocket_connect(f'/ws?room_id={a}&role=player&token={token}') as ws:
            assert ws.receive_json()['type']=='playback.state'
            ws.send_json({'type':'ping'})
            assert ws.receive_json()['type']=='pong'


def test_origin_and_payload_limits(event):
    c,a,b,sid,h,j=event
    assert c.post(f'/api/songs/{sid}/report',json={'issue':'other'},headers={**h,'Origin':'https://evil.example'}).status_code==403
    assert c.post('/api/auth/admin/login',content=b'x'*(1024*1024+1)).status_code==413
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect(f'/ws?room_id={a}&role=remote&token={j["access_token"]}',headers={'Origin':'https://evil.example'}) as ws: ws.receive_json()


def test_failed_login_limited_without_throttling_successful_party_guests(event):
    c,a,b,sid,h,j=event
    for _ in range(30):
        assert c.post('/api/auth/admin/login',json={'password':'wrong'}).status_code==401
    assert c.post('/api/auth/admin/login',json={'password':'wrong'}).status_code==429
    security._windows.clear()
    for _ in range(35):
        assert c.post(f'/api/rooms/{b}/player-session',json={'password':'room-password'}).status_code==200
