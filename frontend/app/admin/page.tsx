"use client";

import { useState, useEffect, useCallback } from "react";
import {
  adminLogin,
  adminListRooms,
  adminCreateRoom,
  adminDeleteRoom,
  adminChangeRoomPassword,
  adminListErrorLogs,
  adminResolveErrorLog,
  adminResolveAllErrorLogs,
  adminGetCacheStats,
  adminClearCache,
  adminListSavedSongs,
  adminDeleteSavedSong,
  adminClearLeaderboard,
  adminGetSystemStatus,
  type SavedSong,
  adminGetRoomDetail,
  adminGetGuestDetail,
  AdminAuthError,
  type AdminRoomItem,
  type ErrorLogEntry,
  type CacheStats,
  type SystemStatus,
  type AdminRoomDetail,
  type AdminGuestDetail,
} from "@/lib/api";

// ── Login Screen ───────────────────────────────────────────────────────────────

function LoginScreen({ onLogin }: { onLogin: (token: string) => void }) {
  const [pw, setPw] = useState("");
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);

  async function handle(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setErr("");
    try {
      const { token } = await adminLogin(pw);
      localStorage.setItem("admin_token", token);
      onLogin(token);
    } catch {
      setErr("密碼錯誤");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center p-6">
      <form onSubmit={handle} className="w-full max-w-sm flex flex-col gap-4">
        <div className="text-center mb-2">
          <span className="text-4xl">🔐</span>
          <h1 className="text-xl font-bold text-white mt-2">管理員登入</h1>
        </div>
        <input
          type="password"
          value={pw}
          onChange={(e) => setPw(e.target.value)}
          placeholder="輸入管理員密碼"
          className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-3 text-white placeholder-gray-500 focus:outline-none focus:border-purple-500"
          autoFocus
        />
        {err && <p className="text-red-400 text-sm text-center">{err}</p>}
        <button
          type="submit"
          disabled={loading}
          className="w-full bg-purple-600 hover:bg-purple-500 disabled:opacity-50 text-white font-semibold py-3 rounded-lg transition-colors"
        >
          {loading ? "驗證中…" : "登入"}
        </button>
      </form>
    </div>
  );
}

// ── Rooms Tab ─────────────────────────────────────────────────────────────────

