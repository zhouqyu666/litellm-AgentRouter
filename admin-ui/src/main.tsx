import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Activity, BarChart3, Database, KeyRound, LayoutDashboard, ListChecks, LockKeyhole, LogOut, Plus, RefreshCw, Save, Server, Settings, Shield, Trash2 } from 'lucide-react';
import * as api from './api';
import type { AdminUser, ApiConfig, ModelConfig, RequestLog, TelemetrySummary } from './api';
import './style.css';

type Page = 'dashboard' | 'models' | 'keys' | 'logs' | 'settings' | 'security';

const emptyConfig: ApiConfig = { models: [], api_keys: { openai: [], anthropic: [] }, settings: {} };
const emptySummary: TelemetrySummary = { total_requests: 0, total_tokens: 0, prompt_tokens: 0, completion_tokens: 0, reasoning_tokens: 0, models: [] };

function fmt(value: unknown) {
  return Number(value || 0).toLocaleString();
}

function fmtTime(value?: string) {
  if (!value) return '-';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false });
}

function truncate(value: unknown, size = 34) {
  const text = String(value ?? '');
  return text.length > size ? `${text.slice(0, size)}...` : text;
}

function Login({ onLogin }: { onLogin: (user: AdminUser) => void }) {
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError('');
    try {
      onLogin(await api.login(username, password));
    } catch (err: any) {
      setError(err.message || '登录失败');
    }
  }

  return <div className="login-page">
    <form className="login-card" onSubmit={submit}>
      <div className="brand"><Shield size={42}/><div><h1>AgentRouter 管理系统</h1><p>登录后管理模型、密钥与请求日志</p></div></div>
      <label>账号<input value={username} onChange={e => setUsername(e.target.value)} autoComplete="username"/></label>
      <label>密码<input type="password" value={password} onChange={e => setPassword(e.target.value)} autoComplete="current-password"/></label>
      {error && <div className="error">{error}</div>}
      <button className="primary full">登录</button>
      <p className="hint">首次启动默认账号 admin / changeme，生产环境请使用 ADMIN_USERNAME、ADMIN_PASSWORD 覆盖。</p>
    </form>
  </div>;
}

function App() {
  const [user, setUser] = useState<AdminUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getCurrentUser().then(setUser).finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="loading">加载中...</div>;
  if (!user) return <Login onLogin={setUser}/>;
  return <Layout user={user} onLogout={() => { api.clearToken(); setUser(null); }}/>;
}

function Layout({ user, onLogout }: { user: AdminUser; onLogout: () => void }) {
  const [page, setPage] = useState<Page>('dashboard');
  const [config, setConfig] = useState<ApiConfig>(emptyConfig);
  const [summary, setSummary] = useState<TelemetrySummary>(emptySummary);
  const [logs, setLogs] = useState<RequestLog[]>([]);
  const [toast, setToast] = useState('');

  async function load() {
    const [configData, summaryData, logsData] = await Promise.all([
      api.getConfig(),
      api.getTelemetrySummary(),
      api.getRequestLogs(200),
    ]);
    setConfig(configData);
    setSummary(summaryData);
    setLogs(logsData);
  }

  async function reload() {
    const result = await api.reloadConfig();
    setToast(`配置已重载：新增 ${result.added}，失败 ${result.failed}`);
    await load();
  }

  useEffect(() => {
    load().catch((err) => setToast(err.message || '加载失败'));
  }, []);

  const nav = [
    ['dashboard', LayoutDashboard, '仪表盘'],
    ['models', Server, '模型管理'],
    ['keys', KeyRound, 'API Key 管理'],
    ['logs', ListChecks, '请求日志'],
    ['settings', Settings, '运行配置'],
    ['security', LockKeyhole, '账号安全'],
  ] as const;

  return <div className="app-shell">
    {toast && <div className="toast" onClick={() => setToast('')}>{toast}</div>}
    <aside>
      <div className="side-title"><Shield/>AgentRouter 管理</div>
      <nav>
        {nav.map(([id, Icon, label]) => <button key={id} className={page === id ? 'active' : ''} onClick={() => setPage(id)}><Icon size={18}/>{label}</button>)}
      </nav>
      <div className="side-user">
        <div>{user.username}</div>
        <small>管理员</small>
        <button onClick={onLogout}><LogOut size={18}/>退出登录</button>
      </div>
    </aside>
    <main>
      <div className="page-title">
        <div>{page === 'dashboard' ? <Activity/> : <BarChart3/>}<h1>{nav.find(item => item[0] === page)?.[2]}</h1></div>
        <div className="table-actions"><button className="ghost" onClick={load}><RefreshCw size={16}/>刷新</button><button className="primary" onClick={reload}><Save size={16}/>重载配置</button></div>
      </div>
      {page === 'dashboard' && <Dashboard config={config} summary={summary}/>}
      {page === 'models' && <ModelsPage config={config} onChanged={load} setToast={setToast}/>}
      {page === 'keys' && <KeysPage config={config} onChanged={load} setToast={setToast}/>}
      {page === 'logs' && <LogsPage logs={logs} summary={summary}/>}
      {page === 'settings' && <SettingsPage config={config}/>}
      {page === 'security' && <SecurityPage onLogout={onLogout}/>}
    </main>
  </div>;
}

