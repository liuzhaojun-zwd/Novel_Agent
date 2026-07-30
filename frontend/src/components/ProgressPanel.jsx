import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { useSSE } from "../hooks/useSSE";
import { EditorialReview, LocalRewritePanel } from "./EditorialTools";
import MemoryPanel from "./MemoryPanel";
import VersionPanel from "./VersionPanel";

const STAGES = {
  planning: "章节规划",
  scene: "场景写作",
  polishing: "合并润色",
  chapter_complete: "章节收尾",
  completed: "已完成",
};

function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) return "待估算";
  if (seconds < 60) return `${seconds} 秒`;
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.ceil((seconds % 3600) / 60);
  return hours ? `${hours} 小时 ${minutes} 分` : `${minutes} 分钟`;
}

function Metric({ label, value, title }) {
  return <div className="min-w-0 rounded-lg bg-gray-50 px-3 py-2 dark:bg-gray-900/60" title={title}>
    <dt className="text-[11px] text-gray-400">{label}</dt>
    <dd className="truncate text-sm font-semibold text-gray-700 dark:text-gray-200">{value}</dd>
  </div>;
}

export default function ProgressPanel({ jobId, onBack }) {
  const [job, setJob] = useState(null);
  const [chapters, setChapters] = useState([]);
  const [selectedNumber, setSelectedNumber] = useState(null);
  const [editContent, setEditContent] = useState("");
  const [savedContent, setSavedContent] = useState("");
  const [generationState, setGenerationState] = useState(null);
  const [generationMode, setGenerationMode] = useState("auto");
  const [targetMode, setTargetMode] = useState("all");
  const [targetChapter, setTargetChapter] = useState(1);
  const [statusText, setStatusText] = useState("");
  const [liveText, setLiveText] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [assistantTab, setAssistantTab] = useState("tools");
  const [versionResource, setVersionResource] = useState("chapter");
  const [versionNonce, setVersionNonce] = useState(0);
  const [rewriteInstruction, setRewriteInstruction] = useState("");
  const [mobilePane, setMobilePane] = useState("editor");
  const editorRef = useRef(null);

  const selected = useMemo(
    () => chapters.find((item) => item.chapter_number === selectedNumber) || null,
    [chapters, selectedNumber],
  );
  const dirty = Boolean(selected && editContent !== savedContent);

  const loadJob = useCallback(async () => {
    const result = await api.getJob(jobId);
    setJob(result);
    setTargetChapter((value) => Math.max(Number(value) || 1, Math.min(result.chapter_count, result.current_chapter + 1)));
    return result;
  }, [jobId]);

  const loadChapters = useCallback(async (preferredNumber = null) => {
    const result = await api.getChapters(jobId);
    setChapters(result);
    const number = preferredNumber ?? selectedNumber ?? result.find((item) => item.status === "completed")?.chapter_number ?? result[0]?.chapter_number;
    const chapter = result.find((item) => item.chapter_number === number) || result[0] || null;
    if (chapter) {
      setSelectedNumber(chapter.chapter_number);
      setEditContent(chapter.content || "");
      setSavedContent(chapter.content || "");
    }
    return result;
  }, [jobId, selectedNumber]);

  const loadGenerationState = useCallback(async () => {
    const result = await api.getGenerationState(jobId);
    setGenerationState(result);
    if (result.run?.generation_mode) setGenerationMode(result.run.generation_mode);
    return result;
  }, [jobId]);

  const refresh = useCallback(async (preferredNumber = null) => {
    setError("");
    try {
      await Promise.all([loadJob(), loadChapters(preferredNumber), loadGenerationState()]);
    } catch (err) {
      setError(err.message);
    }
  }, [loadJob, loadChapters, loadGenerationState]);

  useEffect(() => {
    const timer = window.setTimeout(() => refresh(), 0);
    return () => window.clearTimeout(timer);
  }, [refresh]);

  useEffect(() => {
    if (job?.status !== "generating_chapters") return undefined;
    const timer = window.setInterval(() => loadGenerationState().catch(() => {}), 5000);
    return () => window.clearInterval(timer);
  }, [job?.status, loadGenerationState]);

  useEffect(() => {
    const beforeUnload = (event) => {
      if (!dirty) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, [dirty]);

  const saveChapter = useCallback(async () => {
    if (!selected || !dirty || busy) return;
    setBusy("save");
    setError("");
    try {
      await api.updateChapter(jobId, selected.chapter_number, editContent);
      setSavedContent(editContent);
      setNotice("正文已保存并创建版本");
      setVersionNonce((value) => value + 1);
      await loadChapters(selected.chapter_number);
    } catch (err) {
      setError(`保存失败：${err.message}`);
    } finally {
      setBusy("");
    }
  }, [busy, dirty, editContent, jobId, loadChapters, selected]);

  useEffect(() => {
    const keydown = (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        saveChapter();
      }
    };
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
  }, [saveChapter]);

  const chooseChapter = (chapter) => {
    if (dirty && !window.confirm("当前正文尚未保存，确定切换章节并放弃修改吗？")) return;
    setSelectedNumber(chapter.chapter_number);
    setEditContent(chapter.content || "");
    setSavedContent(chapter.content || "");
    setError("");
    setMobilePane("editor");
  };

  const handlePatchApplied = async (result) => {
    setEditContent(result.content);
    setSavedContent(result.content);
    setVersionNonce((value) => value + 1);
    await loadChapters(selected.chapter_number);
  };

  const regenerate = async () => {
    if (!selected || busy) return;
    if (dirty && !window.confirm("AI 重写会覆盖未保存修改，是否继续？")) return;
    setBusy("rewrite");
    setError("");
    try {
      const result = await api.regenerateChapter(jobId, selected.chapter_number, rewriteInstruction);
      setEditContent(result.content || "");
      setSavedContent(result.content || "");
      setRewriteInstruction("");
      setVersionNonce((value) => value + 1);
      await loadChapters(selected.chapter_number);
      setNotice("AI 重写完成，原正文已保留在版本历史中");
    } catch (err) {
      setError(`重写失败：${err.message}`);
    } finally {
      setBusy("");
    }
  };

  const startGeneration = async (resume = false) => {
    if (!job || busy) return;
    const number = Math.max(1, Math.min(job.chapter_count, Number(targetChapter) || 1));
    const options = { mode: generationMode };
    let upTo;
    if (targetMode === "single") options.chapter = number;
    if (targetMode === "up_to") upTo = number;
    setBusy("generation");
    setError("");
    try {
      if (resume) await api.resumeGeneration(jobId, upTo, options);
      else await api.startGeneration(jobId, upTo, options);
      await refresh();
    } catch (err) {
      setError(`${resume ? "恢复" : "启动"}失败：${err.message}`);
    } finally {
      setBusy("");
    }
  };

  const controlGeneration = async (action) => {
    if (busy) return;
    setBusy(action);
    setError("");
    try {
      const result = action === "pause" ? await api.pauseGeneration(jobId) : await api.cancelGeneration(jobId);
      setStatusText(result.message);
      await refresh();
    } catch (err) {
      setError(`${action === "pause" ? "暂停" : "取消"}失败：${err.message}`);
    } finally {
      setBusy("");
    }
  };

  const exportBook = (format) => {
    const link = document.createElement("a");
    link.href = api.getExportUrl(jobId, format);
    link.click();
    setNotice(`已开始导出 ${format.toUpperCase()}`);
  };

  useSSE(jobId, (event, data) => {
    if (event === "initial_state") {
      setStatusText(data.status || "");
      return;
    }
    if (["progress", "scene_progress", "control_state"].includes(event)) {
      setStatusText(data.message || data.state || "生成中");
      loadGenerationState().catch(() => {});
    }
    if (event === "token") setLiveText(data.accumulated || "");
    if (["chapter_complete", "batch_complete", "job_complete"].includes(event)) {
      setLiveText("");
      refresh(selectedNumber);
      setVersionNonce((value) => value + 1);
    }
    if (event === "error") {
      setError(data.error || "生成失败，可从 checkpoint 恢复");
      refresh(selectedNumber);
    }
  });

  const handleRestored = async () => {
    await refresh(selectedNumber);
    setVersionNonce((value) => value + 1);
    setNotice("版本已恢复，恢复前内容已自动备份");
  };

  const metrics = generationState?.metrics || {};
  const completed = chapters.filter((item) => item.status === "completed").length;
  const total = job?.chapter_count || 0;
  const progress = total ? Math.round((completed / total) * 100) : 0;
  const isGenerating = job?.status === "generating_chapters";
  const canStart = job?.status === "pending" && job?.outline;
  const canResume = ["paused", "failed"].includes(job?.status);
  const versionKey = versionResource === "chapter" ? String(selectedNumber || "") : "";

  if (!job) return <div role="status" className="grid min-h-[60vh] place-items-center text-gray-400">正在加载创作工作台…</div>;

  return <main className="mx-auto w-full max-w-[1600px] px-3 py-4 sm:px-5" aria-label="小说创作工作台">
    <div aria-live="polite" className="sr-only">{notice}</div>
    <header className="mb-4 rounded-2xl border border-gray-100 bg-white p-4 shadow-sm dark:border-gray-700 dark:bg-gray-800">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <button type="button" onClick={onBack} aria-label="返回任务列表" className="mt-0.5 rounded-lg p-2 text-gray-400 hover:bg-gray-100 focus-visible:outline-2 focus-visible:outline-indigo-500 dark:hover:bg-gray-700">←</button>
          <div><h1 className="text-lg font-bold text-gray-900 dark:text-white">{job.theme}</h1><p className="max-w-2xl text-sm text-gray-500 dark:text-gray-400">{job.topic}</p></div>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={() => exportBook("md")} disabled={!completed} className="rounded-lg border border-gray-200 px-3 py-2 text-xs disabled:opacity-40 dark:border-gray-600">导出 MD</button>
          <button type="button" onClick={() => exportBook("txt")} disabled={!completed} className="rounded-lg border border-gray-200 px-3 py-2 text-xs disabled:opacity-40 dark:border-gray-600">导出 TXT</button>
        </div>
      </div>
      <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-gray-100 dark:bg-gray-700" aria-label={`全书进度 ${progress}%`} role="progressbar" aria-valuenow={progress} aria-valuemin="0" aria-valuemax="100"><div className="h-full rounded-full bg-indigo-600 transition-all" style={{ width: `${progress}%` }} /></div>
      <dl className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        <Metric label="全书进度" value={`${completed}/${total} 章 · ${progress}%`} />
        <Metric label="生成阶段" value={STAGES[generationState?.run?.stage] || statusText || job.status} />
        <Metric label="预计剩余" value={formatDuration(metrics.eta_seconds)} />
        <Metric label="运行耗时" value={formatDuration(metrics.elapsed_seconds || 0)} />
        <Metric label="Token（估算）" value={(metrics.total_tokens || 0).toLocaleString()} title={metrics.pricing_note} />
        <Metric label="费用（估算）" value={`$${(metrics.cost_usd || 0).toFixed(4)}`} title={metrics.pricing_note} />
      </dl>
    </header>

    {(canStart || canResume || isGenerating) && <section aria-label="生成控制" className="mb-4 flex flex-wrap items-end gap-2 rounded-xl border border-gray-100 bg-white p-3 dark:border-gray-700 dark:bg-gray-800">
      {!isGenerating && <>
        <label className="text-xs text-gray-500">模式<select value={generationMode} onChange={(event) => setGenerationMode(event.target.value)} className="mt-1 block rounded-lg border border-gray-200 bg-white px-2 py-2 text-sm dark:border-gray-600 dark:bg-gray-900"><option value="auto">全自动</option><option value="collaborative">逐章协作</option></select></label>
        <label className="text-xs text-gray-500">范围<select value={targetMode} onChange={(event) => setTargetMode(event.target.value)} className="mt-1 block rounded-lg border border-gray-200 bg-white px-2 py-2 text-sm dark:border-gray-600 dark:bg-gray-900"><option value="all">剩余全部</option><option value="up_to">生成到第 N 章</option><option value="single">仅单章</option></select></label>
        {targetMode !== "all" && <label className="text-xs text-gray-500">章节<input type="number" min="1" max={total} value={targetChapter} onChange={(event) => setTargetChapter(event.target.value)} className="mt-1 block w-20 rounded-lg border border-gray-200 bg-white px-2 py-2 text-sm dark:border-gray-600 dark:bg-gray-900" /></label>}
        <button type="button" onClick={() => startGeneration(canResume)} disabled={busy === "generation"} className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50">{busy === "generation" ? "启动中…" : canResume ? "恢复生成" : "开始生成"}</button>
      </>}
      {isGenerating && <><button type="button" onClick={() => controlGeneration("pause")} disabled={Boolean(busy)} className="rounded-lg bg-amber-500 px-4 py-2 text-sm text-white disabled:opacity-50">暂停</button><button type="button" onClick={() => controlGeneration("cancel")} disabled={Boolean(busy)} className="rounded-lg bg-red-500 px-4 py-2 text-sm text-white disabled:opacity-50">取消</button><span className="self-center text-xs text-blue-600 dark:text-blue-300">{statusText || "场景级生成进行中"}</span></>}
    </section>}

    {error && <div role="alert" className="mb-4 flex items-start justify-between gap-3 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300"><span>{error}</span><button type="button" aria-label="关闭错误提示" onClick={() => setError("")}>✕</button></div>}
    {notice && <div role="status" className="mb-4 rounded-xl border border-green-200 bg-green-50 p-3 text-sm text-green-700 dark:border-green-900 dark:bg-green-950/30 dark:text-green-300">{notice}</div>}

    <nav className="mb-3 grid grid-cols-3 rounded-xl bg-gray-100 p-1 lg:hidden dark:bg-gray-800" aria-label="移动端工作台面板">
      {[["tree", "章节"], ["editor", "正文"], ["assistant", "助手"]].map(([value, label]) => <button key={value} type="button" onClick={() => setMobilePane(value)} aria-current={mobilePane === value ? "page" : undefined} className={`rounded-lg px-3 py-2 text-sm ${mobilePane === value ? "bg-white font-medium text-indigo-600 shadow-sm dark:bg-gray-700 dark:text-indigo-300" : "text-gray-500"}`}>{label}</button>)}
    </nav>

    <div className="grid min-h-[68vh] grid-cols-1 gap-3 lg:grid-cols-[260px_minmax(420px,1fr)_340px]">
      <aside className={`${mobilePane === "tree" ? "block" : "hidden"} min-h-0 rounded-2xl border border-gray-100 bg-white p-3 lg:block dark:border-gray-700 dark:bg-gray-800`} aria-label="章节树">
        <div className="mb-3 flex items-center justify-between"><h2 className="text-sm font-semibold text-gray-800 dark:text-gray-100">章节树</h2><span className="text-xs text-gray-400">{completed}/{total}</span></div>
        {chapters.length === 0 ? <div className="rounded-xl border border-dashed border-gray-200 p-6 text-center text-sm text-gray-400 dark:border-gray-700"><div className="mb-2 text-2xl">🌱</div>大纲确认后，章节会显示在这里</div> : <ol className="max-h-[62vh] space-y-1 overflow-y-auto pr-1">
          {chapters.map((chapter) => <li key={chapter.chapter_number}><button type="button" onClick={() => chooseChapter(chapter)} aria-current={selectedNumber === chapter.chapter_number ? "true" : undefined} className={`w-full rounded-lg px-3 py-2.5 text-left transition focus-visible:outline-2 focus-visible:outline-indigo-500 ${selectedNumber === chapter.chapter_number ? "bg-indigo-50 text-indigo-800 dark:bg-indigo-950/50 dark:text-indigo-200" : "hover:bg-gray-50 dark:hover:bg-gray-700"}`}><span className="flex items-center justify-between gap-2"><span className="truncate text-sm font-medium">{chapter.chapter_number}. {chapter.title}</span><span aria-label={chapter.status === "completed" ? "已完成" : "待生成"} className={chapter.status === "completed" ? "text-green-500" : "text-gray-300"}>{chapter.status === "completed" ? "●" : "○"}</span></span><span className="mt-0.5 block text-[11px] text-gray-400">{chapter.word_count?.toLocaleString() || 0} 字</span></button></li>)}
        </ol>}
      </aside>

      <section className={`${mobilePane === "editor" ? "flex" : "hidden"} min-h-0 flex-col rounded-2xl border border-gray-100 bg-white lg:flex dark:border-gray-700 dark:bg-gray-800`} aria-label="正文编辑器">
        {selected ? <>
          <header className="flex flex-wrap items-center justify-between gap-2 border-b border-gray-100 px-4 py-3 dark:border-gray-700">
            <div className="min-w-0"><h2 className="truncate font-semibold text-gray-900 dark:text-white">第 {selected.chapter_number} 章 · {selected.title}</h2><p className="text-xs text-gray-400">{editContent.replace(/\s/g, "").length.toLocaleString()} 字 · {dirty ? "有未保存修改" : "已保存"}</p></div>
            <div className="flex items-center gap-2"><button type="button" onClick={() => { setEditContent(savedContent); setError(""); }} disabled={!dirty || Boolean(busy)} className="rounded-lg border border-gray-200 px-3 py-1.5 text-xs disabled:opacity-40 dark:border-gray-600">放弃修改</button><button type="button" onClick={saveChapter} disabled={!dirty || Boolean(busy)} className="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-40">{busy === "save" ? "保存中…" : "保存 Ctrl+S"}</button></div>
          </header>
          {isGenerating && liveText && selected.chapter_number === (generationState?.run?.current_chapter || selected.chapter_number) ? <div className="border-b border-blue-100 bg-blue-50 p-3 text-xs text-blue-700 dark:border-blue-900 dark:bg-blue-950/30 dark:text-blue-300">实时生成预览已更新，章节完成后会载入编辑器。</div> : null}
          <textarea ref={editorRef} value={editContent} onChange={(event) => setEditContent(event.target.value)} disabled={selected.status !== "completed" && !editContent} aria-label={`第${selected.chapter_number}章正文`} placeholder={selected.status === "completed" ? "在这里开始编辑正文…" : "本章尚未生成"} className="min-h-[58vh] flex-1 resize-none bg-transparent p-5 font-serif text-[15px] leading-8 text-gray-800 outline-none placeholder:text-gray-300 disabled:cursor-not-allowed dark:text-gray-100" />
        </> : <div className="grid flex-1 place-items-center p-8 text-center text-gray-400"><div><div className="mb-3 text-4xl">📖</div><p>从章节树选择一章开始创作</p><p className="mt-1 text-xs">正文、保存状态和版本会集中显示在这里</p></div></div>}
      </section>

      <aside className={`${mobilePane === "assistant" ? "block" : "hidden"} min-h-0 rounded-2xl border border-gray-100 bg-white lg:block dark:border-gray-700 dark:bg-gray-800`} aria-label="创作助手">
        <div className="grid grid-cols-2 border-b border-gray-100 p-1 dark:border-gray-700" role="tablist" aria-label="创作助手功能">
          <button type="button" role="tab" aria-selected={assistantTab === "tools"} onClick={() => setAssistantTab("tools")} className={`rounded-lg px-3 py-2 text-sm ${assistantTab === "tools" ? "bg-indigo-50 font-medium text-indigo-700 dark:bg-indigo-950/50 dark:text-indigo-200" : "text-gray-500"}`}>AI 助手</button>
          <button type="button" role="tab" aria-selected={assistantTab === "versions"} onClick={() => setAssistantTab("versions")} className={`rounded-lg px-3 py-2 text-sm ${assistantTab === "versions" ? "bg-indigo-50 font-medium text-indigo-700 dark:bg-indigo-950/50 dark:text-indigo-200" : "text-gray-500"}`}>版本历史</button>
        </div>
        <div className="max-h-[65vh] overflow-y-auto p-4">
          {assistantTab === "tools" && (selected?.status === "completed" ? <div className="space-y-5">
            <section><h3 className="text-sm font-semibold text-gray-800 dark:text-gray-100">整章重写</h3><p className="mb-2 text-xs text-gray-400">原正文会自动保留为历史版本</p><textarea value={rewriteInstruction} onChange={(event) => setRewriteInstruction(event.target.value)} placeholder="例如：加快节奏，强化人物冲突" className="h-20 w-full resize-none rounded-lg border border-gray-200 bg-transparent p-2 text-sm dark:border-gray-600" /><button type="button" onClick={regenerate} disabled={Boolean(busy)} className="mt-2 w-full rounded-lg bg-purple-600 px-3 py-2 text-sm text-white disabled:opacity-50">{busy === "rewrite" ? "重写中…" : "AI 重写本章"}</button></section>
            <LocalRewritePanel jobId={jobId} chapterNumber={selected.chapter_number} content={editContent} textareaRef={editorRef} onApplied={handlePatchApplied} />
            <EditorialReview key={`review-${selected.chapter_number}-${versionNonce}`} jobId={jobId} chapterNumber={selected.chapter_number} />
          </div> : <div className="rounded-xl border border-dashed border-gray-200 p-6 text-center text-sm text-gray-400 dark:border-gray-700">选择已完成章节后，可使用局部修复、整章重写和语义审稿</div>)}
          {assistantTab === "versions" && <div>
            <div className="mb-4 grid grid-cols-3 rounded-lg bg-gray-100 p-1 dark:bg-gray-900" aria-label="版本资源类型">
              {[["chapter", "正文"], ["outline", "大纲"], ["settings", "设定"]].map(([value, label]) => <button key={value} type="button" onClick={() => setVersionResource(value)} disabled={value === "chapter" && !selectedNumber} className={`rounded-md px-2 py-1.5 text-xs disabled:opacity-40 ${versionResource === value ? "bg-white font-medium text-indigo-600 shadow-sm dark:bg-gray-700 dark:text-indigo-300" : "text-gray-500"}`}>{label}</button>)}
            </div>
            <VersionPanel key={`${versionResource}-${versionKey}-${versionNonce}`} jobId={jobId} resourceType={versionResource} resourceKey={versionKey} onRestored={handleRestored} />
          </div>}
        </div>
      </aside>
    </div>

    {liveText && isGenerating && <section className="mt-4 rounded-xl border border-blue-100 bg-blue-50 p-4 dark:border-blue-900 dark:bg-blue-950/30" aria-live="polite"><h2 className="mb-2 text-sm font-semibold text-blue-700 dark:text-blue-300">实时写作预览</h2><div className="max-h-48 overflow-y-auto whitespace-pre-wrap text-sm leading-7 text-gray-700 dark:text-gray-200">{liveText}</div></section>}
    <MemoryPanel jobId={jobId} />
  </main>;
}