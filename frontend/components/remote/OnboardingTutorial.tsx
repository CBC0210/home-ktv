"use client";

import { useEffect, useLayoutEffect, useRef, useState, useCallback } from "react";

export type TourTab = "playing" | "queue" | "search" | "room";

interface Step {
  /** data-tour value of the element to spotlight. Omit for a centered card. */
  target?: string;
  /** Switch the Remote to this tab before measuring the target. */
  tab?: TourTab;
  tag: string;
  title: string;
  body: React.ReactNode;
}

const STEPS: Step[] = [
  {
    tag: "遙控",
    title: "手機遙控",
    body: (
      <>搜尋點歌、控制播放、管理隊列、揪朋友一起唱 —— 都在這支遙控器上。以下是各個分頁的功能。</>
    ),
  },
  {
    target: "tabbar",
    tag: "導覽",
    title: "底部四個分頁",
    body: (
      <>由左到右:<span className="text-white font-medium">播放 · 隊列 · 搜尋 · 房間</span>,點一下即切換。</>
    ),
  },
  {
    target: "search-input",
    tab: "search",
    tag: "搜尋",
    title: "搜尋點歌",
    body: (
      <>打歌名(例如 <span className="text-violet-300 font-medium">周杰倫 晴天</span>)或
        <span className="text-white font-medium">貼上 YouTube／Bilibili 連結</span>,
        點每列右邊的 <span className="text-white font-medium">＋</span> 加入隊列。
        標 <span className="text-emerald-300 font-medium">⚡立即</span> = 已快取秒播;新歌會先處理幾分鐘。</>
    ),
  },
  {
    target: "nav-playing",
    tab: "playing",
    tag: "播放",
    title: "播放控制",
    body: (
      <>正在唱的歌顯示在這頁:<span className="text-white font-medium">▶播放/暫停、⏭切歌、進度條</span>,
        以及兩條音量 —— <span className="text-white font-medium">人聲拉到 0% 就是伴奏</span>。也能送表情、回報音訊問題。</>
    ),
  },
  {
    target: "nav-queue",
    tab: "queue",
    tag: "隊列",
    title: "待播隊列",
    body: (
      <>接下來要唱的歌都在這。同一個人連點的歌會<span className="text-white font-medium">自動錯開輪流</span>。
        管理員模式下可拖曳排序、刪歌。</>
    ),
  },
  {
    target: "copy-link",
    tab: "room",
    tag: "房間",
    title: "邀請朋友",
    body: (
      <><span className="text-white font-medium">複製房間連結</span>傳給朋友,
        或讓他們<span className="text-white font-medium">掃電視上的 QR code</span>,進來免再輸密碼。
        這頁也能看統計、在線的人、離開房間。</>
    ),
  },
  {
    target: "admin",
    tag: "管理員",
    title: "管理員模式",
    body: (
      <>點右上角<span className="text-white font-medium">頭像</span>,輸入管理員密碼即可解鎖
        <span className="text-amber-300 font-medium">拖曳排序、刪歌、踢人</span>。再點一次退出。
        (密碼問主辦人。)</>
    ),
  },
  {
    target: "help",
    tag: "說明",
    title: "重看教學",
    body: <>右上角的 <span className="text-violet-300 font-medium">?</span> 隨時能再打開這份說明。</>,
  },
];

interface Props {
  open: boolean;
  onClose: (dontShowAgain: boolean) => void;
  onNavigate: (tab: TourTab) => void;
}

interface Box { top: number; left: number; width: number; height: number }

