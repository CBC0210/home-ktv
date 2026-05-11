import RemoteView from "@/components/remote/RemoteView";

export default async function RemotePage({
  params,
}: {
  params: Promise<{ roomId: string }>;
}) {
  const { roomId } = await params;
  return <RemoteView roomId={roomId} />;
}
