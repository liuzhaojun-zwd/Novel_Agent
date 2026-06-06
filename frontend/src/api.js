const BASE = "";
const ADMIN_TOKEN = localStorage.getItem("novel-admin-token") || "novel-agent-2026";

async function request(path, options = {}) {
  const headers = { "Content-Type": "application/json", "X-Admin-Token": ADMIN_TOKEN, ...options.headers };
  const res = await fetch(`${BASE}${path}`, {
    headers,
    ...options,
  });
  if (!res.ok) {
    if (res.status === 401) {
      // 提示用户输入 token
      const token = prompt("请输入管理员 Token：");
      if (token) {
        localStorage.setItem("novel-admin-token", token);
        // 重试
        headers["X-Admin-Token"] = token;
        return request(path, { ...options, headers });
      }
      throw new Error("未授权");
    }
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

  // Issue 12: 写作反馈
  getFeedback: (id) => request(`/api/jobs/${id}/feedback`),

  saveFeedback: (id, feedback) =>
    request(`/api/jobs/${id}/feedback`, { method: "PUT", body: JSON.stringify(feedback) }),
};