function RoomsTab() {
  const [rooms, setRooms] = useState<AdminRoomItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [createId, setCreateId] = useState("");
  const [createName, setCreateName] = useState("");
  const [createPw, setCreatePw] = useState("");
  const [deleting, setDeleting] = useState<string | null>(null);
  const [passwordEdit, setPasswordEdit] = useState<{ roomId: string; name: string; kind: "join" | "admin" } | null>(null);
  const [detailRoom, setDetailRoom] = useState<string | null>(null);
  const [newPw, setNewPw] = useState("");
  const [opError, setOpError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await adminListRooms();
      setRooms(data);
    } catch {
      setOpError("載入失敗");
    }
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!createId.trim() || !createName.trim()) return;
    try {
      const room = await adminCreateRoom({ id: createId.trim(), name: createName.trim(), password: createPw || undefined });
      setRooms((r) => [room, ...r]);
      setShowCreate(false);
      setCreateId(""); setCreateName(""); setCreatePw("");
    } catch {
      setOpError("建立失敗");
    }
  }

  async function handleDelete(roomId: string) {
    if (!confirm("刪除房間？")) return;
    setDeleting(roomId);
    try {
      await adminDeleteRoom(roomId);
      setRooms((r) => r.filter((x) => x.id !== roomId));
    } catch {
      setOpError("刪除失敗");
    }
    setDeleting(null);
  }

  async function handlePasswordChange(e: React.FormEvent) {
    e.preventDefault();
    if (!passwordEdit) return;
    try {
      if (passwordEdit.kind === "join") {
        const result = await adminChangeRoomPassword(passwordEdit.roomId, newPw || null);
        setRooms((r) => r.map((x) => x.id === passwordEdit.roomId ? { ...x, has_password: result.has_password } : x));
      } else {
        // admin-mode password — uses /api/rooms/{id}/admin-password
        if (!newPw.trim()) { setOpError("管理員密碼不能為空"); return; }
        const { setRoomAdminPassword } = await import("@/lib/api");
        await setRoomAdminPassword(passwordEdit.roomId, newPw);
      }
      setPasswordEdit(null);
      setNewPw("");
    } catch {
      setOpError("修改失敗");
    }
  }

  return (
    <div className="p-4 flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="text-white font-semibold text-lg">房間管理</h2>
        <button
          onClick={() => setShowCreate((v) => !v)}
          className="bg-purple-600 hover:bg-purple-500 text-white px-4 py-2 rounded-lg text-sm font-medium"
        >
          + 新建房間
        </button>
      </div>

      {showCreate && (
        <form onSubmit={handleCreate} className="bg-gray-900 border border-gray-700 rounded-lg p-4 flex flex-col gap-3">
          <div className="flex gap-3">
            <input
              value={createId}
              onChange={(e) => setCreateId(e.target.value)}
              placeholder="房間 ID (如 my-room)"
              className="flex-1 bg-gray-800 border border-gray-700 rounded px-3 py-2 text-white placeholder-gray-500 focus:outline-none focus:border-purple-500"
              pattern="[a-z0-9-]+"
            />
            <input
              value={createName}
              onChange={(e) => setCreateName(e.target.value)}
              placeholder="房間名稱"
              className="flex-1 bg-gray-800 border border-gray-700 rounded px-3 py-2 text-white placeholder-gray-500 focus:outline-none focus:border-purple-500"
            />
          </div>
          <input
            value={createPw}
            onChange={(e) => setCreatePw(e.target.value)}
            placeholder="密碼（可留空）"
            type="password"
            className="bg-gray-800 border border-gray-700 rounded px-3 py-2 text-white placeholder-gray-500 focus:outline-none focus:border-purple-500"
          />
          {opError && <p className="text-red-400 text-sm">{opError}</p>}
          <div className="flex gap-2">
            <button type="submit" className="bg-purple-600 hover:bg-purple-500 text-white px-4 py-2 rounded text-sm font-medium">建立</button>
            <button type="button" onClick={() => setShowCreate(false)} className="bg-gray-700 hover:bg-gray-600 text-white px-4 py-2 rounded text-sm font-medium">取消</button>
          </div>
        </form>
      )}

      {opError && !showCreate && <p className="text-red-400 text-sm">{opError}</p>}

      {loading ? (
        <p className="text-gray-500">載入中…</p>
      ) : rooms.length === 0 ? (
        <p className="text-gray-500">尚無房間</p>
      ) : (
        <div className="flex flex-col gap-2">
          {rooms.map((room) => (
            <div key={room.id} className="bg-gray-900 border border-gray-800 rounded-lg p-4 flex items-center justify-between">
              <div>
                <div className="text-white font-medium">{room.name}</div>
                <div className="text-gray-400 text-sm font-mono">/{room.id} · {room.created_at ? new Date(room.created_at).toLocaleDateString("zh-TW") : "—"}</div>
                <div className="text-gray-500 text-xs mt-1">
                  {room.has_password ? "🔒 有密碼" : "🔓 無密碼"}
                  {room.is_default && " · 預設"}
                </div>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => setDetailRoom(room.id)}
                  className="text-violet-300 hover:text-violet-200 text-sm px-3 py-1 border border-violet-800/50 rounded"
                  title="查看房間詳情"
                >
                  查看
                </button>
                <button
                  onClick={() => setPasswordEdit({ roomId: room.id, name: room.name, kind: "join" })}
                  className="text-gray-400 hover:text-white text-sm px-3 py-1 border border-gray-700 rounded"
                  title="入房密碼"
                >
                  入房密碼
                </button>
                <button
                  onClick={() => setPasswordEdit({ roomId: room.id, name: room.name, kind: "admin" })}
                  className="text-amber-400/80 hover:text-amber-300 text-sm px-3 py-1 border border-amber-900/50 rounded"
                  title="遙控管理員模式密碼"
                >
                  管理員密碼
                </button>
                <button
                  onClick={() => handleDelete(room.id)}
                  disabled={deleting === room.id}
                  className="text-red-400 hover:text-red-300 text-sm px-3 py-1 border border-red-900/50 rounded disabled:opacity-50"
                >
                  {deleting === room.id ? "刪除中…" : "刪除"}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {passwordEdit && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <form onSubmit={handlePasswordChange} className="bg-gray-900 border border-gray-700 rounded-lg p-6 w-full max-w-sm flex flex-col gap-4">
            <h3 className="text-white font-semibold">
              {passwordEdit.kind === "join" ? "修改入房密碼" : "修改管理員密碼"} — {passwordEdit.name}
            </h3>
            <p className="text-xs text-gray-500">
              {passwordEdit.kind === "join"
                ? "用戶進房間時要輸入的密碼。"
                : "遙控頭像點擊進入管理員模式時要輸入的密碼，可進行刪歌、拖曳排序等進階操作。"}
            </p>
            <input
              value={newPw}
              onChange={(e) => setNewPw(e.target.value)}
              placeholder={passwordEdit.kind === "join" ? "新密碼（留空移除密碼）" : "新管理員密碼"}
              type="password"
              className="bg-gray-800 border border-gray-700 rounded px-3 py-2 text-white placeholder-gray-500 focus:outline-none focus:border-purple-500"
              autoFocus
            />
            {opError && <p className="text-red-400 text-sm">{opError}</p>}
            <div className="flex gap-2">
              <button type="submit" className="bg-purple-600 hover:bg-purple-500 text-white px-4 py-2 rounded text-sm font-medium flex-1">儲存</button>
              <button type="button" onClick={() => { setPasswordEdit(null); setNewPw(""); setOpError(""); }} className="bg-gray-700 hover:bg-gray-600 text-white px-4 py-2 rounded text-sm font-medium flex-1">取消</button>
            </div>
          </form>
        </div>
      )}

      {detailRoom && (
        <RoomDetailPanel roomId={detailRoom} onClose={() => setDetailRoom(null)} />
      )}
    </div>
  );
}

// ── Room detail panel (online users, queue, processing, stats) ─────────────

function RoomDetailPanel({ roomId, onClose }: { roomId: string; onClose: () => void }) {
  const [data, setData] = useState<AdminRoomDetail | null>(null);
  const [err, setErr] = useState("");
  const [guestId, setGuestId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setErr("");
    try {
      setData(await adminGetRoomDetail(roomId));
    } catch (e) {
      if (!(e instanceof AdminAuthError)) setErr((e as Error).message || "載入失敗");
    }
  }, [roomId]);

  useEffect(() => {
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [load]);

  return (
    <div className="fixed inset-0 bg-black/70 z-50 flex items-start justify-center p-4 overflow-y-auto">
      <div className="bg-gray-900 border border-gray-700 rounded-xl w-full max-w-2xl my-8">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-800 sticky top-0 bg-gray-900 rounded-t-xl">
          <h3 className="text-white font-semibold">
            房間詳情 — {data?.room.name ?? roomId}
          </h3>
          <button onClick={onClose} className="text-gray-400 hover:text-white w-8 h-8 rounded-full hover:bg-gray-800">✕</button>
        </div>

        {err && <p className="text-red-400 text-sm p-5">{err}</p>}
        {!data && !err && <p className="text-gray-500 p-5">載入中…</p>}

        {data && (
          <div className="p-5 flex flex-col gap-5">
            <div className="grid grid-cols-4 gap-2">
              {[
                ["在線人數", data.online_count],
                ["隊列", data.queue_count],
                ["累計播放", data.stats.total_played],
                ["不重複歌", data.stats.unique_songs],
              ].map(([l, v]) => (
                <div key={l} className="bg-gray-800 rounded-lg p-3 text-center">
                  <div className="text-xl font-bold text-white">{v}</div>
                  <div className="text-[11px] text-gray-400 mt-0.5">{l}</div>
                </div>
              ))}
            </div>

            {Object.keys(data.processing_breakdown).length > 0 && (
              <div>
                <p className="text-gray-400 text-sm mb-2">隊列歌曲處理狀態</p>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(data.processing_breakdown).map(([k, v]) => (
                    <span key={k} className="text-xs bg-gray-800 text-gray-300 px-2.5 py-1 rounded-full">
                      {k}: {v}
                    </span>
                  ))}
                </div>
              </div>
            )}

            <div>
              <p className="text-gray-400 text-sm mb-2">在線用戶（點擊查看記錄）</p>
              {data.online_guests.length === 0 ? (
                <p className="text-gray-600 text-sm">目前無人在線</p>
              ) : (
                <div className="flex flex-col gap-1.5">
                  {data.online_guests.map((g) => (
                    <button
                      key={g.id}
                      onClick={() => setGuestId(g.id)}
                      className="flex items-center gap-2.5 bg-gray-800 hover:bg-gray-700 rounded-lg px-3 py-2 text-left transition-colors"
                    >
                      <div className="w-7 h-7 rounded-full flex items-center justify-center text-white text-xs font-bold flex-shrink-0"
                        style={{ backgroundColor: g.avatar_color ?? "#7c3aed" }}>
                        {g.nickname.slice(0, 1).toUpperCase()}
                      </div>
                      <span className="text-white text-sm flex-1">{g.nickname}</span>
                      {g.is_admin && <span className="text-amber-400 text-[10px]">管理員</span>}
                      <span className="text-gray-500 text-xs">{g.plays_here} 首</span>
                    </button>
                  ))}
                </div>
              )}
            </div>

            <div>
              <p className="text-gray-400 text-sm mb-2">隊列（{data.queue_count}）</p>
              {data.queue.length === 0 ? (
                <p className="text-gray-600 text-sm">隊列是空的</p>
              ) : (
                <div className="flex flex-col divide-y divide-gray-800 border border-gray-800 rounded-lg overflow-hidden">
                  {data.queue.map((qi) => (
                    <div key={qi.id} className="flex items-center gap-3 px-3 py-2 bg-gray-900">
                      <span className="text-gray-600 text-xs w-5 text-center">{qi.position}</span>
                      <div className="flex-1 min-w-0">
                        <p className="text-white text-sm truncate">{qi.title}</p>
                        <p className="text-gray-500 text-xs truncate">
                          {qi.artist ?? "—"} · {qi.requested_by ?? "?"}
                        </p>
                      </div>
                      <span className={`text-xs px-2 py-0.5 rounded-full ${
                        qi.status === "playing" ? "bg-violet-600 text-white"
                        : qi.status === "ready" ? "bg-emerald-700 text-emerald-100"
                        : "bg-amber-700 text-amber-100"
                      }`}>{qi.status}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {guestId && (
        <GuestDetailPanel guestId={guestId} onClose={() => setGuestId(null)} />
      )}
    </div>
  );
}

function GuestDetailPanel({ guestId, onClose }: { guestId: string; onClose: () => void }) {
  const [data, setData] = useState<AdminGuestDetail | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    adminGetGuestDetail(guestId)
      .then(setData)
      .catch((e) => { if (!(e instanceof AdminAuthError)) setErr((e as Error).message); });
  }, [guestId]);

  return (
    <div className="fixed inset-0 bg-black/80 z-[60] flex items-start justify-center p-4 overflow-y-auto" onClick={onClose}>
      <div className="bg-gray-900 border border-gray-700 rounded-xl w-full max-w-md my-8" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-800">
          <h3 className="text-white font-semibold">
            {data?.guest.nickname ?? "用戶"} 的記錄
          </h3>
          <button onClick={onClose} className="text-gray-400 hover:text-white w-8 h-8 rounded-full hover:bg-gray-800">✕</button>
        </div>
        {err && <p className="text-red-400 text-sm p-5">{err}</p>}
        {!data && !err && <p className="text-gray-500 p-5">載入中…</p>}
        {data && (
          <div className="p-5 flex flex-col gap-4">
            <div className="text-sm text-gray-400">
              累計播放 <span className="text-white font-bold">{data.total_plays}</span> 首
              {data.guest.first_seen && (
                <> · 首次 {new Date(data.guest.first_seen).toLocaleDateString("zh-TW")}</>
              )}
            </div>

            <div>
              <p className="text-gray-400 text-sm mb-1.5">⭐ 收藏（{data.favorites.length}）</p>
              {data.favorites.length === 0 ? (
                <p className="text-gray-600 text-sm">無</p>
              ) : (
                <div className="flex flex-col gap-1">
                  {data.favorites.map((s) => (
                    <div key={s.id} className="text-sm text-white truncate">
                      {s.title} <span className="text-gray-500">· {s.artist ?? "—"}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div>
              <p className="text-gray-400 text-sm mb-1.5">🕑 歷史記錄（最近 {data.history.length}）</p>
              {data.history.length === 0 ? (
                <p className="text-gray-600 text-sm">無</p>
              ) : (
                <div className="flex flex-col gap-1 max-h-64 overflow-y-auto">
                  {data.history.map((h, i) => (
                    <div key={i} className="text-sm text-gray-300 truncate">
                      {h.title}
                      <span className="text-gray-600 text-xs ml-2">
                        {h.played_at ? new Date(h.played_at).toLocaleString("zh-TW", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }) : ""}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Error Logs Tab ────────────────────────────────────────────────────────────

function ErrorLogsTab() {
  const [showResolved, setShowResolved] = useState(false);
  const [logs, setLogs] = useState<ErrorLogEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [resolvingId, setResolvingId] = useState<number | null>(null);
  const [resolveAllLoading, setResolveAllLoading] = useState(false);

  const [loadErr, setLoadErr] = useState("");
  const load = useCallback(async () => {
    setLoading(true);
    setLoadErr("");
    try {
      const data = await adminListErrorLogs({ resolved: showResolved ? undefined : false, limit: 100 });
      setLogs(data.entries);
      setTotal(data.total);
    } catch (e) {
      if (!(e instanceof AdminAuthError)) setLoadErr((e as Error).message || "載入失敗");
    }
    setLoading(false);
  }, [showResolved]);

  useEffect(() => { load(); }, [load]);

  async function handleResolve(logId: number) {
    setResolvingId(logId);
    try {
      await adminResolveErrorLog(logId);
      setLogs((l) => l.filter((e) => e.id !== logId));
      setTotal((t) => Math.max(0, t - 1));
    } catch { /* silent */ }
    setResolvingId(null);
  }

  async function handleResolveAll() {
    if (!confirm("標記全部為已解決？")) return;
    setResolveAllLoading(true);
    try {
      await adminResolveAllErrorLogs();
      setLogs([]);
      setTotal(0);
    } catch { /* silent */ }
    setResolveAllLoading(false);
  }

  return (
    <div className="p-4 flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-white font-semibold text-lg">錯誤日誌</h2>
          <p className="text-gray-400 text-sm">共 {total} 筆未解決</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setShowResolved((v) => !v)}
            className="text-gray-400 hover:text-white text-sm px-3 py-2 border border-gray-700 rounded"
          >
            {showResolved ? "隱藏已解決" : "顯示全部"}
          </button>
          {total > 0 && (
            <button
              onClick={handleResolveAll}
              disabled={resolveAllLoading}
              className="bg-green-700 hover:bg-green-600 disabled:opacity-50 text-white text-sm px-3 py-2 rounded"
            >
              {resolveAllLoading ? "處理中…" : "全部標記已解決"}
            </button>
          )}
        </div>
      </div>

      {loadErr && <p className="text-red-400 text-sm mb-2">載入失敗：{loadErr}</p>}

      {loading ? (
        <p className="text-gray-500">載入中…</p>
      ) : logs.length === 0 ? (
        <p className="text-gray-500">✅ 無錯誤日誌</p>
      ) : (
        <div className="flex flex-col gap-2 max-h-[60vh] overflow-y-auto">
          {logs.map((log) => (
            <div key={log.id} className="bg-gray-900 border border-gray-800 rounded-lg p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    {log.severity && (
                      <span className={`text-xs px-2 py-0.5 rounded font-mono ${
                        log.severity === "error" ? "bg-red-900/50 text-red-400" :
                        log.severity === "warning" ? "bg-yellow-900/50 text-yellow-400" :
                        "bg-gray-700 text-gray-400"
                      }`}>{log.severity}</span>
                    )}
                    {log.category && <span className="text-gray-500 text-xs font-mono">{log.category}</span>}
                    <span className="text-gray-500 text-xs">{log.occurred_at ? new Date(log.occurred_at).toLocaleString("zh-TW") : "—"}</span>
                  </div>
                  <p className="text-gray-200 text-sm break-all">{log.message}</p>
                  {log.context && Object.keys(log.context).length > 0 && (
                    <details className="mt-2">
                      <summary className="text-gray-500 text-xs cursor-pointer">context</summary>
                      <pre className="text-gray-600 text-xs mt-1 overflow-x-auto">{JSON.stringify(log.context, null, 2)}</pre>
                    </details>
                  )}
                </div>
                <button
                  onClick={() => handleResolve(log.id)}
                  disabled={resolvingId === log.id}
                  className="text-green-400 hover:text-green-300 text-sm px-3 py-1 border border-green-900/50 rounded shrink-0 disabled:opacity-50"
                >
                  {resolvingId === log.id ? "處理中…" : "已解決"}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Cache Tab ─────────────────────────────────────────────────────────────────

function CacheTab() {
  const [stats, setStats] = useState<CacheStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [clearing, setClearing] = useState(false);
  const [songs, setSongs] = useState<SavedSong[] | null>(null);
  const [songsTotal, setSongsTotal] = useState("");
  const [delId, setDelId] = useState<string | null>(null);

  const loadSongs = useCallback(async () => {
    try {
      const r = await adminListSavedSongs();
      setSongs(r.songs);
      setSongsTotal(r.total_human);
    } catch (e) {
      if (!(e instanceof AdminAuthError)) setSongs([]);
    }
  }, []);

  useEffect(() => {
    adminGetCacheStats().then(setStats).catch(() => {}).finally(() => setLoading(false));
    loadSongs();
  }, [loadSongs]);

  async function handleDeleteSong(s: SavedSong) {
    if (!confirm(`永久刪除「${s.title}」？\n會移除資料庫記錄與 ${s.human} 的媒體檔，無法復原。`)) return;
    setDelId(s.id);
    try {
      await adminDeleteSavedSong(s.id);
      setSongs((cur) => cur?.filter((x) => x.id !== s.id) ?? null);
      adminGetCacheStats().then(setStats).catch(() => {});
    } catch {
      alert("刪除失敗");
    }
    setDelId(null);
  }

  async function handleClear(what: "all" | "cache" | "tmp") {
    if (!confirm(`確定清除 ${what}？`)) return;
    setClearing(true);
    try {
      const result = await adminClearCache(what);
      const updated = await adminGetCacheStats();
      setStats(updated);
      alert(`已清除：${result.cleared.map((c) => `${c.dir} (${c.files_removed} 檔案, ${c.bytes_freed} bytes)`).join(" / ")}`);
    } catch {
      alert("清除失敗");
    }
    setClearing(false);
  }

  const fmt = (entry: { bytes: number; human: string }) => entry.human;

  return (
    <div className="p-4 flex flex-col gap-4">
      <h2 className="text-white font-semibold text-lg">磁碟用量</h2>
      <div className="bg-gray-900/60 border border-gray-800 rounded-lg p-3 text-xs text-gray-400 leading-relaxed">
        <p><span className="text-gray-300">media</span>：每首歌的成品（轉碼後影片、字幕 .ass/.txt、各來源歌詞快取）— 刪了該首歌要重新處理。</p>
        <p><span className="text-gray-300">cache</span>：原始下載（yt-dlp 原片）與 Demucs 人聲分離的 WAV/Opus — 最佔空間，刪了會重新下載/分離。</p>
        <p><span className="text-gray-300">tmp / logs</span>：暫存與日誌，可安全清除。</p>
      </div>
      {loading ? <p className="text-gray-500">載入中…</p> : stats ? (
        <>
          <div className="grid grid-cols-2 gap-3">
            {(["media", "cache", "logs", "tmp", "total"] as const).map((key) => {
              const entry = stats[key];
              const pct = stats.total.bytes > 0 ? Math.round((entry.bytes / stats.total.bytes) * 100) : 0;
              return (
                <div key={key} className="bg-gray-900 border border-gray-800 rounded-lg p-4">
                  <div className="text-gray-400 text-xs uppercase tracking-wider mb-1">{key}</div>
                  <div className="text-white text-xl font-mono">{entry.human}</div>
                  {key !== "total" && (
                    <div className="mt-2 h-1.5 bg-gray-800 rounded-full overflow-hidden">
                      <div className="h-full bg-purple-600 rounded-full" style={{ width: `${pct}%` }} />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          <div className="flex gap-3">
            <button onClick={() => handleClear("cache")} disabled={clearing} className="bg-yellow-700 hover:bg-yellow-600 disabled:opacity-50 text-white px-4 py-2 rounded text-sm font-medium">
              清除 Cache
            </button>
            <button onClick={() => handleClear("tmp")} disabled={clearing} className="bg-yellow-700 hover:bg-yellow-600 disabled:opacity-50 text-white px-4 py-2 rounded text-sm font-medium">
              清除 Tmp
            </button>
            <button onClick={() => handleClear("all")} disabled={clearing} className="bg-red-700 hover:bg-red-600 disabled:opacity-50 text-white px-4 py-2 rounded text-sm font-medium">
              {clearing ? "清除中…" : "清除全部"}
            </button>
            <button
              onClick={async () => {
                if (!confirm("清除所有排行榜資料（播放歷史 + 播放次數歸零）？")) return;
                try {
                  const r = await adminClearLeaderboard();
                  alert(`已清除 ${r.removed} 筆播放記錄`);
                } catch { alert("清除失敗"); }
              }}
              className="bg-orange-700 hover:bg-orange-600 text-white px-4 py-2 rounded text-sm font-medium"
            >
              清除排行榜
            </button>
          </div>
        </>
      ) : <p className="text-gray-500">載入失敗</p>}

      {/* Saved songs — per-song footprint + delete */}
      <div className="mt-2">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-white font-semibold text-lg">已保存歌曲</h2>
          {songs && (
            <span className="text-gray-400 text-sm">
              {songs.length} 首 · 共 {songsTotal}
            </span>
          )}
        </div>
        {!songs ? (
          <p className="text-gray-500">載入中…</p>
        ) : songs.length === 0 ? (
          <p className="text-gray-500">尚無保存的歌曲</p>
        ) : (
          <div className="flex flex-col divide-y divide-gray-800 border border-gray-800 rounded-lg overflow-hidden">
            {songs.map((s) => (
              <div key={s.id} className="flex items-center gap-3 px-3 py-2.5 bg-gray-900">
                <div className="flex-1 min-w-0">
                  <p className="text-white text-sm truncate">{s.title}</p>
                  <p className="text-gray-500 text-xs truncate">
                    {s.artist ?? "—"} · {s.status}
                    {s.play_count > 0 && ` · 播 ${s.play_count} 次`}
                    {s.has_timing ? " · 有字幕" : ""}
                  </p>
                </div>
                <span className="text-gray-400 text-sm font-mono w-20 text-right flex-shrink-0">
                  {s.human}
                </span>
                <button
                  onClick={() => handleDeleteSong(s)}
                  disabled={delId === s.id}
                  className="text-red-400 hover:text-red-300 text-sm px-3 py-1 border border-red-900/50 rounded flex-shrink-0 disabled:opacity-50"
                >
                  {delId === s.id ? "刪除中…" : "刪除"}
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── System Status Tab ─────────────────────────────────────────────────────────

function SystemStatusTab() {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    adminGetSystemStatus().then(setStatus).catch(() => {}).finally(() => setLoading(false));
  }, []);

  return (
    <div className="p-4 flex flex-col gap-4">
      <h2 className="text-white font-semibold text-lg">系統狀態</h2>
      {loading ? <p className="text-gray-500">載入中…</p> : status ? (
        <div className="flex flex-col gap-4">
          {/* GPU */}
          <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
            <h3 className="text-gray-400 text-xs uppercase tracking-wider mb-3">GPU</h3>
            {status.gpu.available ? (
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <div className="text-gray-500 text-xs">型號</div>
                  <div className="text-white font-mono text-sm">{status.gpu.name ?? "—"}</div>
                </div>
                <div>
                  <div className="text-gray-500 text-xs">VRAM</div>
                  <div className="text-white font-mono text-sm">
                    {status.gpu.memory_used_mb != null ? `${(status.gpu.memory_used_mb / 1024).toFixed(1)} GB / ${(status.gpu.memory_total_mb! / 1024).toFixed(1)} GB` : "—"}
                  </div>
                </div>
              </div>
            ) : (
              <p className="text-gray-500 text-sm">GPU 不可用</p>
            )}
          </div>

          {/* Pipeline */}
          <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
            <h3 className="text-gray-400 text-xs uppercase tracking-wider mb-3">Pipeline</h3>
            <div className="text-white text-2xl font-mono">{status.pipeline.pending_count}</div>
            <p className="text-gray-500 text-sm">pending songs</p>
          </div>

          {/* Songs */}
          <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
            <h3 className="text-gray-400 text-xs uppercase tracking-wider mb-3">Songs</h3>
            <div className="grid grid-cols-3 gap-4 text-center">
              <div>
                <div className="text-white text-xl font-mono">{status.songs.total}</div>
                <div className="text-gray-500 text-xs">總數</div>
              </div>
              <div>
                <div className="text-green-400 text-xl font-mono">{status.songs.ready}</div>
                <div className="text-gray-500 text-xs">ready</div>
              </div>
              <div>
                <div className="text-red-400 text-xl font-mono">{status.songs.failed}</div>
                <div className="text-gray-500 text-xs">failed</div>
              </div>
            </div>
          </div>

          {/* DB */}
          <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
            <h3 className="text-gray-400 text-xs uppercase tracking-wider mb-3">Database</h3>
            <div className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full ${status.db_connected ? "bg-green-400" : "bg-red-400"}`} />
              <span className="text-white text-sm font-mono">{status.db_connected ? "Connected" : "Disconnected"}</span>
            </div>
            <p className="text-gray-500 text-xs font-mono mt-1">{status.db_path}</p>
          </div>
        </div>
      ) : <p className="text-gray-500">載入失敗</p>}
    </div>
  );
}

// ── Main Admin Page ───────────────────────────────────────────────────────────

type Tab = "rooms" | "errors" | "cache" | "system";

export default function AdminPage() {
  const [token, setToken] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("rooms");

  useEffect(() => {
    const stored = localStorage.getItem("admin_token");
    if (stored) setToken(stored);
    const onExpired = () => setToken(null);
    window.addEventListener("admin-auth-expired", onExpired);
    return () => window.removeEventListener("admin-auth-expired", onExpired);
  }, []);

  if (!token) {
    return <LoginScreen onLogin={setToken} />;
  }

  const TABS: { id: Tab; label: string; icon: string }[] = [
    { id: "rooms", label: "房間", icon: "🚪" },
    { id: "errors", label: "錯誤日誌", icon: "📋" },
    { id: "cache", label: "緩存", icon: "💾" },
    { id: "system", label: "系統", icon: "🖥️" },
  ];

  return (
    <div className="min-h-screen bg-gray-950 flex flex-col">
      {/* Header */}
      <header className="flex items-center justify-between px-6 py-4 border-b border-gray-800 bg-gray-900">
        <div className="flex items-center gap-3">
          <span className="text-2xl">🛠️</span>
          <h1 className="text-white font-semibold text-lg">管理員後台</h1>
        </div>
        <button
          onClick={() => { localStorage.removeItem("admin_token"); setToken(null); }}
          className="text-gray-400 hover:text-white text-sm"
        >
          登出
        </button>
      </header>

      {/* Tab bar */}
      <nav className="flex border-b border-gray-800 bg-gray-900/50">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`flex-1 flex items-center justify-center gap-2 py-3 text-sm font-medium transition-colors ${
              tab === t.id ? "text-purple-400 border-b-2 border-purple-400" : "text-gray-500 hover:text-gray-300"
            }`}
          >
            <span>{t.icon}</span>
            <span>{t.label}</span>
          </button>
        ))}
      </nav>

      {/* Content */}
      <main className="flex-1 overflow-y-auto">
        {tab === "rooms" && <RoomsTab />}
        {tab === "errors" && <ErrorLogsTab />}
        {tab === "cache" && <CacheTab />}
        {tab === "system" && <SystemStatusTab />}
      </main>
    </div>
  );
}