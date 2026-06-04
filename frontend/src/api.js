const BASE = "";

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options.headers },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `请求失败 (${res.status})`);
  }
  if (res.status === 204) return null;
  return res.json();
}

export const api = {
  // 任务
  createJob: (setup) =>
    request("/api/jobs", { method: "POST", body: JSON.stringify(setup) }),

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

  confirmOutline: (id) =>
    request(`/api/jobs/${id}/confirm-outline`, { method: "POST" }),

  // 正文
  startGeneration: (id, upTo) =>
    request(`/api/jobs/${id}/start${upTo ? `?up_to=${upTo}` : ""}`, { method: "POST" }),

  resumeGeneration: (id, upTo) =>
    request(`/api/jobs/${id}/resume${upTo ? `?up_to=${upTo}` : ""}`, { method: "POST" }),

  getChapters: (id) => request(`/api/jobs/${id}/chapters`),

  getChapter: (id, num) => request(`/api/jobs/${id}/chapters/${num}`),

  // 导出
  getExportUrl: (id, format = "md") => `/api/jobs/${id}/export?format=${format}`,

  // SSE 流
  streamUrl: (id) => `${BASE}/api/jobs/${id}/stream`,

  // 设置
  getLlmSettings: () => request("/api/settings/llm"),

  updateLlmSettings: (config) =>
    request("/api/settings/llm", { method: "PUT", body: JSON.stringify(config) }),

  checkSetupStatus: () => request("/api/settings/status"),
};