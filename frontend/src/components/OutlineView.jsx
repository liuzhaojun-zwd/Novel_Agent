import { useState, useEffect, useRef } from "react";
import { api } from "../api";

export default function OutlineView({ jobId, onConfirm, outline: initialOutline, onBack }) {
  const [outline, setOutline] = useState(initialOutline || []);
  const [generating, setGenerating] = useState(false);
  const [loading, setLoading] = useState(false);
  const [modifyInstr, setModifyInstr] = useState("");
  const [modifyMsg, setModifyMsg] = useState("");
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    if (!initialOutline && jobId && !generating) {
      loadOutline();
    }
    return () => { mountedRef.current = false; };
  }, [jobId]);

  const loadOutline = async () => {
    if (generating) return;
    setGenerating(true);
    setModifyMsg("");
    try {
      const data = await api.generateOutline(jobId);
      if (mountedRef.current) {
        setOutline(data.outline);
        setModifyMsg("✅ 大纲生成成功");
      }
    } catch (err) {
      if (mountedRef.current) {
        // 如果是因为正在生成中，稍等后自动重试一次
        if (err.message.includes("不允许")) {
          setModifyMsg("大纲正在生成中，请稍候...");
          setTimeout(() => {
            if (mountedRef.current && !outline.length) loadOutline();
          }, 8000);
        } else {
          setModifyMsg("❌ " + err.message);
        }
      }
    } finally {
      if (mountedRef.current) setGenerating(false);
    }
  };

  const handleModify = async () => {
    if (!modifyInstr.trim()) return;
    setLoading(true);
    setModifyMsg("");
    try {
      const data = await api.modifyOutline(jobId, modifyInstr);
      setOutline(data.outline);
      setModifyMsg("✅ 大纲已更新");
      setModifyInstr("");
    } catch (err) {
      setModifyMsg("❌ " + err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleConfirm = async () => {
    setLoading(true);
    try {
      await api.confirmOutline(jobId);
      onConfirm();
    } catch (err) {
      setModifyMsg("❌ " + err.message);
    } finally {
      setLoading(false);
    }
  };

  // 本地编辑某个章节
  const updateChapter = (idx, field, value) => {
    const updated = [...outline];
    updated[idx] = { ...updated[idx], [field]: value };
    setOutline(updated);
  };

  return (
    <div className="max-w-4xl mx-auto py-8 px-4">
      <div className="flex items-center justify-between mb-6">
        <div>
          <button onClick={onBack} className="text-sm text-indigo-600 hover:text-indigo-800 cursor-pointer">
            ← 返回任务列表
          </button>
          <h2 className="text-xl font-bold text-gray-900 mt-1">📋 作品大纲</h2>
        </div>
        <div className="flex gap-2">
          <button
            onClick={loadOutline}
            disabled={generating}
            className="px-4 py-2 text-sm border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
          >
            {generating ? "⏳ 生成中..." : "🔄 重新生成"}
          </button>
          <button
            onClick={handleConfirm}
            disabled={loading || generating || outline.length === 0}
            className="px-5 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-400 text-white text-sm rounded-lg font-medium transition cursor-pointer"
          >
            {loading ? "处理中..." : "✅ 确认大纲，开始写正文"}
          </button>
        </div>
      </div>

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
                  className="w-full font-medium text-gray-900 bg-transparent border-b border-transparent hover:border-gray-200 focus:border-indigo-500 outline-none transition"
                />
                <textarea
                  value={ch.summary}
                  onChange={(e) => updateChapter(i, "summary", e.target.value)}
                  rows={2}
                  className="w-full mt-1 text-sm text-gray-500 bg-transparent border border-transparent hover:border-gray-100 focus:border-indigo-200 rounded outline-none transition resize-none p-1"
                />
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
          支持指令示例："第3章标题改为xxx"、"重写第5章摘要为xxx"、"把第4章标题改为xxx，摘要改为xxx"
        </p>
      </div>
    </div>
  );
}