export default function OnboardingTutorial({ open, onClose, onNavigate }: Props) {
  const [step, setStep] = useState(0);
  const [dontShow, setDontShow] = useState(true);
  const [box, setBox] = useState<Box | null>(null);
  const rafRef = useRef<number | null>(null);

  const current = STEPS[step];

  const measure = useCallback(() => {
    const target = current?.target;
    if (!target) { setBox(null); return; }
    const el = document.querySelector<HTMLElement>(`[data-tour="${target}"]`);
    if (!el) { setBox(null); return; }
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) { setBox(null); return; }
    setBox({ top: r.top, left: r.left, width: r.width, height: r.height });
  }, [current]);

  // On step change: navigate to the right tab, then measure once the tab's
  // content has mounted (rAF + a short backstop for slower renders).
  useLayoutEffect(() => {
    if (!open) return;
    setBox(null);
    if (current?.tab) onNavigate(current.tab);
    const run = () => { measure(); };
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    rafRef.current = requestAnimationFrame(() => requestAnimationFrame(run));
    const t1 = setTimeout(measure, 140);
    const t2 = setTimeout(measure, 340);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      clearTimeout(t1); clearTimeout(t2);
    };
  }, [open, step, current, onNavigate, measure]);

  // Keep the spotlight aligned on resize / scroll.
  useEffect(() => {
    if (!open) return;
    const onChange = () => measure();
    window.addEventListener("resize", onChange);
    window.addEventListener("scroll", onChange, true);
    return () => {
      window.removeEventListener("resize", onChange);
      window.removeEventListener("scroll", onChange, true);
    };
  }, [open, measure]);

  // Reset to step 0 whenever it (re)opens.
  useEffect(() => { if (open) setStep(0); }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(dontShow); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, dontShow, onClose]);

  if (!open) return null;

  const isLast = step === STEPS.length - 1;
  const PAD = 6;

  // Tooltip placement: below the target if it sits in the top half, else above.
  let cardStyle: React.CSSProperties;
  if (box) {
    const vw = window.innerWidth;
    const cardW = Math.min(360, vw - 24);
    const centerX = box.left + box.width / 2;
    const left = Math.max(12, Math.min(centerX - cardW / 2, vw - cardW - 12));
    const placeAbove = box.top > window.innerHeight * 0.5;
    cardStyle = placeAbove
      ? { left, width: cardW, bottom: window.innerHeight - box.top + 16 }
      : { left, width: cardW, top: box.top + box.height + 16 };
  } else {
    cardStyle = { left: "50%", top: "50%", transform: "translate(-50%, -50%)", width: "min(360px, 92vw)" };
  }

  return (
    <div className="fixed inset-0 z-[70]" role="dialog" aria-modal="true" aria-label="使用教學">
      {/* Passive click-blocker so stray taps hit neither the app underneath
          nor accidentally dismiss the tour — closing is via the buttons only. */}
      <div className="absolute inset-0" aria-hidden="true" />

      {/* Dimmer: a spotlight cutout when we have a target, else a flat scrim */}
      {box ? (
        <div
          className="absolute rounded-2xl ring-2 ring-violet-400/90 pointer-events-none transition-all duration-300"
          style={{
            top: box.top - PAD,
            left: box.left - PAD,
            width: box.width + PAD * 2,
            height: box.height + PAD * 2,
            boxShadow: "0 0 0 9999px rgba(0,0,0,0.80)",
          }}
        />
      ) : (
        <div className="absolute inset-0 bg-black/80 pointer-events-none" />
      )}

      {/* Tooltip card */}
      <div
        className="absolute bg-[#171717] border border-white/10 rounded-2xl shadow-2xl overflow-hidden"
        style={cardStyle}
      >
        <div className="px-5 pt-5 pb-4">
          <div className="flex items-center justify-between mb-2.5">
            <span className="text-[10px] font-bold uppercase tracking-wider text-violet-300/85 bg-violet-500/10 border border-violet-500/25 rounded-full px-2.5 py-1">
              {current.tag}
            </span>
            <span className="text-white/30 text-xs font-mono tabular-nums">{step + 1} / {STEPS.length}</span>
          </div>
          <h2 className="text-white font-bold text-lg mb-1.5 tracking-tight">{current.title}</h2>
          <p className="text-white/60 text-[13.5px] leading-relaxed">{current.body}</p>
        </div>

        {/* Progress dots */}
        <div className="flex justify-center gap-1.5 pb-3">
          {STEPS.map((_, i) => (
            <button
              key={i}
              onClick={() => setStep(i)}
              aria-label={`第 ${i + 1} 步`}
              className={`h-1.5 rounded-full transition-all ${
                i === step ? "w-5 bg-violet-400" : "w-1.5 bg-white/20 hover:bg-white/35"
              }`}
            />
          ))}
        </div>

        <div className="px-5 pb-4 pt-1 border-t border-white/6">
          <label className="flex items-center gap-2.5 py-2.5 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={dontShow}
              onChange={(e) => setDontShow(e.target.checked)}
              className="w-4 h-4 rounded accent-violet-500"
            />
            <span className="text-white/45 text-xs">不要再自動顯示教學</span>
          </label>
          <div className="flex items-center gap-2">
            <button
              onClick={() => onClose(dontShow)}
              className="px-3 py-2.5 rounded-xl text-white/45 text-sm hover:text-white/75 transition-colors"
            >
              跳過
            </button>
            <div className="flex-1" />
            {step > 0 && (
              <button
                onClick={() => setStep((v) => v - 1)}
                className="px-4 py-2.5 rounded-xl bg-white/8 text-white/70 text-sm hover:bg-white/12 transition-colors"
              >
                上一步
              </button>
            )}
            <button
              onClick={() => (isLast ? onClose(dontShow) : setStep((v) => v + 1))}
              className="px-5 py-2.5 rounded-xl bg-violet-600 text-white text-sm font-medium hover:bg-violet-500 transition-colors"
            >
              {isLast ? "開始使用" : "下一步"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
