import { useState } from "react";
import { api } from "../api";

const DIMENSIONS = {
  plot: "剧情", character: "人物", continuity: "连续性", pacing: "节奏", technical: "规则",
};
const SEVERITY = {
  critical: ["致命", "bg-red-100 text-red-700"],
  high: ["严重", "bg-orange-100 text-orange-700"],
  medium: ["中等", "bg-yellow-100 text-yellow-700"],
  low: ["轻微", "bg-blue-100 text-blue-700"],
};

export function EditorialReview({ jobId, chapterNumber }) {
  const [review, setReview] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const runReview = async () => {
    setLoading(true);
    setError("");
    try {
      setReview(await api.reviewChapter(jobId, chapterNumber));
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="mt-6 border-t border-gray-100 pt-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h4 className="text-sm font-semibold text-gray-700">🔎 AI 语义审稿</h4>
          <p className="text-xs text-gray-400">剧情、人物、连续性、节奏 + 低成本规则检查</p>
        </div>
        <button onClick={runReview} disabled={loading}
          className="rounded-lg bg-purple-600 px-3 py-2 text-xs font-medium text-white hover:bg-purple-700 disabled:opacity-50">
          {loading ? "审稿中..." : review ? "重新审稿" : "开始审稿"}
        </button>
      </div>
      {error && <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-600">{error}</p>}
      {review && (
        <div className="mt-4 space-y-4">
          <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
            <Score label="综合" value={review.overall} strong />
            {Object.entries(review.dimensions).map(([name, value]) => (
              <Score key={name} label={DIMENSIONS[name] || name} value={value} />
            ))}
          </div>
          {review.summary && <p className="rounded-lg bg-purple-50 p-3 text-sm text-purple-800">{review.summary}</p>}
          <div className="space-y-2">
            {review.issues.length === 0 && <p className="text-sm text-green-600">未发现明确问题。</p>}
            {review.issues.map((issue, index) => {
              const severity = SEVERITY[issue.severity] || SEVERITY.medium;
              return <article key={`${issue.source}-${index}`} className="rounded-lg border border-gray-100 p-3">
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <span className={`rounded-full px-2 py-0.5 ${severity[1]}`}>{severity[0]}</span>
                  <span className="font-medium text-gray-600">{DIMENSIONS[issue.dimension] || "规则"}</span>
                  <span className="text-gray-400">位置 {issue.location.start}–{issue.location.end}</span>
                </div>
                {issue.location.excerpt && <blockquote className="mt-2 border-l-2 border-gray-200 pl-2 text-xs text-gray-500">{issue.location.excerpt}</blockquote>}
                <p className="mt-2 text-sm text-gray-700">{issue.reason}</p>
                <p className="mt-1 text-xs text-indigo-600">建议：{issue.suggestion}</p>
              </article>;
            })}
          </div>
        </div>
      )}
    </section>
  );
}

function Score({ label, value, strong = false }) {
  const color = value >= 80 ? "text-green-600" : value >= 60 ? "text-amber-600" : "text-red-600";
  return <div className={`rounded-lg p-2 text-center ${strong ? "bg-purple-50" : "bg-gray-50"}`}>
    <div className={`text-lg font-bold ${color}`}>{value}</div>
    <div className="text-[11px] text-gray-400">{label}</div>
  </div>;
}


const OPERATIONS = [
  ["refine", "润色"], ["expand", "扩写"], ["shorten", "缩写"],
  ["style", "改风格"], ["dialogue", "增加对白"], ["description", "增加描写"],
];

export function LocalRewritePanel({ jobId, chapterNumber, content, textareaRef, onApplied }) {
  const [operation, setOperation] = useState("refine");
  const [instruction, setInstruction] = useState("");
  const [style, setStyle] = useState("");
  const [patch, setPatch] = useState(null);
  const [selection, setSelection] = useState(null);
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState("");

  const generate = async (reuseSelection = false) => {
    const element = textareaRef.current;
    const range = reuseSelection && selection
      ? selection
      : { start: element?.selectionStart ?? 0, end: element?.selectionEnd ?? 0 };
    if (range.end <= range.start) {
      setError("请先在正文编辑框中选择需要修改的文字。");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const result = await api.proposeChapterPatch(jobId, chapterNumber, {
        ...range, operation, instruction, style,
        selected_text: content.slice(range.start, range.end),
      });
      setSelection(range);
      setPatch(result);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const accept = async () => {
    if (!patch) return;
    setApplying(true);
    setError("");
    try {
      const result = await api.applyChapterPatch(jobId, chapterNumber, {
        patch_id: patch.patch_id, start: patch.start, end: patch.end,
        original: patch.original, replacement: patch.replacement, base_hash: patch.base_hash,
      });
      onApplied(result);
      setPatch(null);
      setSelection(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setApplying(false);
    }
  };

  return <section className="mt-4 border-t border-gray-100 pt-4">
    <div className="mb-2 flex flex-wrap items-end gap-2">
      <label className="text-xs text-gray-500">局部操作
        <select value={operation} onChange={(e) => setOperation(e.target.value)}
          className="mt-1 block rounded-lg border border-gray-200 px-2 py-2 text-sm text-gray-700">
          {OPERATIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      </label>
      {operation === "style" && <label className="min-w-32 flex-1 text-xs text-gray-500">目标风格
        <input value={style} onChange={(e) => setStyle(e.target.value)} placeholder="如：冷峻克制"
          className="mt-1 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm" />
      </label>}
      <label className="min-w-48 flex-[2] text-xs text-gray-500">补充要求（可选）
        <input value={instruction} onChange={(e) => setInstruction(e.target.value)} placeholder="保持人物语气，不新增设定"
          className="mt-1 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm" />
      </label>
      <button onClick={() => generate(false)} disabled={loading}
        className="rounded-lg bg-indigo-600 px-3 py-2 text-sm text-white hover:bg-indigo-700 disabled:opacity-50">
        {loading ? "生成中..." : "生成选区补丁"}
      </button>
    </div>
    <p className="text-xs text-gray-400">先在上方正文中选中文字。若正文已手动改动，请先保存再生成补丁。</p>
    {error && <p className="mt-2 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-600">{error}</p>}
    {patch && <div className="mt-3 rounded-xl border border-gray-200 bg-gray-50 p-3">
      <div className="mb-2 flex items-center justify-between text-xs text-gray-500">
        <span>Diff 预览 · 仅替换位置 {patch.start}–{patch.end}</span>
        <span>{patch.explanation}</span>
      </div>
      <div className="max-h-52 space-y-2 overflow-y-auto font-mono text-sm">
        <div className="whitespace-pre-wrap rounded-lg bg-red-50 p-3 text-red-700"><span className="select-none font-bold">− </span>{patch.original}</div>
        <div className="whitespace-pre-wrap rounded-lg bg-green-50 p-3 text-green-700"><span className="select-none font-bold">+ </span>{patch.replacement}</div>
      </div>
      <div className="mt-3 flex justify-end gap-2">
        <button onClick={() => setPatch(null)} className="rounded-lg border border-gray-200 px-3 py-1.5 text-xs text-gray-600">拒绝</button>
        <button onClick={() => generate(true)} disabled={loading} className="rounded-lg border border-purple-200 px-3 py-1.5 text-xs text-purple-600 disabled:opacity-50">再生成</button>
        <button onClick={accept} disabled={applying} className="rounded-lg bg-green-600 px-3 py-1.5 text-xs text-white disabled:opacity-50">{applying ? "应用中..." : "接受补丁"}</button>
      </div>
    </div>}
  </section>;
}
