#!/bin/bash
# Pipeline runner — CUDA lib paths are resolved dynamically by
# ktv_pipeline.config at import time; nothing machine-specific here.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"
cd "$BACKEND_DIR"
exec uv run python -m ktv_pipeline.pipeline_orchestrator "$@"
