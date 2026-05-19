// Per-room PWA manifest. A static manifest makes every "Add to Home
// Screen" install the same deduped app — you can't tell rooms apart and
// a 2nd room won't install separately. A room-scoped id/name/start_url/
// scope makes each room its own installable app: "響窩 · <room>".

export const dynamicParams = true;

export function generateStaticParams() {
  return [{ roomId: "home" }];
}

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ roomId: string }> },
) {
  const { roomId } = await params;
  const label = roomId.charAt(0).toUpperCase() + roomId.slice(1);
  const body = {
    id: `/r/${roomId}/remote`,
    name: `響窩 · ${label}`,
    short_name: `響窩 ${label}`,
    description: `響窩 Echonest — ${label} 房間遙控（掃碼點歌、控制播放）`,
    start_url: `/r/${roomId}/remote`,
    scope: `/r/${roomId}/`,
    display: "standalone",
    orientation: "portrait",
    background_color: "#0a0a0a",
    theme_color: "#7c3aed",
    icons: [
      { src: "/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
  return new Response(JSON.stringify(body), {
    headers: {
      "Content-Type": "application/manifest+json",
      "Cache-Control": "public, max-age=3600",
    },
  });
}
