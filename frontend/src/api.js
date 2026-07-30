const BASE = "";

async function request(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...options.headers };
  let res;
  try {
    res = await fetch(`${BASE}${path}`, { credentials: "include", ...options, headers });
  } catch (error) {
    throw new Error(`无法连接服务，请检查后端是否运行（${error.message}）`);
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    const detail = Array.isArray(err.detail)
      ? err.detail.map((item) => item.msg || String(item)).join("；")
      : err.detail;
    throw new Error(detail || (res.status === 401 ? "请先登录" : `请求失败 (${res.status})`));
  }
  if (res.status === 204) return null;
  return res.json();
}

export const api = {
  // 用户会话（HttpOnly Cookie，不在前端保存长期凭据）
  authStatus: () => request("/api/auth/status"),
  bootstrap: (username, password) => request("/api/auth/bootstrap", {
    method: "POST", body: JSON.stringify({ username, password }),
  }),
  login: (username, password) => request("/api/auth/login", {
    method: "POST", body: JSON.stringify({ username, password }),
  }),
  logout: () => request("/api/auth/logout", { method: "POST" }),

  // 任务
  createJob: (setup) =>
    request("/api/jobs", { method: "POST", body: JSON.stringify(setup) }),

  assistSetup: (setup) =>
    request("/api/jobs/assist-setup", { method: "POST", body: JSON.stringify(setup) }),

  listJobs: () => request("/api/jobs"),

  getJob: (id) => request(`/api/jobs/${id}`),

  deleteJob: (id) => request(`/api/jobs/${id}`, { method: "DELETE" }),

  // 大纲
  generateOutline: (id) =>
    request(`/api/jobs/${id}/generate-outline`, { method: "POST" }),

  getOutline: (id) => request(`/api/jobs/${id}/outline`),

  modifyOutline: (id, instruction) =>
    request(`/api/jobs/${id}/outline`, {
      method: "PUT",
      body: JSON.stringify({ instruction }),
    }),

  saveOutline: (id, chapters) =>
    request(`/api/jobs/${id}/outline/content`, {
      method: "PUT",
      body: JSON.stringify({ chapters }),
    }),

  confirmOutline: (id) =>
    request(`/api/jobs/${id}/confirm-outline`, { method: "POST" }),

  // 正文
  startGeneration: (id, upTo, options = {}) => {
    const params = new URLSearchParams();
    if (upTo) params.set("up_to", upTo);
    if (options.chapter) params.set("chapter", options.chapter);
    if (options.mode) params.set("generation_mode", options.mode);
    if (options.idempotencyKey) params.set("idempotency_key", options.idempotencyKey);
    const query = params.toString();
    return request(`/api/jobs/${id}/start${query ? `?${query}` : ""}`, { method: "POST" });
  },

  resumeGeneration: (id, upTo, options = {}) => {
    const params = new URLSearchParams();
    if (upTo) params.set("up_to", upTo);
    if (options.chapter) params.set("chapter", options.chapter);
    if (options.mode) params.set("generation_mode", options.mode);
    if (options.idempotencyKey) params.set("idempotency_key", options.idempotencyKey);
    const query = params.toString();
    return request(`/api/jobs/${id}/resume${query ? `?${query}` : ""}`, { method: "POST" });
  },

  generateChapter: (id, chapter, mode = "auto") =>
    request(`/api/jobs/${id}/chapters/${chapter}/generate?generation_mode=${mode}`, { method: "POST" }),

  pauseGeneration: (id) =>
    request(`/api/jobs/${id}/pause`, { method: "POST" }),

  cancelGeneration: (id) =>
    request(`/api/jobs/${id}/cancel`, { method: "POST" }),

  getGenerationState: (id) => request(`/api/jobs/${id}/generation-state`),

  getChapterScenes: (id, num) => request(`/api/jobs/${id}/chapters/${num}/scenes`),

  getChapters: (id) => request(`/api/jobs/${id}/chapters`),

  getChapter: (id, num) => request(`/api/jobs/${id}/chapters/${num}`),

  // Issue 7: 章节编辑 & 重写
  updateChapter: (id, num, content) =>
    request(`/api/jobs/${id}/chapters/${num}`, {
      method: "PUT",
      body: JSON.stringify({ content }),
    }),

  regenerateChapter: (id, num, instruction = "") =>
    request(`/api/jobs/${id}/chapters/${num}/regenerate`, {
      method: "POST",
      body: JSON.stringify({ instruction }),
    }),

  reviewChapter: (id, num) =>
    request(`/api/jobs/${id}/chapters/${num}/review`, { method: "POST" }),

  proposeChapterPatch: (id, num, payload) =>
    request(`/api/jobs/${id}/chapters/${num}/patches`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  applyChapterPatch: (id, num, patch) =>
    request(`/api/jobs/${id}/chapters/${num}/patches/apply`, {
      method: "POST",
      body: JSON.stringify(patch),
    }),

  // 导出
  getExportUrl: (id, format = "md") => `/api/jobs/${id}/export?format=${format}`,

  // SSE 流
  streamUrl: (id) => `${BASE}/api/jobs/${id}/stream`,

  // 设置
  getLlmSettings: () => request("/api/settings/llm"),

  updateLlmSettings: (config) =>
    request("/api/settings/llm", { method: "PUT", body: JSON.stringify(config) }),

  checkSetupStatus: () => request("/api/settings/status"),

  // Issue 11: 导出/导入设定
  exportSetup: (id) => request(`/api/jobs/${id}/setup`),

  updateSetup: (id, setup) =>
    request(`/api/jobs/${id}/setup`, { method: "PUT", body: JSON.stringify(setup) }),

  // 大纲、设定和正文版本
  getVersions: (id, resourceType, resourceKey = "") => {
    const params = new URLSearchParams({ resource_type: resourceType });
    if (resourceKey !== "") params.set("resource_key", resourceKey);
    return request(`/api/jobs/${id}/versions?${params}`);
  },

  getVersion: (id, versionId) => request(`/api/jobs/${id}/versions/${versionId}`),

  restoreVersion: (id, versionId) =>
    request(`/api/jobs/${id}/versions/${versionId}/restore`, { method: "POST" }),

  // Issue 12: 写作反馈
  getFeedback: (id) => request(`/api/jobs/${id}/feedback`),

  saveFeedback: (id, feedback) =>
    request(`/api/jobs/${id}/feedback`, { method: "PUT", body: JSON.stringify(feedback) }),

  // 长篇记忆与重要事实审批
  getMemories: (id, entity = "") =>
    request(`/api/jobs/${id}/memory${entity ? `?entity=${encodeURIComponent(entity)}` : ""}`),

  getMemoryContext: (id, chapter) =>
    request(`/api/jobs/${id}/memory/context/${chapter}`),

  extractMemory: (id, chapter) =>
    request(`/api/jobs/${id}/memory/extract/${chapter}`, { method: "POST" }),

  getFactChanges: (id, status = "pending") =>
    request(`/api/jobs/${id}/memory/changes${status ? `?status=${status}` : ""}`),

  getFactChangeImpact: (id, changeId) =>
    request(`/api/jobs/${id}/memory/changes/${changeId}/impact`),

  resolveFactChange: (id, changeId, approve) =>
    request(`/api/jobs/${id}/memory/changes/${changeId}/resolve`, {
      method: "POST",
      body: JSON.stringify({ approve }),
    }),
};