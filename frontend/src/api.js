import axios from "axios";

const BASE = process.env.REACT_APP_BACKEND_URL;
export const API_BASE = `${BASE}/api`;

export const api = axios.create({ baseURL: API_BASE });

api.interceptors.request.use((config) => {
  const t = localStorage.getItem("mtos_token");
  if (t) config.headers.Authorization = `Bearer ${t}`;
  return config;
});

api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err?.response?.status === 401) {
      const path = window.location.pathname;
      if (!path.startsWith("/login") && !path.startsWith("/register")) {
        localStorage.removeItem("mtos_token");
        localStorage.removeItem("mtos_user");
        window.location.href = "/login";
      }
    }
    return Promise.reject(err);
  },
);

export const auth = {
  login: (email, password) => api.post("/auth/login", { email, password }).then((r) => r.data),
  register: (payload) => api.post("/auth/register", payload).then((r) => r.data),
  me: () => api.get("/auth/me").then((r) => r.data),
};

export const clients = {
  list: () => api.get("/clients").then((r) => r.data),
  create: (data) => api.post("/clients", data).then((r) => r.data),
  get: (id) => api.get(`/clients/${id}`).then((r) => r.data),
  update: (id, patch) => api.patch(`/clients/${id}`, patch).then((r) => r.data),
  remove: (id) => api.delete(`/clients/${id}`).then((r) => r.data),
  listBindings: (id) => api.get(`/clients/${id}/bindings`).then((r) => r.data),
  upsertBinding: (id, platform, payload) => api.put(`/clients/${id}/bindings/${platform}`, payload).then((r) => r.data),
  deleteBinding: (id, platform) => api.delete(`/clients/${id}/bindings/${platform}`).then((r) => r.data),
  generateMonthlyTouch: (id, payload = {}) => api.post(`/clients/${id}/monthly-touch`, payload).then((r) => r.data),
};

export const meetings = {
  list: (clientId) => api.get(`/meetings${clientId ? `?client_id=${clientId}` : ""}`).then((r) => r.data),
  create: (data) => api.post("/meetings", data).then((r) => r.data),
  get: (id) => api.get(`/meetings/${id}`).then((r) => r.data),
  update: (id, patch) => api.patch(`/meetings/${id}`, patch).then((r) => r.data),
  remove: (id) => api.delete(`/meetings/${id}`).then((r) => r.data),
  generateBrief: (id, body) => api.post(`/meetings/${id}/generate-brief`, body).then((r) => r.data),
  analyzeTranscript: (id, body) => api.post(`/meetings/${id}/analyze-transcript`, body).then((r) => r.data),
  generateRecap: (id, body) => api.post(`/meetings/${id}/generate-recap`, body).then((r) => r.data),
  exportHtml: (id) => api.get(`/meetings/${id}/export/html`).then((r) => r.data),
  syncMeetTranscript: (id) => api.post(`/meetings/${id}/google-meet/sync-transcript`).then((r) => r.data),
  automation: (id) => api.get(`/meetings/${id}/automation`).then((r) => r.data),
  generateAutomation: (id) => api.post(`/meetings/${id}/automation/generate`).then((r) => r.data),
  approveAutomation: (id) => api.post(`/meetings/${id}/automation/approve`).then((r) => r.data),
  qa: (id) => api.get(`/meetings/${id}/qa`).then((r) => r.data),
  scoreQa: (id) => api.post(`/meetings/${id}/qa/score`).then((r) => r.data),
};

export const actionItems = {
  list: (params = {}) => {
    const q = new URLSearchParams(params).toString();
    return api.get(`/action-items${q ? `?${q}` : ""}`).then((r) => r.data);
  },
  create: (data) => api.post("/action-items", data).then((r) => r.data),
  update: (id, patch) => api.patch(`/action-items/${id}`, patch).then((r) => r.data),
  remove: (id) => api.delete(`/action-items/${id}`).then((r) => r.data),
};

export const contentCaptures = {
  list: (clientId) => api.get(`/content-captures${clientId ? `?client_id=${clientId}` : ""}`).then((r) => r.data),
  create: (data) => api.post("/content-captures", data).then((r) => r.data),
  update: (id, patch) => api.patch(`/content-captures/${id}`, patch).then((r) => r.data),
  remove: (id) => api.delete(`/content-captures/${id}`).then((r) => r.data),
};

export const integrations = {
  catalog: () => api.get("/integrations/catalog").then((r) => r.data),
  status: () => api.get("/integrations").then((r) => r.data),
  configure: (platform, data) => api.post(`/integrations/${platform}/configure`, data).then((r) => r.data),
  test: (platform) => api.post(`/integrations/${platform}/test`).then((r) => r.data),
  disconnect: (platform) => api.delete(`/integrations/${platform}`).then((r) => r.data),
  oauthGoogleStart: (platform) => api.get(`/oauth/google/start?platform=${encodeURIComponent(platform)}`).then((r) => r.data),
  oauthGoogleDisconnect: (platform) => api.post(`/oauth/google/disconnect?platform=${encodeURIComponent(platform)}`).then((r) => r.data),
  oauthGoogleStatus: (platform) => api.get(`/oauth/google/status?platform=${encodeURIComponent(platform)}`).then((r) => r.data),
  clickupWorkspaces: () => api.get("/integrations/clickup/workspaces").then((r) => r.data),
  clickupLists: (teamId) => api.get(`/integrations/clickup/lists${teamId ? `?team_id=${encodeURIComponent(teamId)}` : ""}`).then((r) => r.data),
  clickupFolders: (teamId) => api.get(`/integrations/clickup/folders${teamId ? `?team_id=${encodeURIComponent(teamId)}` : ""}`).then((r) => r.data),
  gohighlevelLocations: () => api.get("/integrations/gohighlevel/locations").then((r) => r.data),
  googleAdsCustomers: () => api.get("/integrations/google_ads/customers").then((r) => r.data),
};

export const settings = {
  get: () => api.get("/settings").then((r) => r.data),
  put: (data) => api.put("/settings", data).then((r) => r.data),
};

export const whiteLabel = {
  uploads: () => api.get("/white-label/uploads").then((r) => r.data),
  upload: (file, purpose = "documentation") => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("purpose", purpose);
    return api.post("/white-label/uploads", fd, { headers: { "Content-Type": "multipart/form-data" } }).then((r) => r.data);
  },
  analyze: () => api.post("/white-label/analyze").then((r) => r.data),
};

export const docs = {
  list: () => api.get("/docs").then((r) => r.data),
  get: (slug) => api.get(`/docs/${slug}`).then((r) => r.data),
};

export const dashboard = {
  overview: () => api.get("/dashboard/overview").then((r) => r.data),
};

export const aiModels = {
  list: () => api.get("/ai/models").then((r) => r.data),
};
