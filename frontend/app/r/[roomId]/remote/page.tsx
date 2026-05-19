import type { Metadata } from "next";
import RemoteView from "@/components/remote/RemoteView";

interface Props {
  params: Promise<{ roomId: string }>;
}

// Override the global manifest with a room-scoped one so each room
// installs as its own distinguishable home-screen app ("響窩 · <room>").
export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { roomId } = await params;
  const label = roomId.charAt(0).toUpperCase() + roomId.slice(1);
  return {
    title: `響窩 · ${label}`,
    manifest: `/r/${roomId}/manifest`,
    appleWebApp: { capable: true, statusBarStyle: "black-translucent", title: `響窩 ${label}` },
  };
}

export default async function RemotePage({ params }: Props) {
  const { roomId } = await params;
  return <RemoteView roomId={roomId} />;
}

export function generateStaticParams() {
  return [{ roomId: "home" }];
}
