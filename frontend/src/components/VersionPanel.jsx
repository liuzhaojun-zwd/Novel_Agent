import { useCallback, useEffect, useState } from "react";
import { api } from "../api";

const RESOURCE_NAMES = { chapter: "正文", outline: "大纲", settings: "设定" };

function formatContent(value) {
  if (typeof value === "string") return value;
  if (value && typeof value === "object" && typeof value.content === "string") {
    return value.content;
  }
  return JSON.stringify(value ?? {}, null, 2);
}

export default function VersionPanel({ jobId, resourceType, resourceKey = "", onRestored }) {
  const [items, setItems] = useState([]);
  const [current, setCurrent] = useState(null);
  const [selected, setSelected] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const result = await api.getVersions(jobId, resourceType, resourceKey);
      setItems(result.versions || []);
      setCurrent(result.current);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [jobId, resourceType, resourceKey]);

  useEffect(() => {
    const timer = window.setTimeout(load, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const showCompare = async (item) => {
    setError("");
    try {
      setSelected(await api.getVersion(jobId, item.id));
    } catch (err) {
      setError(err.message);
    }
  };

  const restore = async (item) => {
    if (!item || busy) return;
    if (!window.confirm(`恢复到 v${item.version_number}？当前内容会先自动备份。`)) return;
    setBusy(true);
    setError("");
    try {
      await api.restoreVersion(jobId, item.id);
      setSelected(null);
      await load();
      await onRestored?.();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const previous = items.length > 1 ? items[1] : null;
  const name = RESOURCE_NAMES[resourceType] || resourceType;

  return <section aria-labelledby="version-title" className="space-y-3">
    <div className="flex items-center justify-between gap-2">
      <div>
        <h3 id="version-title" className="text-sm font-semibold text-gray-800 dark:text-gray-100">{name}版本</h3>
        <p className="text-xs text-gray-400">保存时自动留版，恢复前自动备份</p>
      </div>
      <button type="button" onClick={() => restore(previous)} disabled={!previous || busy}
        className="rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs text-gray-600 hover:bg-gray-50 disabled:opacity-40 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-700">
        ↶ 撤销
      </button>
    </div>
    {error && <p role="alert" className="rounded-lg bg-red-50 p-2 text-xs text-red-700 dark:bg-red-950/40 dark:text-red-300">{error}</p>}
    {loading ? <p className="py-5 text-center text-xs text-gray-400">加载版本…</p> : items.length === 0 ?
      <div className="rounded-lg border border-dashed border-gray-200 p-4 text-center text-xs text-gray-400 dark:border-gray-700">首次保存后会在这里生成版本</div> :
      <ol className="max-h-72 space-y-2 overflow-y-auto" aria-label={`${name}版本列表`}>
        {items.map((item, index) => <li key={item.id} className="rounded-lg border border-gray-100 p-2.5 dark:border-gray-700">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <p className="truncate text-xs font-medium text-gray-700 dark:text-gray-200">v{item.version_number} · {item.label || "自动保存"}{index === 0 ? "（当前）" : ""}</p>
              <p className="mt-0.5 text-[11px] text-gray-400">{item.created_at} · {item.word_count.toLocaleString()} 字</p>
            </div>
            <div className="flex shrink-0 gap-1">
              <button type="button" onClick={() => showCompare(item)} className="rounded px-1.5 py-1 text-[11px] text-indigo-600 hover:bg-indigo-50 dark:text-indigo-300">对比</button>
              {index !== 0 && <button type="button" onClick={() => restore(item)} disabled={busy} className="rounded px-1.5 py-1 text-[11px] text-amber-700 hover:bg-amber-50 disabled:opacity-50 dark:text-amber-300">恢复</button>}
            </div>
          </div>
        </li>)}
      </ol>}

    {selected && <div role="dialog" aria-modal="true" aria-labelledby="compare-title" className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="max-h-[90vh] w-full max-w-5xl overflow-hidden rounded-2xl bg-white shadow-xl dark:bg-gray-800">
        <header className="flex items-center justify-between border-b border-gray-100 px-5 py-3 dark:border-gray-700">
          <div><h2 id="compare-title" className="font-semibold text-gray-900 dark:text-white">版本对比 · v{selected.version_number}</h2><p className="text-xs text-gray-400">左侧历史版本，右侧当前内容</p></div>
          <button type="button" aria-label="关闭版本对比" onClick={() => setSelected(null)} className="rounded-lg p-2 text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700">✕</button>
        </header>

        <div className="grid max-h-[68vh] grid-cols-1 overflow-auto md:grid-cols-2">
          <pre className="min-h-60 whitespace-pre-wrap border-b border-red-100 bg-red-50/40 p-4 text-xs leading-6 text-gray-700 md:border-b-0 md:border-r dark:border-red-900/30 dark:bg-red-950/10 dark:text-gray-200">{formatContent(selected.content)}</pre>
          <pre className="min-h-60 whitespace-pre-wrap bg-green-50/40 p-4 text-xs leading-6 text-gray-700 dark:bg-green-950/10 dark:text-gray-200">{formatContent(current)}</pre>
        </div>
        <footer className="flex justify-end gap-2 border-t border-gray-100 px-5 py-3 dark:border-gray-700">
          <button type="button" onClick={() => setSelected(null)} className="rounded-lg border border-gray-200 px-3 py-2 text-sm dark:border-gray-600">关闭</button>
          <button type="button" onClick={() => restore(selected)} disabled={busy} className="rounded-lg bg-amber-600 px-3 py-2 text-sm text-white disabled:opacity-50">恢复此版本</button>
        </footer>
      </div>
    </div>}
  </section>;
}