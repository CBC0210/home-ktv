"use client";

import { useParams } from "next/navigation";
import PlayerView from "@/components/player/PlayerView";

export default function PlayerPage() {
  const params = useParams<{ roomId: string }>();
  return <PlayerView roomId={params.roomId} />;
}

export function generateStaticParams() {
  return [{ roomId: "home" }];
}
