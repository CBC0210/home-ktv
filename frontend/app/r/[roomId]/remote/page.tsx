"use client";

import { useParams } from "next/navigation";
import RemoteView from "@/components/remote/RemoteView";

export default function RemotePage() {
  const params = useParams<{ roomId: string }>();
  return <RemoteView roomId={params.roomId} />;
}

export function generateStaticParams() {
  return [{ roomId: "home" }];
}