function Dashboard({ config, summary }: { config: ApiConfig; summary: TelemetrySummary }) {
  return <>
    <div className="cards">
      <div className="card"><span>模型数量</span><strong>{config.models.length}</strong></div>
      <div className="card"><span>请求总数</span><strong>{fmt(summary.total_requests)}</strong></div>
      <div className="card"><span>总 Tokens</span><strong>{fmt(summary.total_tokens)}</strong></div>
      <div className="card"><span>Reasoning Tokens</span><strong>{fmt(summary.reasoning_tokens)}</strong></div>
    </div>
    <div className="panel">
      <h2>模型消耗排行</h2>
      <SummaryTable summary={summary}/>
    </div>
  </>;
}

function SummaryTable({ summary }: { summary: TelemetrySummary }) {
  return <div className="table-wrap"><table><thead><tr><th>模型</th><th>上游</th><th>请求数</th><th>输入</th><th>输出</th><th>总计</th><th>Reasoning</th></tr></thead><tbody>
    {summary.models.map(row => <tr key={row.model_alias}><td>{row.model_alias}</td><td>{row.upstream_model}</td><td>{fmt(row.request_count)}</td><td>{fmt(row.prompt_tokens)}</td><td>{fmt(row.completion_tokens)}</td><td>{fmt(row.total_tokens)}</td><td>{fmt(row.reasoning_tokens)}</td></tr>)}
    {summary.models.length === 0 && <tr><td colSpan={7}>暂无请求消耗数据</td></tr>}
  </tbody></table></div>;
}

