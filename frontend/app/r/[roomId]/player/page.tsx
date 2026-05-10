export default function PlayerPage({
  params,
}: {
  params: Promise<{ roomId: string }>;
}) {
  return (
    <main className="min-h-screen bg-black flex items-center justify-center">
      <p className="text-white text-2xl">Player — 開發中</p>
    </main>
  );
}
