import RemoteView from "@/components/remote/RemoteView";

interface Props {
  params: Promise<{ roomId: string }>;
}

export default async function RemotePage({ params }: Props) {
  const { roomId } = await params;
  return <RemoteView roomId={roomId} />;
}

export function generateStaticParams() {
  return [{ roomId: "home" }];
}
