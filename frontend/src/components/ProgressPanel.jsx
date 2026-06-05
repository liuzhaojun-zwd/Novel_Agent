import { useState, useEffect } from "react";
import { api } from "../api";
import { useSSE } from "../hooks/useSSE";

export default function ProgressPanel({ jobId, onBack }) {
  const [job, setJob] = useState(null);
  const [chapters, setChapters] = useState([]);
  const [currentChapter, setCurrentChapter] = useState(0);
  const [statusText, setStatusText] = useState("");
  const [alerts, setAlerts] = useState([]);
  const [readingChapter, setReadingChapter] = useState(null);
  const [exporting, setExporting] = useState(false);
  const [exportMsg, setExportMsg] = useState("");
  const [starting, setStarting] = useState(false);

  // 加载任务数据
  const loadJob = async () => {
    try {
      const j = await api.getJob(jobId);
      setJob(j);
      setCurrentChapter(j.current_chapter);
      setAlerts(j.consistency_alerts || []);
      updateStatusText(j.status, j.current_chapter, j.chapter_count);
    } catch (e) { /* ignore */ }
  };

  const loadChapters = async () => {
    try {
      const chs = await api.getChapters(jobId);
      setChapters(chs);
    } catch (e) { /* ignore */ }
  };

  useEffect(() => {
    loadJob();
    loadChapters();
  }, [jobId]);

  const updateStatusText = (st, cur, total) => {
    const map = {
      pending: "等待中",
      generating_outline: "正在生成大纲...",
      generating_chapters: cur === 0
        ? `准备中 (共${total}章，首次生成较慢请耐心等待)`
        : `写作中 (已完成 ${cur}/${total} 章)`,
      paused: `已暂停 (已完成 ${cur} 章)`,
      completed: "✅ 已完成",
      failed: "❌ 生成失败",
    };
    setStatusText(map[st] || st);
  };

  // SSE 实时推送
  useSSE(jobId, (event, data) => {
    if (event === "progress") {
      setCurrentChapter(data.chapter);
      setStatusText(
        data.chapter === 0
          ? `准备中 (共${data.total}章，正在调用AI生成...)`
          : `写作中 (已完成 ${data.chapter}/${data.total} 章)`
      );
      loadChapters();
    } else if (event === "chapter_complete") {
      loadChapters();
      loadJob();
    } else if (event === "batch_complete") {
      setCurrentChapter(data.chapter);
      setStatusText(`已暂停 (已完成 ${data.chapter} 章)`);
      loadChapters();
      loadJob();
    } else if (event === "job_complete") {
      loadJob();
      loadChapters();
    } else if (event === "error") {
      loadJob();
    }
  });

  const handleStart = async (upTo) => {
    if (starting) return;
    setStarting(true);
    setStatusText("");
    try {
      await api.startGeneration(jobId, upTo);
      // 立即更新状态显示
      await loadJob();
      await loadChapters();
    } catch (e) {
      setStatusText("启动失败: " + e.message);
    } finally {
      setStarting(false);
    }
  };

  const handleResume = async (upTo) => {
    if (starting) return;
    setStarting(true);
    setStatusText("");
    try {
      await api.resumeGeneration(jobId, upTo);
      await loadJob();
      await loadChapters();
    } catch (e) {
      setStatusText("续生失败: " + e.message);
    } finally {
      setStarting(false);
    }
  };

  const handleExport = async (fmt) => {
    setExporting(true);
    setExportMsg("");
    try {
      const url = api.getExportUrl(jobId, fmt);
      // 创建下载链接
      const a = document.createElement("a");
      a.href = url;
      a.download = "";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setExportMsg(`✅ 已开始下载 .${fmt} 文件`);
    } catch (e) {
      setExportMsg("导出失败: " + e.message);
    } finally {
      setExporting(false);
    }
  };

  const totalChapters = job?.chapter_count || 0;
  const completedChapters = chapters.filter((c) => c.status === "completed").length;
  const progressPct = totalChapters > 0 ? Math.round((completedChapters / totalChapters) * 100) : 0;

  if (!job) return <div className="text-center py-12 text-gray-400">加载中...</div>;

  return (
    <div className="max-w-4xl mx-auto py-8 px-4">
      <button onClick={onBack} className="text-sm text-indigo-600 hover:text-indigo-800 mb-4 cursor-pointer">
        ← 返回任务列表
      </button>

      {/* 顶部状态卡 */}
      <div className="bg-white rounded-xl p-6 shadow-sm border border-gray-100 mb-6">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-xl font-bold text-gray-900">{job.theme}</h2>
            <p className="text-gray-500 mt-1">{job.topic}</p>
          </div>
          <div className="text-right">
            <span className={`inline-block px-3 py-1 rounded-full text-sm font-medium ${
              job.status === "completed" ? "bg-green-100 text-green-700" :
              job.status === "failed" ? "bg-red-100 text-red-700" :
              job.status === "paused" ? "bg-yellow-100 text-yellow-700" :
              job.status === "generating_chapters" ? "bg-blue-100 text-blue-700" :
              "bg-gray-100 text-gray-600"
            }`}>
              {statusText}
            </span>
          </div>
        </div>

        {/* 进度条 */}
        <div className="mt-4">
          <div className="flex justify-between text-sm text-gray-500 mb-1">
            <span>{completedChapters}/{totalChapters} 章</span>
            <span>{progressPct}%</span>
          </div>
          <div className="w-full bg-gray-100 rounded-full h-2 overflow-hidden">
            <div
              className="bg-indigo-600 h-full rounded-full transition-all duration-500"
              style={{ width: `${progressPct}%` }}
            />
          </div>
        </div>
      </div>

      {/* 操作按钮 */}
      <div className="flex flex-wrap gap-2 mb-6">
        {/* 首次启动：可指定写几章 */}
        {job.status === "pending" && job.outline && (
          <div className="flex flex-wrap items-center gap-2">
            <button onClick={() => handleStart(totalChapters < 5 ? totalChapters : 5)} disabled={starting} className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-400 text-white rounded-lg text-sm font-medium transition cursor-pointer disabled:cursor-not-allowed">
              {starting ? "⏳ 启动中..." : "▶️ 写5章"}
            </button>
            <button onClick={() => handleStart(totalChapters < 10 ? totalChapters : 10)} disabled={starting} className="px-4 py-2 bg-indigo-500 hover:bg-indigo-600 disabled:bg-indigo-400 text-white rounded-lg text-sm font-medium transition cursor-pointer disabled:cursor-not-allowed">
              {starting ? "⏳ 启动中..." : "▶️ 写10章"}
            </button>
            <button onClick={() => handleStart()} disabled={starting} className="px-4 py-2 bg-indigo-700 hover:bg-indigo-800 disabled:bg-indigo-400 text-white rounded-lg text-sm font-medium transition cursor-pointer disabled:cursor-not-allowed">
              {starting ? "⏳ 启动中..." : `▶️ 全部(${totalChapters}章)`}
            </button>
          </div>
        )}

        {/* 续写：可指定续写几章 */}
        {job.status === "paused" && (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm text-gray-500 mr-1">续写:</span>
            <button onClick={() => handleResume(completedChapters + 5 > totalChapters ? totalChapters : completedChapters + 5)} disabled={starting} className="px-4 py-2 bg-amber-600 hover:bg-amber-700 disabled:bg-amber-400 text-white rounded-lg text-sm font-medium transition cursor-pointer disabled:cursor-not-allowed">
              {starting ? "⏳" : "5章"}
            </button>
            <button onClick={() => handleResume(completedChapters + 10 > totalChapters ? totalChapters : completedChapters + 10)} disabled={starting} className="px-4 py-2 bg-amber-500 hover:bg-amber-600 disabled:bg-amber-400 text-white rounded-lg text-sm font-medium transition cursor-pointer disabled:cursor-not-allowed">
              {starting ? "⏳" : "10章"}
            </button>
            <button onClick={() => handleResume()} disabled={starting} className="px-4 py-2 bg-amber-700 hover:bg-amber-800 disabled:bg-amber-400 text-white rounded-lg text-sm font-medium transition cursor-pointer disabled:cursor-not-allowed">
              {starting ? "⏳" : `全部(剩余${totalChapters - completedChapters}章)`}
            </button>
          </div>
        )}
        <button
          onClick={() => handleExport("md")}
          disabled={exporting || completedChapters === 0}
          className="px-4 py-2 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-50 transition cursor-pointer"
        >
          📥 导出 MD
        </button>
        <button
          onClick={() => handleExport("txt")}
          disabled={exporting || completedChapters === 0}
          className="px-4 py-2 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-50 transition cursor-pointer"
        >
          📥 导出 TXT
        </button>
      </div>
      {exportMsg && <p className="text-sm text-gray-600 mb-4">{exportMsg}</p>}

      {/* 章节列表 */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-1">
          <h3 className="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-3">
            章节列表
          </h3>
          <div className="space-y-2">
            {chapters.map((ch) => (
              <button
                key={ch.chapter_number}
                onClick={() => setReadingChapter(ch)}
                className={`w-full text-left p-3 rounded-lg border transition cursor-pointer ${
                  ch.status === "completed"
                    ? "border-green-200 bg-green-50 hover:bg-green-100"
                    : "border-gray-100 bg-white hover:bg-gray-50"
                } ${readingChapter?.chapter_number === ch.chapter_number ? "ring-2 ring-indigo-500" : ""}`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium text-sm text-gray-900 truncate">
                    #{ch.chapter_number} {ch.title}
                  </span>
                  {ch.status === "completed" && (
                    <span className="text-green-500 text-xs">✓</span>
                  )}
                </div>
                {ch.word_count > 0 && (
                  <span className="text-xs text-gray-400">{ch.word_count} 字</span>
                )}
              </button>
            ))}
          </div>
        </div>

        {/* 正文阅读 */}
        <div className="lg:col-span-2">
          {readingChapter ? (
            <div className="bg-white rounded-xl p-6 shadow-sm border border-gray-100">
              <h3 className="text-lg font-bold text-gray-900 mb-1">
                第{readingChapter.chapter_number}章 {readingChapter.title}
              </h3>
              <p className="text-sm text-gray-400 mb-4">{readingChapter.word_count} 字</p>
              <div className="prose text-gray-700 leading-relaxed whitespace-pre-wrap">
                {readingChapter.content || (
                  <span className="text-gray-300 italic">正文生成中...</span>
                )}
              </div>
            </div>
          ) : (
            <div className="bg-gray-50 rounded-xl p-12 text-center text-gray-400 border border-dashed border-gray-200">
              <div className="text-4xl mb-2">📖</div>
              <p>点击左侧章节查看正文</p>
            </div>
          )}
        </div>
      </div>

      {/* 一致性告警 */}
      {alerts.length > 0 && (
        <div className="mt-6 bg-yellow-50 border border-yellow-200 rounded-lg p-4">
          <h4 className="text-sm font-semibold text-yellow-800 mb-2">⚠️ 一致性告警</h4>
          <div className="space-y-1">
            {alerts.map((a, i) => (
              <p key={i} className="text-sm text-yellow-700">
                第 {a.chapter_number} 章 — 检测到未定义人物 "{a.conflict_name}"
              </p>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}