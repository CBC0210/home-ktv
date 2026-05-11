"""API router aggregation。"""
from fastapi import APIRouter
from . import rooms, songs, guests, queue, auth, admin

api_router = APIRouter(prefix="/api")
api_router.include_router(auth.router)
api_router.include_router(admin.router)
api_router.include_router(rooms.router)
api_router.include_router(songs.router)
api_router.include_router(guests.router)
api_router.include_router(queue.router)

# WebSocket endpoint registered at /ws (root-level, not /api/ws)
ws_router = __import__("api.ws", fromlist=["router"]).router

# Streaming endpoints under /api/songs/{song_id}/stream.m3u8 etc.
streaming_router = __import__("api.streaming", fromlist=["router"]).router