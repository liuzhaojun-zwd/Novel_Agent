import { useState, useRef } from "react";
import { api } from "../api";

export default function SetupForm({ onJobCreated }) {
  const [form, setForm] = useState({
    theme: "",
    topic: "",
    chapter_count: 10,
    words_per_chapter: 2000,
    writing_style: "",
    characters: "",
    world_setting: "",
    narrative_perspective: "",
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const fileInputRef = useRef(null);

  const handleChange = (e) => {
    const { name, value } = e.target;
    setForm((f) => ({ ...f, [name]: value }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const setup = {
        theme: form.theme,
        topic: form.topic,
        chapter_count: parseInt(form.chapter_count),
        words_per_chapter: parseInt(form.words_per_chapter),
      };

      if (form.writing_style) setup.writing_style = form.writing_style;
      if (form.characters) {
        setup.characters = form.characters.split(/[,，、]/).map((s) => s.trim()).filter(Boolean);
      }
      if (form.world_setting) setup.world_setting = form.world_setting;
      if (form.narrative_perspective) setup.narrative_perspective = form.narrative_perspective;

      const result = await api.createJob(setup);
      onJobCreated(result.job_id);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // Issue 11: 导入创作设定
  const handleImport = () => {
    fileInputRef.current?.click();
  };

  const handleFileChange = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (evt) => {
      try {
        const data = JSON.parse(evt.target.result);
        setForm({
          theme: data.theme || "",
          topic: data.topic || "",
          chapter_count: data.chapter_count || 10,
          words_per_chapter: data.words_per_chapter || 2000,
          writing_style: data.writing_style || "",
          characters: Array.isArray(data.characters) ? data.characters.join(", ") : (data.characters || ""),
          world_setting: data.world_setting || "",
          narrative_perspective: data.narrative_perspective || "",
        });
        setError("");
      } catch {
        setError("导入失败：JSON 格式错误");
      }
    };
    reader.readAsText(file);
    e.target.value = "";
  };

  // Issue 11: 导出当前设定
  const handleExportSetup = () => {
    const setup = {
      theme: form.theme,
      topic: form.topic,
      chapter_count: parseInt(form.chapter_count) || 10,
      words_per_chapter: parseInt(form.words_per_chapter) || 2000,
    };
    if (form.writing_style) setup.writing_style = form.writing_style;
    if (form.characters) {
      setup.characters = form.characters.split(/[,，、]/).map((s) => s.trim()).filter(Boolean);
    }
    if (form.world_setting) setup.world_setting = form.world_setting;
    if (form.narrative_perspective) setup.narrative_perspective = form.narrative_perspective;

    const blob = new Blob([JSON.stringify(setup, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `创作设定_${form.theme || "未命名"}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  return (
    <div className="max-w-2xl mx-auto py-8 px-4">
      <div className="text-center mb-8">
        <h1 className="text-3xl font-bold text-gray-900 dark:text-white">✍️ Novel_Agent</h1>
        <p className="text-gray-500 dark:text-gray-400 mt-2">AI 小说创作智能体</p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-5 bg-white dark:bg-gray-800 rounded-xl p-6 shadow-sm border border-gray-100 dark:border-gray-700">
        <div className="flex items-center justify-between border-b border-gray-100 dark:border-gray-700 pb-3">
          <h2 className="text-lg font-semibold text-gray-800 dark:text-white">创作设定</h2>
          <div className="flex gap-2">
            {/* Issue 11: 导入/导出按钮 */}
            <input
              ref={fileInputRef}
              type="file"
              accept=".json"
              className="hidden"
              onChange={handleFileChange}
            />
            <button
              type="button"
              onClick={handleImport}
              className="text-xs px-2.5 py-1.5 border border-gray-200 dark:border-gray-600 rounded-lg text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700 transition cursor-pointer"
            >
              📂 导入
            </button>
            <button
              type="button"
              onClick={handleExportSetup}
              className="text-xs px-2.5 py-1.5 border border-gray-200 dark:border-gray-600 rounded-lg text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700 transition cursor-pointer"
            >
              💾 导出
            </button>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              题材 <span className="text-red-500">*</span>
            </label>
            <input
              name="theme"
              value={form.theme}
              onChange={handleChange}
              placeholder="如：玄幻、科幻、悬疑"
              className="w-full px-3 py-2 border border-gray-200 dark:border-gray-600 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent outline-none transition bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              主题 <span className="text-red-500">*</span>
            </label>
            <input
              name="topic"
              value={form.topic}
              onChange={handleChange}
              placeholder="故事核心一句话"
              className="w-full px-3 py-2 border border-gray-200 dark:border-gray-600 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent outline-none transition bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              目标章数 <span className="text-red-500">*</span>
              <span className="text-gray-400 ml-1">(1-1000)</span>
            </label>
            <input
              name="chapter_count"
              type="number"
              min="1"
              max="1000"
              value={form.chapter_count}
              onChange={handleChange}
              className="w-full px-3 py-2 border border-gray-200 dark:border-gray-600 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent outline-none transition bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              每章字数 <span className="text-red-500">*</span>
              <span className="text-gray-400 ml-1">(2000-20000)</span>
            </label>
            <input
              name="words_per_chapter"
              type="number"
              min="2000"
              max="20000"
              value={form.words_per_chapter}
              onChange={handleChange}
              className="w-full px-3 py-2 border border-gray-200 dark:border-gray-600 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent outline-none transition bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100"
            />
          </div>
        </div>

        <div className="border-t border-gray-100 dark:border-gray-700 pt-4">
          <p className="text-sm text-gray-500 dark:text-gray-400 mb-3">可选设定</p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">写作风格</label>
              <input
                name="writing_style"
                value={form.writing_style}
                onChange={handleChange}
                placeholder="如：幽默、冷峻、诗意"
                className="w-full px-3 py-2 border border-gray-200 dark:border-gray-600 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent outline-none transition bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">主要人物</label>
              <input
                name="characters"
                value={form.characters}
                onChange={handleChange}
                placeholder="逗号分隔，如：林夜, 苏晚晴"
                className="w-full px-3 py-2 border border-gray-200 dark:border-gray-600 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent outline-none transition bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100"
              />
            </div>

            <div className="md:col-span-2">
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">世界观设定</label>
              <textarea
                name="world_setting"
                value={form.world_setting}
                onChange={handleChange}
                rows={2}
                placeholder="如：修仙世界中，灵气复苏..."
                className="w-full px-3 py-2 border border-gray-200 dark:border-gray-600 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent outline-none transition bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 resize-none"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">叙事视角</label>
              <select
                name="narrative_perspective"
                value={form.narrative_perspective}
                onChange={handleChange}
                className="w-full px-3 py-2 border border-gray-200 dark:border-gray-600 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent outline-none transition bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100"
              >
                <option value="">不限</option>
                <option value="first_person">第一人称</option>
                <option value="third_person">第三人称</option>
                <option value="multi_pov">多视角</option>
              </select>
            </div>
          </div>
        </div>

        {error && (
          <div className="bg-red-50 dark:bg-red-900/30 text-red-600 dark:text-red-400 px-4 py-3 rounded-lg text-sm">
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={loading}
          className="w-full py-3 bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-400 text-white font-medium rounded-lg transition cursor-pointer"
        >
          {loading ? "创建中..." : "🚀 创建创作任务"}
        </button>
      </form>
    </div>
  );
}