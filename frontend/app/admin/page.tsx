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
  adminGetSystemStatus,
  type AdminRoomItem,
  type ErrorLogEntry,
  type CacheStats,
  type SystemStatus,
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

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await adminListErrorLogs({ resolved: showResolved ? undefined : false, limit: 100 });
      setLogs(data.entries);
      setTotal(data.total);
    } catch { /* silent */ }
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

  useEffect(() => {
    adminGetCacheStats().then(setStats).catch(() => {}).finally(() => setLoading(false));
  }, []);

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
          </div>
        </>
      ) : <p className="text-gray-500">載入失敗</p>}
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