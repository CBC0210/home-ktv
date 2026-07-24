import PlayerView from "@/components/player/PlayerView";

interface Props {
  params: Promise<{ roomId: string }>;
}

export default async function PlayerPage({ params }: Props) {
  const { roomId } = await params;
  return <PlayerView roomId={roomId} />;
}

export function generateStaticParams() {
  return [{ roomId: "home" }];
}
