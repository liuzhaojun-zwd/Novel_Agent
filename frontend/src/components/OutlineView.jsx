import { useState, useEffect, useRef, useCallback } from "react";
import { api } from "../api";
import { useSSE } from "../hooks/useSSE";

export default function OutlineView({ jobId, onConfirm, outline: initialOutline, onBack }) {
  const [outline, setOutline] = useState(initialOutline || []);
  const [generating, setGenerating] = useState(false);
  const [loading, setLoading] = useState(false);
  const [modifyInstr, setModifyInstr] = useState("");
  const [modifyMsg, setModifyMsg] = useState("");
  const mountedRef = useRef(true);

  // 流式实时预览
  const [streamText, setStreamText] = useState("");
  const [streamProgress, setStreamProgress] = useState("");
  const [batchInfo, setBatchInfo] = useState(null); // {batch, total_batches, batch_start, batch_end}
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);

  const recoverPersistedOutline = useCallback(async (message = "") => {
    try {
      const job = await api.getJob(jobId);
      if (job.status !== "pending" || !job.outline?.length || !mountedRef.current) return false;
      setOutline(job.outline);
      setDirty(false);
      setGenerating(false);
      setStreamText("");
      setStreamProgress("");
      setBatchInfo(null);
      if (message) setModifyMsg(message);
      return true;
    } catch {
      return false;
    }
  }, [jobId]);

  useEffect(() => {
    mountedRef.current = true;
    const timer = window.setTimeout(() => {
      recoverPersistedOutline("✅ 已恢复保存的大纲");
    }, 0);
    return () => {
      window.clearTimeout(timer);
      mountedRef.current = false;
    };
  }, [recoverPersistedOutline]);

  // SSE 事件可能因断线或独立 Worker 丢失；生成期间以数据库状态兜底。
  useEffect(() => {
    if (!generating) return undefined;
    const timer = window.setInterval(() => {
      recoverPersistedOutline("✅ 大纲生成成功（已从数据库同步）");
    }, 3000);
    return () => window.clearInterval(timer);
  }, [generating, recoverPersistedOutline]);

  useEffect(() => {
    const warnBeforeUnload = (event) => {
      if (!dirty) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warnBeforeUnload);
    return () => window.removeEventListener("beforeunload", warnBeforeUnload);
  }, [dirty]);

  // SSE 监听大纲生成事件
  useSSE(jobId, (event, data) => {
    if (event === "initial_state") {
      if (data.outline_ready) {
        recoverPersistedOutline("✅ 大纲已生成并恢复");
      } else if (data.status === "generating_outline") {
        setGenerating(true);
        setStreamProgress("大纲正在生成中...");
      }
    } else if (event === "outline_progress") {
      setStreamProgress(data.message || "生成中...");
      setGenerating(true);
      if (data.batch) {
        setBatchInfo({ batch: data.batch, total: data.total_batches, start: data.batch_start, end: data.batch_end });
      }
    } else if (event === "outline_token") {
      if (data.accumulated !== undefined) setStreamText(data.accumulated);
      else setStreamText((current) => current + (data.text || ""));
    } else if (event === "outline_done") {
      setOutline(data.outline || []);
      setDirty(false);
      setGenerating(false);
      setStreamText("");
      setStreamProgress("");
      setBatchInfo(null);
      setModifyMsg("✅ " + (data.message || "大纲生成成功"));
    } else if (event === "outline_error") {
      setGenerating(false);
      setStreamText("");
      setStreamProgress("");
      setBatchInfo(null);
      setModifyMsg("❌ " + (data.message || data.error || "大纲生成失败"));
    }
  });

  const loadOutline = async () => {
    if (generating) return;
    setGenerating(true);
    setModifyMsg("");
    setStreamText("");
    setStreamProgress("正在请求 AI 生成大纲...");
    try {
      await api.generateOutline(jobId);
      // 返回后不代表完成，等待 SSE 事件
      setModifyMsg("大纲正在生成中...");
    } catch (err) {
      if (mountedRef.current) {
        setGenerating(false);
        if (err.message.includes("不允许")) {
          setModifyMsg("大纲正在生成中，请稍候...");
          setTimeout(() => {
            if (mountedRef.current && !outline.length) loadOutline();
          }, 8000);
        } else {
          setModifyMsg("❌ " + err.message);
        }
      }
    }
  };

  const handleModify = async () => {
    if (!modifyInstr.trim()) return;
    setLoading(true);
    setModifyMsg("");
    try {
      const data = await api.modifyOutline(jobId, modifyInstr);
      setOutline(data.outline);
      setDirty(false);
      setModifyMsg("✅ 大纲已更新并保存");
      setModifyInstr("");
    } catch (err) {
      setModifyMsg("❌ " + err.message);
    } finally {
      setLoading(false);
    }
  };

  const persistOutline = async () => {
    if (!outline.length) return false;
    setSaving(true);
    setModifyMsg("");
    try {
      const data = await api.saveOutline(jobId, outline);
      setOutline(data.outline);
      setDirty(false);
      setModifyMsg("✅ 大纲已保存");
      return true;
    } catch (err) {
      setModifyMsg("❌ 保存失败：" + err.message);
      return false;
    } finally {
      setSaving(false);
    }
  };

  const handleConfirm = async () => {
    setLoading(true);
    try {
      if (dirty && !(await persistOutline())) return;
      await api.confirmOutline(jobId);
      onConfirm();
    } catch (err) {
      setModifyMsg("❌ " + err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleBack = () => {
    if (dirty && !window.confirm("大纲还有未保存的修改，确定离开吗？")) return;
    onBack();
  };

  // 本地编辑某个章节
  const updateChapter = (idx, field, value) => {
    const updated = [...outline];
    updated[idx] = { ...updated[idx], [field]: value };
    setOutline(updated);
    setDirty(true);
  };

  const updateListField = (idx, field, value) => {
    updateChapter(idx, field, value.split(/[,，、]/).map((item) => item.trim()).filter(Boolean));
  };

  const updateScenes = (idx, value) => {
    const scenes = value.split("\n").map((line) => {
      const [goal = "", conflict = "", result = ""] = line.split("|").map((item) => item.trim());
      return { goal, conflict, result };
    }).filter((scene) => scene.goal || scene.conflict || scene.result);
    updateChapter(idx, "scenes", scenes);
  };

  return (
    <div className="max-w-4xl mx-auto py-8 px-4">
      <div className="flex items-center justify-between mb-6">
        <div>
          <button onClick={handleBack} className="text-sm text-indigo-600 hover:text-indigo-800 cursor-pointer">
            ← 返回任务列表
          </button>
          <h2 className="text-xl font-bold text-gray-900 mt-1">📋 作品大纲</h2>
        </div>
        <div className="flex items-center gap-2">
          {outline.length > 0 && (
            <span className={`text-xs px-2 py-1 rounded-full ${dirty ? "bg-amber-50 text-amber-700" : "bg-emerald-50 text-emerald-700"}`}>
              {saving ? "保存中..." : dirty ? "● 未保存" : "✓ 已保存"}
            </span>
          )}
          <button
            onClick={loadOutline}
            disabled={generating || saving}
            className="px-4 py-2 text-sm border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
          >
            {generating ? "⏳ 生成中..." : "🔄 生成大纲"}
          </button>
          <button
            onClick={persistOutline}
            disabled={loading || saving || generating || !dirty}
            className="px-4 py-2 text-sm border border-indigo-200 text-indigo-700 rounded-lg hover:bg-indigo-50 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
          >
            {saving ? "保存中..." : "💾 保存大纲"}
          </button>
          <button
            onClick={handleConfirm}
            disabled={loading || saving || generating || outline.length === 0}
            className="px-5 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-400 text-white text-sm rounded-lg font-medium transition cursor-pointer"
          >
            {loading ? "处理中..." : "✅ 确认大纲，开始写正文"}
          </button>
        </div>
      </div>

      {/* 流式生成预览 */}
      {generating && (
        <div className="bg-blue-50 border border-blue-100 rounded-xl p-5 mb-6">
          <div className="flex items-center gap-2 mb-2">
            <span className="w-2 h-2 bg-blue-500 rounded-full animate-ping" />
            <span className="text-sm font-medium text-blue-700">大纲生成中</span>
            {batchInfo && (
              <span className="text-xs bg-blue-100 text-blue-600 px-2 py-0.5 rounded-full">
                第 {batchInfo.batch}/{batchInfo.total} 批（{batchInfo.start}-{batchInfo.end}章）
              </span>
            )}
            <span className="text-xs text-blue-400">{streamProgress}</span>
          </div>
          {/* 批次进度条 */}
          {batchInfo && batchInfo.total > 1 && (
            <div className="w-full bg-blue-100 rounded-full h-1.5 mb-3 overflow-hidden">
              <div
                className="bg-blue-500 h-full rounded-full transition-all duration-500"
                style={{ width: `${(batchInfo.batch / batchInfo.total) * 100}%` }}
              />
            </div>
          )}
          {streamText && (
            <div className="bg-white rounded-lg p-3 text-xs text-gray-500 font-mono max-h-32 overflow-y-auto whitespace-pre-wrap break-all leading-relaxed">
              {streamText}
            </div>
          )}
          {!streamText && (
            <div className="text-sm text-blue-400">
              <div className="flex items-center gap-1">
                <span>AI 正在构思中</span>
                <span className="animate-bounce">...</span>
              </div>
            </div>
          )}
        </div>
      )}

      {/* 章节列表 */}
      <div className="space-y-3">
        {outline.map((ch, i) => (
          <div
            key={ch.chapter_number}
            className="bg-white rounded-lg border border-gray-100 p-4 hover:shadow-sm transition"
          >
            <div className="flex items-start gap-3">
              <span className="text-indigo-600 font-bold text-lg min-w-[2.5rem] pt-0.5">
                #{ch.chapter_number}
              </span>
              <div className="flex-1 min-w-0">
                <input
                  value={ch.title}
                  onChange={(e) => updateChapter(i, "title", e.target.value)}
                  className="w-full font-medium text-gray-900 dark:text-gray-100 bg-transparent border-b border-transparent hover:border-gray-200 focus:border-indigo-500 outline-none transition"
                />
                <textarea
                  value={ch.summary}
                  onChange={(e) => updateChapter(i, "summary", e.target.value)}
                  rows={2}
                  className="w-full mt-1 text-sm text-gray-500 dark:text-gray-400 bg-transparent border border-transparent hover:border-gray-100 focus:border-indigo-200 rounded outline-none transition resize-none p-1"
                />
                <details className="mt-2 text-sm">
                  <summary className="cursor-pointer text-indigo-600 select-none">
                    结构化章节卡
                    {ch.pov_character && <span className="ml-2 text-xs text-gray-400">POV：{ch.pov_character}</span>}
                  </summary>
                  <div className="mt-3 grid md:grid-cols-2 gap-3 rounded-lg bg-gray-50 dark:bg-gray-800 p-3">
                    <input value={ch.pov_character || ""} onChange={(e) => updateChapter(i, "pov_character", e.target.value)} placeholder="POV 人物" className="px-3 py-2 border rounded-lg dark:bg-gray-700 dark:border-gray-600" />
                    <input value={ch.location || ""} onChange={(e) => updateChapter(i, "location", e.target.value)} placeholder="主要地点" className="px-3 py-2 border rounded-lg dark:bg-gray-700 dark:border-gray-600" />
                    {[
                      ["chapter_goal", "本章目标"], ["conflict", "核心冲突"],
                      ["turning_point", "关键转折"], ["ending_hook", "结尾钩子"],
                    ].map(([field, label]) => <textarea key={field} value={ch[field] || ""} onChange={(e) => updateChapter(i, field, e.target.value)} rows={2} placeholder={label} className="px-3 py-2 border rounded-lg resize-y dark:bg-gray-700 dark:border-gray-600" />)}
                    <input value={(ch.characters || []).join("、")} onChange={(e) => updateListField(i, "characters", e.target.value)} placeholder="出场人物，使用逗号分隔" className="px-3 py-2 border rounded-lg dark:bg-gray-700 dark:border-gray-600" />
                    <input value={(ch.foreshadowing_add || []).join("、")} onChange={(e) => updateListField(i, "foreshadowing_add", e.target.value)} placeholder="本章埋下的伏笔" className="px-3 py-2 border rounded-lg dark:bg-gray-700 dark:border-gray-600" />
                    <input value={(ch.foreshadowing_resolve || []).join("、")} onChange={(e) => updateListField(i, "foreshadowing_resolve", e.target.value)} placeholder="本章回收的伏笔" className="px-3 py-2 border rounded-lg dark:bg-gray-700 dark:border-gray-600" />
                    <textarea
                      value={(ch.scenes || []).map((scene) => `${scene.goal || ""} | ${scene.conflict || ""} | ${scene.result || ""}`).join("\n")}
                      onChange={(e) => updateScenes(i, e.target.value)} rows={3}
                      placeholder="场景规划：目标 | 冲突 | 结果（每行一个场景）"
                      className="md:col-span-2 px-3 py-2 border rounded-lg resize-y dark:bg-gray-700 dark:border-gray-600"
                    />
                  </div>
                </details>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* 修改指令 */}
      <div className="mt-6 bg-white rounded-lg border border-gray-100 p-4">
        <label className="block text-sm font-medium text-gray-700 mb-2">
          自然语言修改指令
        </label>
        <div className="flex gap-2">
          <input
            value={modifyInstr}
            onChange={(e) => setModifyInstr(e.target.value)}
            placeholder='如："把第3章标题改为暗流涌动"'
            className="flex-1 px-3 py-2 border border-gray-200 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent outline-none transition"
            onKeyDown={(e) => e.key === "Enter" && handleModify()}
          />
          <button
            onClick={handleModify}
            disabled={loading || !modifyInstr.trim()}
            className="px-4 py-2 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-50 transition cursor-pointer"
          >
            执行
          </button>
        </div>
        {modifyMsg && (
          <p className="mt-2 text-sm text-gray-600">{modifyMsg}</p>
        )}
        <p className="mt-2 text-xs text-gray-400">
          支持指令示例："第3章标题改为xxx"、"重写第5章摘要为xxx"
        </p>
      </div>
    </div>
  );
}