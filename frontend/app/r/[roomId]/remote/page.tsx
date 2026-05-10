export default function RemotePage({
  params,
}: {
  params: Promise<{ roomId: string }>;
}) {
  return (
    <main className="min-h-screen bg-gray-900 flex items-center justify-center">
      <p className="text-white text-2xl">Remote — 開發中</p>
    </main>
  );
}
