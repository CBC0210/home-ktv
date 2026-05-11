import Link from "next/link";
import type { Room } from "@/lib/types";

interface Props {
  room: Room;
}

export default function RoomCard({ room }: Props) {
  return (
    <div className="bg-gray-800 rounded-xl p-5 flex flex-col gap-3 border border-gray-700 hover:border-purple-500 transition-colors">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-white">{room.name}</h2>
        {room.has_password && (
          <span className="text-xs bg-gray-700 text-gray-300 px-2 py-0.5 rounded-full">
            🔒 密碼保護
          </span>
        )}
        {room.is_default && (
          <span className="text-xs bg-purple-900 text-purple-200 px-2 py-0.5 rounded-full">
            預設
          </span>
        )}
      </div>
      <p className="text-gray-400 text-sm font-mono">/{room.id}</p>
      <div className="flex gap-2 mt-1">
        <Link
          href={`/r/${room.id}/remote`}
          className="flex-1 text-center bg-purple-600 hover:bg-purple-500 text-white text-sm font-medium py-2 rounded-lg transition-colors"
        >
          📱 點歌遙控
        </Link>
        <Link
          href={`/r/${room.id}/player`}
          className="flex-1 text-center bg-gray-700 hover:bg-gray-600 text-white text-sm font-medium py-2 rounded-lg transition-colors"
        >
          📺 播放器
        </Link>
      </div>
    </div>
  );
}
