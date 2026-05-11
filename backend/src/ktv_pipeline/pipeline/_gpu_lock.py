"""Shared GPU lock — serialises ALL GPU tasks (Demucs + WhisperX) on the same card.

A single asyncio.Lock instance imported by both wrappers ensures only one GPU
job runs at a time, preventing VRAM OOM on the GTX 1650 (4 GB).
"""
import asyncio

GPU_LOCK: asyncio.Lock = asyncio.Lock()
