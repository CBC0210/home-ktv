#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
UV_BIN=""
NODE_BIN=""
FRONTEND_PORT=3000
RENDER_ONLY=""

usage() {
    cat <<'EOF'
Usage: scripts/install-user-services.sh [options]
  --repo-dir DIR       Repository directory (default: detected automatically)
  --uv PATH            uv executable
  --node PATH          node executable
  --frontend-port PORT Frontend port (default: 3000)
  --render-only DIR    Render units into DIR without touching systemd
  -h, --help           Show this help
EOF
}

while (($#)); do
    case "$1" in
        --repo-dir|--uv|--node|--frontend-port|--render-only)
            (($# >= 2)) || { echo "Missing value for $1" >&2; exit 2; }
            case "$1" in
                --repo-dir) REPO_DIR="$2" ;;
                --uv) UV_BIN="$2" ;;
                --node) NODE_BIN="$2" ;;
                --frontend-port) FRONTEND_PORT="$2" ;;
                --render-only) RENDER_ONLY="$2" ;;
            esac
            shift 2
            ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

REPO_DIR="$(cd -- "$REPO_DIR" && pwd -P)"
[[ "$FRONTEND_PORT" =~ ^[0-9]+$ ]] && ((FRONTEND_PORT >= 1 && FRONTEND_PORT <= 65535)) || {
    echo "Invalid frontend port: $FRONTEND_PORT" >&2
    exit 2
}

if [[ -z "$UV_BIN" ]]; then
    UV_BIN="$(command -v uv || true)"
    [[ -n "$UV_BIN" ]] || UV_BIN="$HOME/.local/bin/uv"
fi
if [[ -z "$NODE_BIN" ]]; then
    NODE_BIN="$(command -v node || true)"
    if [[ -z "$NODE_BIN" && -d "$HOME/.nvm/versions/node" ]]; then
        NODE_BIN="$(find "$HOME/.nvm/versions/node" -mindepth 3 -maxdepth 3 -type f -path '*/bin/node' -perm -u+x -print | sort -V | tail -n 1)"
    fi
fi

UV_BIN="$(realpath -e -- "$UV_BIN" 2>/dev/null || true)"
NODE_BIN="$(realpath -e -- "$NODE_BIN" 2>/dev/null || true)"
[[ -x "$UV_BIN" ]] || { echo "uv executable not found; pass --uv PATH" >&2; exit 1; }
[[ -x "$NODE_BIN" ]] || { echo "node executable not found; pass --node PATH" >&2; exit 1; }

TEMPLATE_DIR="$REPO_DIR/deploy/systemd-user"
[[ -f "$TEMPLATE_DIR/ktv-backend.service.in" && -f "$TEMPLATE_DIR/ktv-frontend.service.in" ]] || {
    echo "systemd user-service templates not found under $TEMPLATE_DIR" >&2
    exit 1
}

render() {
    local source=$1 destination=$2 content
    content=$(<"$source")
    content=${content//@REPO_DIR@/$REPO_DIR}
    content=${content//@UV@/$UV_BIN}
    content=${content//@NODE@/$NODE_BIN}
    content=${content//@FRONTEND_PORT@/$FRONTEND_PORT}
    printf '%s\n' "$content" > "$destination"
}

if [[ -n "$RENDER_ONLY" ]]; then
    TARGET_DIR="$RENDER_ONLY"
else
    TARGET_DIR="$HOME/.config/systemd/user"
fi
mkdir -p -- "$TARGET_DIR"

STAGING_DIR="$(mktemp -d)"
trap 'rm -rf -- "$STAGING_DIR"' EXIT
for unit in ktv-backend.service ktv-frontend.service; do
    render "$TEMPLATE_DIR/$unit.in" "$STAGING_DIR/$unit"
    target="$TARGET_DIR/$unit"
    if [[ -f "$target" ]] && ! cmp -s -- "$STAGING_DIR/$unit" "$target"; then
        cp -a -- "$target" "$target.bak-$(date +%Y%m%d-%H%M%S-%N)"
    fi
    cp -- "$STAGING_DIR/$unit" "$target"
done

if [[ -n "$RENDER_ONLY" ]]; then
    printf 'Rendered user units in %s\n' "$TARGET_DIR"
    exit 0
fi

systemctl --user daemon-reload
systemctl --user enable ktv-backend.service ktv-frontend.service
printf 'Units installed and enabled. Start them with:\n'
printf '  systemctl --user start ktv-frontend.service\n'
printf 'For boot-time startup without an interactive login, run once:\n'
printf '  sudo loginctl enable-linger %q\n' "${USER:-$(id -un)}"