function ModelsPage({ config, onChanged, setToast }: { config: ApiConfig; onChanged: () => Promise<void>; setToast: (value: string) => void }) {
  const [editing, setEditing] = useState<ModelConfig | null>(null);
  const [adding, setAdding] = useState(false);
  return <div className="panel">
    <div className="toolbar"><h2>模型列表</h2><button className="primary" onClick={() => setAdding(true)}><Plus size={16}/>添加模型</button></div>
    <div className="table-wrap"><table><thead><tr><th>Key</th><th>模型别名</th><th>上游模型</th><th>Provider</th><th>推理强度</th><th>上游地址</th><th>操作</th></tr></thead><tbody>
      {config.models.map(model => <tr key={model.key}><td><strong>{model.key}</strong></td><td>{model.upstream_model.replace(/^(openai|anthropic|google|azure)\//, '')}</td><td>{model.upstream_model}</td><td><span className={`chip ${model.provider}`}>{model.provider}</span></td><td>{model.reasoning_effort || '-'}</td><td title={model.upstream_base || ''}>{truncate(model.upstream_base || '-')}</td><td><button className="ghost" onClick={() => setEditing(model)}>编辑</button> <button className="ghost danger" onClick={async () => { if (confirm(`删除模型 ${model.key} ?`)) { await api.deleteModel(model.key); setToast('模型已删除'); await onChanged(); } }}><Trash2 size={15}/>删除</button></td></tr>)}
    </tbody></table></div>
    {(adding || editing) && <ModelModal model={editing} onClose={() => { setAdding(false); setEditing(null); }} onSaved={async () => { setToast('模型已保存'); setAdding(false); setEditing(null); await onChanged(); }}/>}
  </div>;
}

function ModelModal({ model, onClose, onSaved }: { model: ModelConfig | null; onClose: () => void; onSaved: () => Promise<void> }) {
  const [form, setForm] = useState({ key: model?.key || '', upstream_model: model?.upstream_model || '', provider: model?.provider || '', reasoning_effort: model?.reasoning_effort || '', upstream_base: model?.upstream_base || '' });
  const [error, setError] = useState('');
  async function save() {
    setError('');
    const key = form.key.trim().toUpperCase();
    if (!/^[A-Z0-9_]+$/.test(key)) { setError('模型配置标识只能使用字母、数字、下划线，例如 GPT5_4'); return; }
    const payload = { ...form, key, provider: form.provider || null, reasoning_effort: form.reasoning_effort || null, upstream_base: form.upstream_base || null };
    try {
      if (model) await api.updateModel(model.key, payload);
      else await api.createModel(payload);
      await onSaved();
    } catch (err: any) { setError(err.message); }
  }
  return <div className="modal-backdrop"><div className="modal"><h2>{model ? '编辑模型' : '添加模型'}</h2>{error && <div className="error">{error}</div>}<div className="modal-grid">
    <label>模型配置标识<input disabled={Boolean(model)} value={form.key} onChange={e => setForm({ ...form, key: e.target.value })}/></label>
    <label>Provider<select value={form.provider} onChange={e => setForm({ ...form, provider: e.target.value })}><option value="">自动识别</option><option value="openai">OpenAI-compatible</option><option value="anthropic">Anthropic</option></select></label>
    <label>上游模型名<input value={form.upstream_model} onChange={e => setForm({ ...form, upstream_model: e.target.value })}/></label>
    <label>推理强度<select value={form.reasoning_effort} onChange={e => setForm({ ...form, reasoning_effort: e.target.value })}><option value="">不设置</option><option value="none">none</option><option value="low">low</option><option value="medium">medium</option><option value="high">high</option></select></label>
    <label style={{ gridColumn: '1 / -1' }}>上游地址覆盖<input value={form.upstream_base} onChange={e => setForm({ ...form, upstream_base: e.target.value })}/></label>
  </div><div className="table-actions"><button className="ghost" onClick={onClose}>取消</button><button className="primary" onClick={save}>保存</button></div></div></div>;
}

function KeysPage({ config, onChanged, setToast }: { config: ApiConfig; onChanged: () => Promise<void>; setToast: (value: string) => void }) {
  const [provider, setProvider] = useState('openai');
  const [newKey, setNewKey] = useState('');
  const keys = config.api_keys?.[provider] || [];
  return <div className="panel">
    <div className="toolbar"><h2>上游 API Key</h2><div className="table-actions"><button className={provider === 'openai' ? 'primary' : 'ghost'} onClick={() => setProvider('openai')}>OpenAI</button><button className={provider === 'anthropic' ? 'primary' : 'ghost'} onClick={() => setProvider('anthropic')}>Anthropic</button></div></div>
    <div className="table-wrap"><table><thead><tr><th>序号</th><th>Key</th><th>操作</th></tr></thead><tbody>{keys.map((key, index) => <tr key={`${key}-${index}`}><td>{index + 1}</td><td><code>{key}</code></td><td><button className="ghost danger" onClick={async () => { await api.deleteProviderKey(provider, index); setToast('API Key 已删除'); await onChanged(); }}>删除</button></td></tr>)}{keys.length === 0 && <tr><td colSpan={3}>暂无 API Key</td></tr>}</tbody></table></div>
    <div className="inline-form"><label>添加新的上游 API Key<input value={newKey} onChange={e => setNewKey(e.target.value)} placeholder="sk-..."/></label><button className="primary" onClick={async () => { if (!newKey.trim()) return; await api.addProviderKey(provider, newKey.trim()); setNewKey(''); setToast('API Key 已添加'); await onChanged(); }}>添加 Key</button></div>
  </div>;
}

function LogsPage({ logs, summary }: { logs: RequestLog[]; summary: TelemetrySummary }) {
  return <><div className="panel"><h2>模型消耗汇总</h2><SummaryTable summary={summary}/></div><div className="panel"><h2>请求日志（SQLite 持久化）</h2><div className="table-wrap"><table><thead><tr><th>时间</th><th>客户端</th><th>模型</th><th>上游</th><th>状态</th><th>耗时</th><th>Tokens</th><th>请求 ID</th><th>错误</th></tr></thead><tbody>{logs.map((row, index) => <tr key={index}><td>{fmtTime(row.timestamp)}</td><td>{row.remote_addr || '-'}</td><td>{row.model_alias}</td><td>{truncate(row.upstream_model, 34)}</td><td>{row.status_code || '-'}</td><td>{row.duration_s == null ? '-' : `${row.duration_s.toFixed(3)}s`}</td><td>{fmt(row.usage?.total_tokens)}</td><td>{truncate(row.client_request_id || '-', 24)}</td><td>{row.error_type ? <span className="chip error">{row.error_type}</span> : '-'}</td></tr>)}{logs.length === 0 && <tr><td colSpan={9}>暂无请求日志</td></tr>}</tbody></table></div></div></>;
}

function SettingsPage({ config }: { config: ApiConfig }) {
  const entries = useMemo(() => Object.entries(config.settings || {}), [config.settings]);
  return <div className="grid-two"><div className="panel"><h2>运行配置</h2><div className="table-wrap"><table><thead><tr><th>配置项</th><th>值</th></tr></thead><tbody>{entries.map(([key, value]) => <tr key={key}><td>{key}</td><td>{value}</td></tr>)}</tbody></table></div></div><div className="panel"><h2>数据存储</h2><p><Database/> 请求日志已写入 SQLite。默认路径：<code>data/telemetry.sqlite3</code>，可通过 <code>TELEMETRY_DB_PATH</code> 覆盖。</p></div></div>;
}

function SecurityPage({ onLogout }: { onLogout: () => void }) {
  const [oldPassword, setOldPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setMessage('');
    setError('');
    if (newPassword.length < 8) {
      setError('新密码至少 8 位');
      return;
    }
    if (newPassword !== confirmPassword) {
      setError('两次输入的新密码不一致');
      return;
    }
    try {
      await api.changePassword(oldPassword, newPassword);
      setMessage('密码已修改，请使用新密码重新登录。');
      window.setTimeout(onLogout, 900);
    } catch (err: any) {
      setError(err.message || '修改失败');
    }
  }

  return <div className="panel" style={{ maxWidth: 620 }}>
    <h2>修改管理员密码</h2>
    <p>密码会写入当前 `.env` 的 <code>ADMIN_PASSWORD</code>。修改成功后需要重新登录。</p>
    <form onSubmit={submit}>
      <label>旧密码<input type="password" value={oldPassword} onChange={e => setOldPassword(e.target.value)} autoComplete="current-password"/></label>
      <label>新密码<input type="password" value={newPassword} onChange={e => setNewPassword(e.target.value)} autoComplete="new-password"/></label>
      <label>确认新密码<input type="password" value={confirmPassword} onChange={e => setConfirmPassword(e.target.value)} autoComplete="new-password"/></label>
      {error && <div className="error">{error}</div>}
      {message && <div className="success">{message}</div>}
      <button className="primary"><LockKeyhole size={16}/>修改密码</button>
    </form>
  </div>;
}

createRoot(document.getElementById('root')!).render(<App />);
