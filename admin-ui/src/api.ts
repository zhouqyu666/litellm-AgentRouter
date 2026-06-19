export type AdminUser = { username: string };

export type ModelConfig = {
  key: string;
  upstream_model: string;
  provider: string;
  reasoning_effort?: string | null;
  upstream_base?: string | null;
};

export type ApiConfig = {
  models: ModelConfig[];
  api_keys: Record<string, string[]>;
  settings: Record<string, string>;
};

export type TelemetrySummary = {
  total_requests: number;
  total_tokens: number;
  prompt_tokens: number;
  completion_tokens: number;
  reasoning_tokens: number;
  models: Array<{
    model_alias: string;
    upstream_model: string;
    request_count: number;
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
    reasoning_tokens: number;
  }>;
};

export type RequestLog = {
  timestamp?: string;
  client_request_id?: string;
  remote_addr?: string;
  model_alias: string;
  upstream_model?: string;
  status_code?: number;
  duration_s?: number;
  streaming: boolean;
  usage: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
    reasoning_tokens: number;
  };
  error_type?: string;
  error_message?: string;
};

const TOKEN_KEY = 'agentrouter_admin_token';

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || '';
}

export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(init.headers as Record<string, string> || {}),
  };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  const response = await fetch(`/admin/api${path}`, { ...init, headers });
  const data = await response.json().catch(() => ({}));
  if (response.status === 401) {
    clearToken();
    throw new Error('登录已过期，请重新登录');
  }
  if (!response.ok) throw new Error(data.detail || data.error || `HTTP ${response.status}`);
  return data as T;
}

export async function login(username: string, password: string) {
  const data = await request<{ token: string }>('/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  });
  setToken(data.token);
  return { username };
}

export async function getCurrentUser(): Promise<AdminUser | null> {
  if (!getToken()) return null;
  await request<{ enabled: boolean }>('/auth/status');
  return { username: 'admin' };
}

export async function changePassword(oldPassword: string, newPassword: string) {
  return request<{ message: string }>('/auth/password', {
    method: 'PUT',
    body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
  });
}

export async function getConfig() {
  return request<ApiConfig>('/config');
}

export async function reloadConfig() {
  return request<{ message: string; deleted: number; added: number; failed: number; requires_restart: boolean }>('/reload', { method: 'POST' });
}

export async function createModel(payload: Partial<ModelConfig> & { key: string; upstream_model: string }) {
  return request('/models', { method: 'POST', body: JSON.stringify(payload) });
}

export async function updateModel(key: string, payload: Partial<ModelConfig>) {
  return request(`/models/${encodeURIComponent(key)}`, { method: 'PUT', body: JSON.stringify(payload) });
}

export async function deleteModel(key: string) {
  return request(`/models/${encodeURIComponent(key)}`, { method: 'DELETE' });
}

export async function addProviderKey(provider: string, key: string) {
  return request(`/keys/${provider}`, { method: 'POST', body: JSON.stringify({ key }) });
}

export async function deleteProviderKey(provider: string, index: number) {
  return request(`/keys/${provider}/${index}`, { method: 'DELETE' });
}

export async function getTelemetrySummary() {
  const data = await request<{ summary: TelemetrySummary }>('/telemetry/summary');
  return data.summary;
}

export async function getRequestLogs(limit = 200) {
  const data = await request<{ requests: RequestLog[] }>(`/telemetry/requests?limit=${limit}`);
  return data.requests;
}
