import PlayerView from "@/components/player/PlayerView";

export default async function PlayerPage({
  params,
}: {
  params: Promise<{ roomId: string }>;
}) {
  const { roomId } = await params;
  return <PlayerView roomId={roomId} />;
}
