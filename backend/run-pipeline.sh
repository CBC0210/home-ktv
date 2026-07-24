#!/bin/bash
# Pipeline CLI runner. CUDA lib paths are resolved by config.py at import
# time (machine-independent), so no LD_LIBRARY_PATH juggling is needed here.
cd "$(dirname "$0")"
exec uv run python -m ktv_pipeline.pipeline_orchestrator "$@"
