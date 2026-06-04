import { useState, useEffect } from "react";
import SetupForm from "./components/SetupForm";
import OutlineView from "./components/OutlineView";
import ProgressPanel from "./components/ProgressPanel";
import SettingsModal from "./components/SettingsModal";
import { api } from "./api";

export default function App() {
  const [view, setView] = useState("setup"); // setup | outline | progress
  const [currentJobId, setCurrentJobId] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [draftOutline, setDraftOutline] = useState(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [llmReady, setLlmReady] = useState(false);

  // 启动时检查 API Key 是否已配
  useEffect(() => {
    api.checkSetupStatus().then((s) => {
      if (!s.llm_configured) {
        setSettingsOpen(true);
      } else {
        setLlmReady(true);
      }
    }).catch(() => setLlmReady(true));
    loadJobs();
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

  const handleBack = () => {
    setView("setup");
    setCurrentJobId(null);
    setDraftOutline(null);
    loadJobs();
  };

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

  return (
    <div className="min-h-screen bg-gray-50">
      {/* 顶部导航 */}
      <header className="bg-white border-b border-gray-100">
        <div className="max-w-4xl mx-auto px-4 h-14 flex items-center justify-between">
          <div
            className="flex items-center gap-2 cursor-pointer"
            onClick={() => { setView("setup"); setCurrentJobId(null); }}
          >
            <span className="font-bold text-gray-900">Novel_Agent</span>
            <span className="text-xs text-gray-400 bg-gray-100 px-2 py-0.5 rounded-full">小说创作</span>
          </div>
          <div className="flex items-center gap-3">
            {!llmReady && (
              <span className="text-xs text-amber-500">⚠️ 未配置 API</span>
            )}
            <button
              onClick={() => setSettingsOpen(true)}
              className="text-sm text-gray-500 hover:text-gray-800 cursor-pointer"
              title="API 配置"
            >
              ⚙️
            </button>
            {view === "setup" && jobs.length > 0 && (
              <div className="relative group">
                <button className="text-sm text-gray-500 hover:text-gray-800 cursor-pointer">
                  历史任务 ▾
                </button>
                <div className="absolute right-0 mt-2 w-64 bg-white border border-gray-100 rounded-lg shadow-lg opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all z-50">
                  {jobs.map((j) => (
                    <button
                      key={j.id}
                      onClick={() => handleSelectJob(j.id)}
                      className="w-full text-left px-4 py-3 text-sm text-gray-700 hover:bg-gray-50 border-b border-gray-50 last:border-0 transition cursor-pointer"
                    >
                      <div className="font-medium truncate">{j.theme}</div>
                      <div className="text-xs text-gray-400 mt-0.5">{j.status} · {j.created_at}</div>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </header>

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