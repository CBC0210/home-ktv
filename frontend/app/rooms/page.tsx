import Link from "next/link";
import { getRooms } from "@/lib/api";
import RoomCard from "@/components/shared/RoomCard";
import type { Room } from "@/lib/types";

export const revalidate = 30;

async function fetchRooms(): Promise<Room[]> {
  try {
    return await getRooms();
  } catch {
    return [];
  }
}

export default async function RoomsPage() {
  const rooms = await fetchRooms();

  return (
    <main className="min-h-screen bg-gray-950 p-6">
      <div className="max-w-lg mx-auto">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-white">🎤 Home KTV</h1>
          <p className="text-gray-400 mt-2">選擇房間開始唱歌</p>
        </div>

        {rooms.length === 0 ? (
          <div className="text-center py-12">
            <p className="text-gray-400">找不到任何房間</p>
            <p className="text-gray-600 text-sm mt-2">
              請確認後端服務已啟動，或前往{" "}
              <Link href="/admin" className="text-purple-400 hover:underline">
                管理頁面
              </Link>{" "}
              建立房間
            </p>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            {rooms.map((room) => (
              <RoomCard key={room.id} room={room} />
            ))}
          </div>
        )}

        <div className="mt-8 text-center">
          <Link
            href="/admin"
            className="text-gray-600 hover:text-gray-400 text-sm transition-colors"
          >
            管理員入口
          </Link>
        </div>
      </div>
    </main>
  );
}
