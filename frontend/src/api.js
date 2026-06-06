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
  google: (credential) => api.post("/auth/google", { credential }).then((r) => r.data),
  me: () => api.get("/auth/me").then((r) => r.data),
};

export const users = {
  list: () => api.get("/users").then((r) => r.data),
};

export const clients = {
  list: () => api.get("/clients").then((r) => r.data),
  create: (data) => api.post("/clients", data).then((r) => r.data),
  get: (id) => api.get(`/clients/${id}`).then((r) => r.data),
  update: (id, patch) => api.patch(`/clients/${id}`, patch).then((r) => r.data),
  remove: (id) => api.delete(`/clients/${id}`).then((r) => r.data),
  suggestions: {
    get: (id) => api.get(`/clients/${encodeURIComponent(id)}/suggestions`).then((r) => r.data),
    generate: (id, payload = {}) => api.post(`/clients/${encodeURIComponent(id)}/suggestions/generate`, payload).then((r) => r.data),
  },
  listBindings: (id) => api.get(`/clients/${id}/bindings`).then((r) => r.data),
  upsertBinding: (id, platform, payload) => api.put(`/clients/${id}/bindings/${platform}`, payload).then((r) => r.data),
  deleteBinding: (id, platform) => api.delete(`/clients/${id}/bindings/${platform}`).then((r) => r.data),
  generateMonthlyTouch: (id, payload = {}) => api.post(`/clients/${id}/monthly-touch`, payload).then((r) => r.data),
  clickupSyncStatus: (userId = "") =>
    api.get(`/import/clickup/clients/status${userId ? `?user_id=${encodeURIComponent(userId)}` : ""}`).then((r) => r.data),
  clickupSyncNow: () => api.post("/import/clickup/clients/sync").then((r) => r.data),
  clickupSyncAll: () => api.post("/import/clickup/clients/sync/all").then((r) => r.data),
  exportCommunications: (id, format = "html") =>
    api.get(`/exports/client-communications/${id}.${format}`, { responseType: "blob" }).then((r) => r.data),
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
  generateDiscovery: (id) => api.post(`/meetings/${id}/discovery/generate`).then((r) => r.data),
};

export const actionItems = {
  list: (params = {}) => {
    const q = new URLSearchParams(params).toString();
    return api.get(`/action-items${q ? `?${q}` : ""}`).then((r) => r.data);
  },
  create: (data) => api.post("/action-items", data).then((r) => r.data),
  update: (id, patch) => api.patch(`/action-items/${id}`, patch).then((r) => r.data),
  remove: (id) => api.delete(`/action-items/${id}`).then((r) => r.data),
  followUp: (params = {}) => {
    const q = new URLSearchParams(params).toString();
    return api.get(`/action-items/follow-up${q ? `?${q}` : ""}`).then((r) => r.data);
  },
  remind: (id) => api.post(`/action-items/${id}/remind`).then((r) => r.data),
};

export const roadmap = {
  get: (clientId) => api.get(`/roadmap/${encodeURIComponent(clientId)}`).then((r) => r.data),
  put: (clientId, payload) => api.put(`/roadmap/${encodeURIComponent(clientId)}`, payload).then((r) => r.data),
  addItem: (clientId, payload) => api.post(`/roadmap/${encodeURIComponent(clientId)}/items`, payload).then((r) => r.data),
  patchItem: (clientId, itemId, patch) =>
    api.patch(`/roadmap/${encodeURIComponent(clientId)}/items/${encodeURIComponent(itemId)}`, patch).then((r) => r.data),
};

export const reviews = {
  goal: {
    get: (clientId) => api.get(`/reviews/${encodeURIComponent(clientId)}/goal`).then((r) => r.data),
    put: (clientId, payload) => api.put(`/reviews/${encodeURIComponent(clientId)}/goal`, payload).then((r) => r.data),
  },
  stats: (clientId, months = 12) => api.get(`/reviews/${encodeURIComponent(clientId)}/stats?months=${encodeURIComponent(months)}`).then((r) => r.data),
  events: {
    list: (clientId, limit = 200) => api.get(`/reviews/${encodeURIComponent(clientId)}/events?limit=${encodeURIComponent(limit)}`).then((r) => r.data),
    create: (clientId, payload) => api.post(`/reviews/${encodeURIComponent(clientId)}/events`, payload).then((r) => r.data),
  },
};

export const feedback = {
  trend: (clientId, limit = 24) =>
    api.get(`/feedback/${encodeURIComponent(clientId)}/trend?limit=${encodeURIComponent(limit)}`).then((r) => r.data),
};

export const health = {
  trend: (clientId, limit = 24) =>
    api.get(`/health/${encodeURIComponent(clientId)}/trend?limit=${encodeURIComponent(limit)}`).then((r) => r.data),
};

