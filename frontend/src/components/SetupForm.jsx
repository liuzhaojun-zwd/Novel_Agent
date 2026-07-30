import { useRef, useState } from "react";
import { api } from "../api";

const INPUT_CLASS = "w-full px-3 py-2 border border-gray-200 dark:border-gray-600 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent outline-none bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100";
const EMPTY_CHARACTER = { name: "", role: "", identity: "", personality: "", goal: "", internal_need: "", secret: "", arc: "", speech_style: "" };
const STEPS = ["作品定位", "人物与世界", "剧情资产"];
const splitLines = (value = "") => value.split(/\n+/).map((item) => item.trim()).filter(Boolean);
const joinLines = (value) => Array.isArray(value) ? value.join("\n") : (value || "");

function Field({ label, required = false, ...props }) {
  return <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
    <span className="block mb-1">{label}{required && <span className="text-red-500"> *</span>}</span>
    <input {...props} className={INPUT_CLASS} />
  </label>;
}

function TextArea({ label, rows = 3, ...props }) {
  return <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
    <span className="block mb-1">{label}</span>
    <textarea {...props} rows={rows} className={`${INPUT_CLASS} resize-y`} />
  </label>;
}

export default function SetupForm({ onJobCreated }) {
  const [step, setStep] = useState(0);
  const [loading, setLoading] = useState(false);
  const [assisting, setAssisting] = useState(false);
  const [error, setError] = useState("");
  const fileInputRef = useRef(null);
  const [form, setForm] = useState({
    theme: "", topic: "", chapter_count: 10, words_per_chapter: 2000,
    writing_style: "", narrative_perspective: "", target_audience: "", tone: "",
    core_conflict: "", theme_expression: "", selling_points: "", prohibited_content: "",
    character_profiles: [{ ...EMPTY_CHARACTER }], character_relationships: "",
    world_setting: "", world_rules: "", factions: "", power_system: "",
    main_plot: "", subplots: "", foreshadowing: "", key_items: "", locations: "",
  });

  const handleChange = ({ target: { name, value } }) => setForm((current) => ({ ...current, [name]: value }));
  const updateCharacter = (index, field, value) => setForm((current) => ({
    ...current,
    character_profiles: current.character_profiles.map((item, i) => i === index ? { ...item, [field]: value } : item),
  }));
  const addCharacter = () => setForm((current) => ({ ...current, character_profiles: [...current.character_profiles, { ...EMPTY_CHARACTER }] }));
  const removeCharacter = (index) => setForm((current) => ({
    ...current,
    character_profiles: current.character_profiles.filter((_, i) => i !== index),
  }));

  const buildStoryBible = () => ({
    target_audience: form.target_audience.trim(), tone: form.tone.trim(),
    core_conflict: form.core_conflict.trim(), theme_expression: form.theme_expression.trim(),
    selling_points: splitLines(form.selling_points), prohibited_content: splitLines(form.prohibited_content),
    character_profiles: form.character_profiles.filter((item) => item.name.trim()).map((item) =>
      Object.fromEntries(Object.entries(item).map(([key, value]) => [key, typeof value === "string" ? value.trim() : value]))),
    character_relationships: splitLines(form.character_relationships),
    world_summary: form.world_setting.trim(), world_rules: splitLines(form.world_rules),
    factions: splitLines(form.factions), power_system: form.power_system.trim(),
    main_plot: form.main_plot.trim(), subplots: splitLines(form.subplots),
    foreshadowing: splitLines(form.foreshadowing), key_items: splitLines(form.key_items),
    locations: splitLines(form.locations),
  });

  const buildSetup = () => {
    const storyBible = buildStoryBible();
    return {
      theme: form.theme.trim(), topic: form.topic.trim(),
      chapter_count: Number.parseInt(form.chapter_count, 10),
      words_per_chapter: Number.parseInt(form.words_per_chapter, 10),
      writing_style: form.writing_style.trim() || null,
      narrative_perspective: form.narrative_perspective || null,
      characters: storyBible.character_profiles.map((item) => item.name),
      world_setting: form.world_setting.trim() || null,
      story_bible: storyBible,
    };
  };

  const applyBible = (bible = {}) => setForm((current) => ({
    ...current,
    target_audience: bible.target_audience || "", tone: bible.tone || "",
    core_conflict: bible.core_conflict || "", theme_expression: bible.theme_expression || "",
    selling_points: joinLines(bible.selling_points), prohibited_content: joinLines(bible.prohibited_content),
    character_profiles: bible.character_profiles?.length ? bible.character_profiles : current.character_profiles,
    character_relationships: joinLines(bible.character_relationships),
    world_setting: bible.world_summary || current.world_setting,
    world_rules: joinLines(bible.world_rules), factions: joinLines(bible.factions),
    power_system: bible.power_system || "", main_plot: bible.main_plot || "",
    subplots: joinLines(bible.subplots), foreshadowing: joinLines(bible.foreshadowing),
    key_items: joinLines(bible.key_items), locations: joinLines(bible.locations),
  }));

  const validateBasics = () => {
    if (!form.theme.trim() || !form.topic.trim()) return "请先填写题材和故事核心";
    if (form.chapter_count < 1 || form.chapter_count > 1000) return "目标章数须在 1-1000 之间";
    if (form.words_per_chapter < 2000 || form.words_per_chapter > 20000) return "每章字数须在 2000-20000 之间";
    return "";
  };

  const handleAssist = async () => {
    const validationError = validateBasics();
    if (validationError) return setError(validationError);
    setAssisting(true); setError("");
    try {
      const result = await api.assistSetup(buildSetup());
      applyBible(result.story_bible);
    } catch (err) { setError(err.message); }
    finally { setAssisting(false); }
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    const validationError = validateBasics();
    if (validationError) return setError(validationError);
    if (step < STEPS.length - 1) { setStep((value) => value + 1); setError(""); return; }
    setLoading(true); setError("");
    try {
      const result = await api.createJob(buildSetup());
      onJobCreated(result.job_id);
    } catch (err) { setError(err.message); }
    finally { setLoading(false); }
  };

  const handleFileChange = (event) => {
    const file = event.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = ({ target }) => {
      try {
        const parsed = JSON.parse(target.result);
        const data = parsed.setup || parsed;
        const legacyProfiles = Array.isArray(data.characters)
          ? data.characters.map((name) => ({ ...EMPTY_CHARACTER, name })) : [];
        setForm((current) => ({
          ...current, theme: data.theme || "", topic: data.topic || "",
          chapter_count: data.chapter_count || 10, words_per_chapter: data.words_per_chapter || 2000,
          writing_style: data.writing_style || "", narrative_perspective: data.narrative_perspective || "",
          world_setting: data.world_setting || "",
          character_profiles: legacyProfiles.length ? legacyProfiles : current.character_profiles,
        }));
        if (data.story_bible) applyBible(data.story_bible);
        setError("");
      } catch { setError("导入失败：JSON 格式错误"); }
    };
    reader.readAsText(file); event.target.value = "";
  };

  const handleExportSetup = () => {
    const blob = new Blob([JSON.stringify(buildSetup(), null, 2)], { type: "application/json" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `创作设定_${form.theme || "未命名"}.json`;
    link.click(); URL.revokeObjectURL(link.href);
  };

  return <div className="max-w-4xl mx-auto py-8 px-4">
    <div className="text-center mb-6">
      <h1 className="text-3xl font-bold text-gray-900 dark:text-white">✍️ Novel_Agent</h1>
      <p className="text-gray-500 dark:text-gray-400 mt-2">先建立小说圣经，再开始稳定的长篇创作</p>
    </div>

    <form onSubmit={handleSubmit} className="space-y-6 bg-white dark:bg-gray-800 rounded-xl p-6 shadow-sm border border-gray-100 dark:border-gray-700">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-100 dark:border-gray-700 pb-4">
        <div className="flex gap-2">
          {STEPS.map((name, index) => <button key={name} type="button" onClick={() => index <= step && setStep(index)}
            className={`px-3 py-1.5 rounded-full text-sm ${index === step ? "bg-indigo-600 text-white" : index < step ? "bg-indigo-50 text-indigo-700" : "bg-gray-100 text-gray-400"}`}>
            {index + 1}. {name}
          </button>)}
        </div>
        <div className="flex gap-2">
          <input ref={fileInputRef} type="file" accept=".json" className="hidden" onChange={handleFileChange} />
          <button type="button" onClick={() => fileInputRef.current?.click()} className="text-xs px-3 py-2 border rounded-lg dark:border-gray-600">📂 导入</button>
          <button type="button" onClick={handleExportSetup} className="text-xs px-3 py-2 border rounded-lg dark:border-gray-600">💾 导出</button>
          <button type="button" onClick={handleAssist} disabled={assisting}
            className="text-xs px-3 py-2 bg-violet-50 text-violet-700 rounded-lg disabled:opacity-50">
            {assisting ? "AI 完善中..." : "✨ AI 完善小说圣经"}
          </button>
        </div>
      </div>

      {step === 0 && <div className="space-y-4">
        <div className="grid md:grid-cols-2 gap-4">
          <Field label="题材" required name="theme" value={form.theme} onChange={handleChange} placeholder="玄幻、科幻、悬疑……" />
          <Field label="故事核心" required name="topic" value={form.topic} onChange={handleChange} placeholder="用一句话描述主角、目标和阻碍" />
          <Field label="目标读者" name="target_audience" value={form.target_audience} onChange={handleChange} placeholder="如：18-30岁悬疑读者" />
          <Field label="作品基调" name="tone" value={form.tone} onChange={handleChange} placeholder="黑暗、温暖、轻松、史诗感……" />
          <Field label="目标章数" type="number" min="1" max="1000" name="chapter_count" value={form.chapter_count} onChange={handleChange} />
          <Field label="每章字数" type="number" min="2000" max="20000" name="words_per_chapter" value={form.words_per_chapter} onChange={handleChange} />
          <Field label="写作风格" name="writing_style" value={form.writing_style} onChange={handleChange} placeholder="冷峻、幽默、诗意……" />
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300"><span className="block mb-1">叙事视角</span>
            <select name="narrative_perspective" value={form.narrative_perspective} onChange={handleChange} className={INPUT_CLASS}>
              <option value="">不限</option><option value="first_person">第一人称</option><option value="third_person">第三人称</option><option value="multi_pov">多视角</option>
            </select>
          </label>
        </div>
        <TextArea label="核心冲突" name="core_conflict" value={form.core_conflict} onChange={handleChange} placeholder="主角想要什么，什么力量阻止他？" />
        <TextArea label="主题表达" name="theme_expression" value={form.theme_expression} onChange={handleChange} placeholder="故事最终希望探讨什么？" />
        <div className="grid md:grid-cols-2 gap-4">
          <TextArea label="作品卖点（每行一项）" name="selling_points" value={form.selling_points} onChange={handleChange} />
          <TextArea label="禁止内容（每行一项）" name="prohibited_content" value={form.prohibited_content} onChange={handleChange} />
        </div>
      </div>}

      {step === 1 && <div className="space-y-5">
        <div className="flex items-center justify-between"><h2 className="font-semibold dark:text-white">人物卡</h2>
          <button type="button" onClick={addCharacter} className="text-sm text-indigo-600">＋ 添加人物</button>
        </div>
        {form.character_profiles.map((character, index) => <div key={index} className="p-4 rounded-lg bg-gray-50 dark:bg-gray-700/50 space-y-3">
          <div className="grid md:grid-cols-3 gap-3">
            <Field label="姓名" value={character.name} onChange={(e) => updateCharacter(index, "name", e.target.value)} />
            <Field label="角色定位" value={character.role || ""} onChange={(e) => updateCharacter(index, "role", e.target.value)} placeholder="主角、导师、反派……" />
            <Field label="身份" value={character.identity || ""} onChange={(e) => updateCharacter(index, "identity", e.target.value)} />
          </div>
          <div className="grid md:grid-cols-2 gap-3">
            <TextArea label="性格与行为模式" rows={2} value={character.personality || ""} onChange={(e) => updateCharacter(index, "personality", e.target.value)} />
            <TextArea label="外在目标" rows={2} value={character.goal || ""} onChange={(e) => updateCharacter(index, "goal", e.target.value)} />
            <TextArea label="秘密/内在需求" rows={2} value={[character.secret, character.internal_need].filter(Boolean).join("；")} onChange={(e) => updateCharacter(index, "secret", e.target.value)} />
            <TextArea label="成长弧线" rows={2} value={character.arc || ""} onChange={(e) => updateCharacter(index, "arc", e.target.value)} />
          </div>
          {form.character_profiles.length > 1 && <button type="button" onClick={() => removeCharacter(index)} className="text-xs text-red-500">删除人物</button>}
        </div>)}
        <TextArea label="人物关系（每行一条）" name="character_relationships" value={form.character_relationships} onChange={handleChange} placeholder="林舟 → 苏晚晴：互相试探的盟友" />
        <TextArea label="世界观摘要" name="world_setting" value={form.world_setting} onChange={handleChange} />
        <div className="grid md:grid-cols-2 gap-4">
          <TextArea label="不可违反的世界规则（每行一项）" name="world_rules" value={form.world_rules} onChange={handleChange} />
          <TextArea label="势力（每行一项）" name="factions" value={form.factions} onChange={handleChange} />
        </div>
        <TextArea label="能力/等级体系" name="power_system" value={form.power_system} onChange={handleChange} />
      </div>}

      {step === 2 && <div className="space-y-4">
        <TextArea label="主线目标" name="main_plot" value={form.main_plot} onChange={handleChange} placeholder="主角最终要完成什么，失败代价是什么？" />
        <div className="grid md:grid-cols-2 gap-4">
          <TextArea label="支线（每行一项）" name="subplots" value={form.subplots} onChange={handleChange} />
          <TextArea label="伏笔计划（每行一项）" name="foreshadowing" value={form.foreshadowing} onChange={handleChange} />
          <TextArea label="关键道具（每行一项）" name="key_items" value={form.key_items} onChange={handleChange} />
          <TextArea label="关键地点（每行一项）" name="locations" value={form.locations} onChange={handleChange} />
        </div>
        <div className="rounded-lg border border-indigo-100 bg-indigo-50 dark:bg-indigo-900/20 dark:border-indigo-800 p-4 text-sm text-indigo-800 dark:text-indigo-300">
          <strong>创作摘要：</strong> {form.theme || "未填写题材"} · {form.chapter_count} 章 · {form.character_profiles.filter((item) => item.name).length} 位人物
          <p className="mt-1 opacity-80">创建后，AI 将依据小说圣经生成包含 POV、目标、冲突、转折、伏笔和场景规划的章节卡。</p>
        </div>
      </div>}

      {error && <div className="bg-red-50 dark:bg-red-900/30 text-red-600 dark:text-red-400 px-4 py-3 rounded-lg text-sm">{error}</div>}
      <div className="flex justify-between border-t dark:border-gray-700 pt-4">
        <button type="button" onClick={() => setStep((value) => Math.max(0, value - 1))} disabled={step === 0}
          className="px-4 py-2 border rounded-lg disabled:opacity-30 dark:border-gray-600">← 上一步</button>
        <button type="submit" disabled={loading || assisting}
          className="px-6 py-2.5 bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-400 text-white font-medium rounded-lg">
          {loading ? "创建中..." : step < STEPS.length - 1 ? "下一步 →" : "🚀 创建并生成大纲"}
        </button>
      </div>
    </form>
  </div>;
}