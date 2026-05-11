"""API router aggregation。"""
from fastapi import APIRouter
from . import rooms, songs, guests, queue, auth

api_router = APIRouter(prefix="/api")
api_router.include_router(auth.router)
api_router.include_router(rooms.router)
api_router.include_router(songs.router)
api_router.include_router(guests.router)
api_router.include_router(queue.router)