export const aiTerritory = {
  latest: (clientId) => api.get(`/ai-territory/${encodeURIComponent(clientId)}/latest`).then((r) => r.data),
  history: (clientId, limit = 30) =>
    api.get(`/ai-territory/${encodeURIComponent(clientId)}/history?limit=${encodeURIComponent(limit)}`).then((r) => r.data),
  runNow: (clientId) => api.post(`/ai-territory/${encodeURIComponent(clientId)}/run`).then((r) => r.data),
  getSettings: () => api.get("/ai-territory/settings").then((r) => r.data),
  putSettings: ({ scanFrequencyHours = 24, maxPrompts = 60 } = {}) =>
    api.put(`/ai-territory/settings?scan_frequency_hours=${encodeURIComponent(scanFrequencyHours)}&max_prompts=${encodeURIComponent(maxPrompts)}`).then((r) => r.data),
};

export const libraries = {
  wins: ({ start = "", end = "", clientId = "", accountManagerId = "", q = "", limit = 500 } = {}) => {
    const params = new URLSearchParams();
    if (start) params.set("start", start);
    if (end) params.set("end", end);
    if (clientId) params.set("client_id", clientId);
    if (accountManagerId) params.set("account_manager_id", accountManagerId);
    if (q) params.set("q", q);
    if (limit) params.set("limit", String(limit));
    const qs = params.toString();
    return api.get(`/wins/library${qs ? `?${qs}` : ""}`).then((r) => r.data);
  },
  issues: ({ start = "", end = "", clientId = "", accountManagerId = "", q = "", limit = 500 } = {}) => {
    const params = new URLSearchParams();
    if (start) params.set("start", start);
    if (end) params.set("end", end);
    if (clientId) params.set("client_id", clientId);
    if (accountManagerId) params.set("account_manager_id", accountManagerId);
    if (q) params.set("q", q);
    if (limit) params.set("limit", String(limit));
    const qs = params.toString();
    return api.get(`/issues/library${qs ? `?${qs}` : ""}`).then((r) => r.data);
  },
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
  gohighlevelLocationTokens: () => api.get("/integrations/gohighlevel/location-tokens").then((r) => r.data),
  gohighlevelUpsertLocationToken: (locationId, token) => api.post("/integrations/gohighlevel/location-tokens", { location_id: locationId, token }).then((r) => r.data),
  gohighlevelDeleteLocationToken: (locationId) => api.delete(`/integrations/gohighlevel/location-tokens?location_id=${encodeURIComponent(locationId)}`).then((r) => r.data),
  googleAdsCustomers: () => api.get("/integrations/google_ads/customers").then((r) => r.data),
};

export const settings = {
  get: () => api.get("/settings").then((r) => r.data),
  put: (data) => api.put("/settings", data).then((r) => r.data),
};

export const prompts = {
  get: (key) => api.get(`/prompts/${encodeURIComponent(key)}`).then((r) => r.data),
  put: (key, payload) => api.put(`/prompts/${encodeURIComponent(key)}`, payload).then((r) => r.data),
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
  domains: () => api.get("/white-label/domains").then((r) => r.data),
  addDomain: (domain) => api.post(`/white-label/domains?domain=${encodeURIComponent(domain)}`).then((r) => r.data),
  deleteDomain: (domain) => api.delete(`/white-label/domains?domain=${encodeURIComponent(domain)}`).then((r) => r.data),
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

export const aiVisibility = {
  entitlement: () => api.get("/ai-visibility/entitlement").then((r) => r.data),
  listConfigs: (clientId) => api.get(`/ai-visibility/configs?client_id=${encodeURIComponent(clientId)}`).then((r) => r.data),
  createConfig: (clientId, payload) => api.post(`/ai-visibility/configs?client_id=${encodeURIComponent(clientId)}`, payload).then((r) => r.data),
  updateConfig: (configId, payload) => api.patch(`/ai-visibility/configs/${configId}`, payload).then((r) => r.data),
  listRuns: (configId, limit = 100, scanId = "") =>
    api.get(`/ai-visibility/configs/${configId}/runs?limit=${encodeURIComponent(limit)}${scanId ? `&scan_id=${encodeURIComponent(scanId)}` : ""}`).then((r) => r.data),
  listScans: (configId, limit = 30) => api.get(`/ai-visibility/configs/${configId}/scans?limit=${encodeURIComponent(limit)}`).then((r) => r.data),
  run: (configId) => api.post(`/ai-visibility/configs/${configId}/run`).then((r) => r.data),
  superGrant: (tenantId, enabled = true, trialDays = 14) =>
    api.post(`/super/ai-visibility/grant?tenant_id=${encodeURIComponent(tenantId)}&enabled=${encodeURIComponent(enabled)}&trial_days=${encodeURIComponent(trialDays)}`).then((r) => r.data),
};
