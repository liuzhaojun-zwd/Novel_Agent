import { useCallback, useEffect, useState } from "react";
import { api } from "../api";

const LAYER_NAMES = {
  fixed: "固定设定",
  state: "剧情状态",
  asset: "长期资产",
};

export default function MemoryPanel({ jobId }) {
  const [open, setOpen] = useState(false);
  const [memories, setMemories] = useState([]);
  const [changes, setChanges] = useState([]);
  const [search, setSearch] = useState("");
  const [busy, setBusy] = useState(null);
  const [message, setMessage] = useState("");
  const [impact, setImpact] = useState(null);

  const load = useCallback(async (entity = "") => {
    try {
      const [memoryData, changeData] = await Promise.all([
        api.getMemories(jobId, entity),
        api.getFactChanges(jobId, "pending"),
      ]);
      setMemories(memoryData.memories || []);
      setChanges(changeData.changes || []);
    } catch (error) {
      setMessage("记忆加载失败：" + error.message);
    }
  }, [jobId]);

  useEffect(() => {
    const initialTimer = window.setTimeout(() => load(search), 0);
    const refreshTimer = window.setInterval(() => load(search), 15000);
    return () => {
      window.clearTimeout(initialTimer);
      window.clearInterval(refreshTimer);
    };
  }, [load, search]);

  const showImpact = async (change) => {
    setBusy(change.id);
    try {
      setImpact(await api.getFactChangeImpact(jobId, change.id));
    } catch (error) {
      setMessage("影响分析失败：" + error.message);
    } finally {
      setBusy(null);
    }
  };

  const resolve = async (change, approve) => {
    const action = approve ? "接受" : "拒绝";
    if (!window.confirm(`${action}这项重要事实变更？${approve ? "后续章节将使用新事实。" : "原事实将继续生效。"}`)) return;
    setBusy(change.id);
    try {
      await api.resolveFactChange(jobId, change.id, approve);
      setMessage(`已${action}事实变更`);
      setImpact(null);
      await load(search);
    } catch (error) {
      setMessage(`${action}失败：${error.message}`);
    } finally {
      setBusy(null);
    }
  };

  const grouped = memories.reduce((result, item) => {
    (result[item.layer] ||= []).push(item);
    return result;
  }, {});

  return (
    <section className="mb-6 rounded-xl border border-violet-100 bg-white shadow-sm">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center justify-between px-5 py-4 text-left cursor-pointer"
      >
        <span>
          <strong className="text-gray-900">🧠 长篇记忆</strong>
          <span className="ml-2 text-xs text-gray-400">{memories.length} 条有效事实</span>
        </span>
        <span className="flex items-center gap-2 text-sm text-gray-500">
          {changes.length > 0 && (
            <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-700">
              {changes.length} 项待确认
            </span>
          )}
          {open ? "收起 ▲" : "展开 ▼"}
        </span>
      </button>

      {open && (
        <div className="border-t border-gray-100 px-5 py-4">
          {message && <p className="mb-3 text-sm text-gray-600">{message}</p>}

          {changes.length > 0 && (
            <div className="mb-5 rounded-lg border border-amber-200 bg-amber-50 p-4">
              <h4 className="mb-2 text-sm font-semibold text-amber-900">重要事实变更待确认</h4>
              <div className="space-y-3">
                {changes.map((change) => (
                  <div key={change.id} className="rounded-lg bg-white p-3 text-sm shadow-sm">
                    <p className="font-medium text-gray-800">
                      {change.entity_key} · {change.attribute}
                    </p>
                    <p className="mt-1 text-gray-500">
                      <span className="line-through">{change.old_value}</span>
                      <span className="mx-2">→</span>
                      <span className="font-medium text-violet-700">{change.proposed_memory.value}</span>
                    </p>
                    <p className="mt-1 text-xs text-gray-400">
                      来源：第 {change.proposed_memory.chapter_number} 章
                    </p>
                    <div className="mt-2 flex flex-wrap gap-2">
                      <button onClick={() => showImpact(change)} disabled={busy === change.id} className="rounded border border-gray-200 px-2 py-1 text-xs hover:bg-gray-50 cursor-pointer disabled:opacity-50">
                        分析影响章节
                      </button>
                      <button onClick={() => resolve(change, false)} disabled={busy === change.id} className="rounded border border-red-200 px-2 py-1 text-xs text-red-600 hover:bg-red-50 cursor-pointer disabled:opacity-50">
                        拒绝
                      </button>
                      <button onClick={() => resolve(change, true)} disabled={busy === change.id} className="rounded bg-violet-600 px-2 py-1 text-xs text-white hover:bg-violet-700 cursor-pointer disabled:opacity-50">
                        接受变更
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {impact && (
            <div className="mb-5 rounded-lg border border-blue-100 bg-blue-50 p-3 text-sm text-blue-800">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <strong>影响分析：{impact.entity_key} · {impact.attribute}</strong>
                  <p className="mt-1">{impact.summary}</p>
                  <p className="mt-1 text-xs">
                    涉及章节：{impact.affected_chapters.length ? impact.affected_chapters.join("、") : "暂无直接提及"}
                  </p>
                </div>
                <button onClick={() => setImpact(null)} className="text-blue-500 cursor-pointer">✕</button>
              </div>
            </div>
          )}

          <form
            className="mb-4 flex gap-2"
            onSubmit={(event) => { event.preventDefault(); load(search.trim()); }}
          >
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="按人物、地点、道具或伏笔检索历史"
              className="min-w-0 flex-1 rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-violet-400"
            />
            <button type="submit" className="rounded-lg bg-gray-800 px-4 py-2 text-sm text-white hover:bg-gray-900 cursor-pointer">
              检索
            </button>
          </form>

          <div className="grid gap-3 md:grid-cols-3">
            {["fixed", "state", "asset"].map((layer) => (
              <div key={layer} className="rounded-lg border border-gray-100 bg-gray-50 p-3">
                <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
                  {LAYER_NAMES[layer]} ({grouped[layer]?.length || 0})
                </h4>
                <div className="max-h-52 space-y-2 overflow-y-auto">
                  {(grouped[layer] || []).map((item) => (
                    <div key={item.id} className="rounded bg-white p-2 text-xs text-gray-600">
                      <p className="font-medium text-gray-800">{item.entity_key} · {item.attribute}</p>
                      <p className="mt-0.5 leading-relaxed">{item.value}</p>
                      {item.chapter_number > 0 && <p className="mt-1 text-gray-400">第 {item.chapter_number} 章</p>}
                    </div>
                  ))}
                  {!grouped[layer]?.length && <p className="text-xs text-gray-400">暂无记录</p>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
