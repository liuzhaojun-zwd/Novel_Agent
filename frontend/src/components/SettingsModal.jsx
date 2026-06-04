import { useState, useEffect } from "react";
import { api } from "../api";

export default function SettingsModal({ open, onClose, onConfigured }) {
  const [form, setForm] = useState({
    api_key: "",
    base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    model: "qwen-max",
    temperature: 0.8,
  });
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    if (open) {
      // 加载已有配置
      api.getLlmSettings().then((cfg) => {
        setForm((f) => ({
          ...f,
          base_url: cfg.base_url || f.base_url,
          model: cfg.model || f.model,
          temperature: cfg.temperature || f.temperature,
        }));
      }).catch(() => {});
    }
  }, [open]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSaving(true);
    setMsg("");
    try {
      const result = await api.updateLlmSettings({
        api_key: form.api_key,
        base_url: form.base_url || undefined,
        model: form.model || undefined,
        temperature: form.temperature || undefined,
      });
      setMsg(result.connected ? "✅ 连接成功！" : "⚠️ " + result.message);
      if (result.connected) {
        setTimeout(() => { onConfigured(); onClose(); }, 1000);
      }
    } catch (err) {
      setMsg("❌ " + err.message);
    } finally {
      setSaving(false);
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-xl shadow-xl max-w-md w-full mx-4 p-6">
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-lg font-bold text-gray-900">⚙️ API 配置</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl cursor-pointer">&times;</button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              API Key <span className="text-red-500">*</span>
            </label>
            <input
              value={form.api_key}
              onChange={(e) => setForm((f) => ({ ...f, api_key: e.target.value }))}
              placeholder="sk-xxxxxxxxxxxxxxxx"
              className="w-full px-3 py-2 border border-gray-200 rounded-lg focus:ring-2 focus:ring-indigo-500 outline-none transition font-mono text-sm"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">API 地址</label>
            <input
              value={form.base_url}
              onChange={(e) => setForm((f) => ({ ...f, base_url: e.target.value }))}
              placeholder="https://api.openai.com/v1"
              className="w-full px-3 py-2 border border-gray-200 rounded-lg focus:ring-2 focus:ring-indigo-500 outline-none transition text-sm"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">模型</label>
              <input
                value={form.model}
                onChange={(e) => setForm((f) => ({ ...f, model: e.target.value }))}
                placeholder="deepseek-chat"
                className="w-full px-3 py-2 border border-gray-200 rounded-lg focus:ring-2 focus:ring-indigo-500 outline-none transition text-sm"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">温度</label>
              <input
                type="number"
                step="0.1"
                min="0"
                max="2"
                value={form.temperature}
                onChange={(e) => setForm((f) => ({ ...f, temperature: parseFloat(e.target.value) || 0.8 }))}
                className="w-full px-3 py-2 border border-gray-200 rounded-lg focus:ring-2 focus:ring-indigo-500 outline-none transition text-sm"
              />
            </div>
          </div>

          {msg && (
            <div className={`px-4 py-3 rounded-lg text-sm ${msg.startsWith("✅") ? "bg-green-50 text-green-700" : msg.startsWith("⚠️") ? "bg-yellow-50 text-yellow-700" : "bg-red-50 text-red-600"}`}>
              {msg}
            </div>
          )}

          <button
            type="submit"
            disabled={saving}
            className="w-full py-3 bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-400 text-white font-medium rounded-lg transition cursor-pointer"
          >
            {saving ? "验证中..." : "保存并测试连接"}
          </button>
        </form>

        <p className="mt-4 text-xs text-gray-400 leading-relaxed">
          支持任何兼容 OpenAI API 格式的服务。保存后会立即测试连接。
          配置保存在内存中，服务重启后需重新配置（或写入 .env 文件持久化）。
        </p>
      </div>
    </div>
  );
}