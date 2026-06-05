import { useState, useEffect, useCallback } from "react";
import SetupForm from "./components/SetupForm";
import OutlineView from "./components/OutlineView";
import ProgressPanel from "./components/ProgressPanel";
import SettingsModal from "./components/SettingsModal";
import { CardSkeleton } from "./components/LoadingSkeleton";
import { api } from "./api";

export default function App() {
  const [view, setView] = useState("setup"); // setup | outline | progress
  const [currentJobId, setCurrentJobId] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [draftOutline, setDraftOutline] = useState(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [llmReady, setLlmReady] = useState(false);
  const [initialLoading, setInitialLoading] = useState(true);

  // Issue 9: 暗色模式
  const [darkMode, setDarkMode] = useState(() => {
    if (typeof window !== "undefined") {
      return localStorage.getItem("novel-dark") === "true";
    }
    return false;
  });

  useEffect(() => {
    if (darkMode) {
      document.documentElement.classList.add("dark");
    } else {
      document.documentElement.classList.remove("dark");
    }
    localStorage.setItem("novel-dark", darkMode);
  }, [darkMode]);

  // 启动时检查 API Key
  useEffect(() => {
    api.checkSetupStatus().then((s) => {
      if (!s.llm_configured) {
        setSettingsOpen(true);
      } else {
        setLlmReady(true);
      }
    }).catch(() => setLlmReady(true));
    loadJobs().finally(() => setInitialLoading(false));
  }, []);

  const loadJobs = async () => {
    try {
      const list = await api.listJobs();
      setJobs(list);
    } catch (_) {}
  };

  const handleJobCreated = async (jobId) => {
    setCurrentJobId(jobId);
    await loadJobs();
    setView("outline");
  };

  const handleOutlineConfirm = async () => {
    setView("progress");
  };

  const handleBack = useCallback(() => {
    setView("setup");
    setCurrentJobId(null);
    setDraftOutline(null);
    loadJobs();
  }, []);

  const handleSelectJob = async (jobId) => {
    setCurrentJobId(jobId);
    const job = await api.getJob(jobId);
    if (job.outline) setDraftOutline(job.outline);
    if (job.status === "pending" && job.outline) {
      setView("outline");
    } else if (["generating_chapters", "paused", "completed", "failed"].includes(job.status)) {
      setView("progress");
    } else {
      setView("outline");
    }
  };

  // Issue 9: 键盘快捷键
  useEffect(() => {
    const handleKeyDown = (e) => {
      // Ctrl+1 = 回到首页, Ctrl+2 = 暗色切换
      if (e.ctrlKey && e.key === "1") {
        e.preventDefault();
        handleBack();
      } else if (e.ctrlKey && e.key === "2") {
        e.preventDefault();
        setDarkMode(d => !d);
      } else if (e.ctrlKey && e.key === "o" && !settingsOpen) {
        e.preventDefault();
        setSettingsOpen(true);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleBack, settingsOpen]);

  if (initialLoading) {
    return (
      <div className="min-h-screen bg-gray-50 dark:bg-gray-900 flex items-center justify-center">
        <div className="text-center">
          <div className="text-4xl mb-4 animate-pulse">✍️</div>
          <div className="text-gray-400 dark:text-gray-500">加载中...</div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900 transition-colors duration-200">
      {/* 顶部导航 */}
      <header className="bg-white dark:bg-gray-800 border-b border-gray-100 dark:border-gray-700">
        <div className="max-w-4xl mx-auto px-4 h-14 flex items-center justify-between">
          <div
            className="flex items-center gap-2 cursor-pointer"
            onClick={() => { setView("setup"); setCurrentJobId(null); }}
          >
            <span className="font-bold text-gray-900 dark:text-white">Novel_Agent</span>
            <span className="text-xs text-gray-400 dark:text-gray-500 bg-gray-100 dark:bg-gray-700 px-2 py-0.5 rounded-full">小说创作</span>
          </div>
          <div className="flex items-center gap-3">
            {!llmReady && (
              <span className="text-xs text-amber-500">⚠️ 未配置 API</span>
            )}
            {/* Issue 9: 暗色切换 */}
            <button
              onClick={() => setDarkMode(d => !d)}
              className="text-sm text-gray-500 hover:text-gray-800 dark:hover:text-gray-300 cursor-pointer transition"
              title={darkMode ? "切换亮色模式" : "切换暗色模式"}
            >
              {darkMode ? "☀️" : "🌙"}
            </button>
            <button
              onClick={() => setSettingsOpen(true)}
              className="text-sm text-gray-500 hover:text-gray-800 dark:hover:text-gray-300 cursor-pointer transition"
              title="API 配置"
            >
              ⚙️
            </button>
            {view === "setup" && jobs.length > 0 && (
              <div className="relative group">
                <button className="text-sm text-gray-500 hover:text-gray-800 dark:hover:text-gray-300 cursor-pointer">
                  历史任务 ▾
                </button>
                <div className="absolute right-0 mt-2 w-64 bg-white dark:bg-gray-800 border border-gray-100 dark:border-gray-700 rounded-lg shadow-lg opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all z-50">
                  {jobs.map((j) => (
                    <div
                      key={j.id}
                      className="flex items-center px-4 py-3 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 border-b border-gray-50 dark:border-gray-700 last:border-0 transition group/item"
                    >
                      <button
                        onClick={() => handleSelectJob(j.id)}
                        className="flex-1 text-left min-w-0"
                      >
                        <div className="font-medium truncate">{j.theme}</div>
                        <div className="text-xs text-gray-400 mt-0.5">{j.status} · {j.created_at}</div>
                      </button>
                      <button
                        onClick={async (e) => {
                          e.stopPropagation();
                          if (confirm(`删除任务「${j.theme}」？\n此操作不可恢复。`)) {
                            try {
                              await api.deleteJob(j.id);
                              await loadJobs();
                            } catch (_) {}
                          }
                        }}
                        className="ml-2 opacity-0 group-hover/item:opacity-100 text-xs text-red-400 hover:text-red-600 transition cursor-pointer flex-shrink-0"
                        title="删除任务"
                      >
                        🗑️
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </header>

      {/* 键盘快捷键提示 */}
      <div className="fixed bottom-4 right-4 z-40">
        <div className="group">
          <button className="w-8 h-8 bg-white dark:bg-gray-700 border border-gray-200 dark:border-gray-600 rounded-full text-xs text-gray-400 shadow-sm hover:shadow cursor-pointer transition">
            ⌨️
          </button>
          <div className="absolute bottom-10 right-0 bg-white dark:bg-gray-800 border border-gray-100 dark:border-gray-700 rounded-lg shadow-lg p-3 text-xs opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all whitespace-nowrap">
            <div className="text-gray-600 dark:text-gray-300 mb-1 font-medium">快捷键</div>
            <div className="text-gray-400 dark:text-gray-500"><kbd className="bg-gray-100 dark:bg-gray-700 px-1 rounded">Ctrl+1</kbd> 回到首页</div>
            <div className="text-gray-400 dark:text-gray-500"><kbd className="bg-gray-100 dark:bg-gray-700 px-1 rounded">Ctrl+2</kbd> 暗色切换</div>
            <div className="text-gray-400 dark:text-gray-500"><kbd className="bg-gray-100 dark:bg-gray-700 px-1 rounded">Ctrl+O</kbd> API 配置</div>
          </div>
        </div>
      </div>

      {/* 主内容 */}
      {view === "setup" && (
        <SetupForm onJobCreated={handleJobCreated} />
      )}

      {view === "outline" && currentJobId && (
        <OutlineView
          jobId={currentJobId}
          outline={draftOutline}
          onConfirm={handleOutlineConfirm}
          onBack={handleBack}
        />
      )}

      {view === "progress" && currentJobId && (
        <ProgressPanel
          jobId={currentJobId}
          onBack={handleBack}
        />
      )}

      {/* API 配置弹窗 */}
      <SettingsModal
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        onConfigured={() => setLlmReady(true)}
      />
    </div>
  );
}