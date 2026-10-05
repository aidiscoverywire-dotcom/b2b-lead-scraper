import axios from 'axios';

/**
 * API layer for the B2B Lead Scraper frontend.
 *
 * Endpoint contract (backend: FastAPI, /api/v1 prefix):
 *   POST /api/v1/auth/register        {email, password} -> JWT
 *   POST /api/v1/auth/login           {email, password} -> JWT
 *   GET  /api/v1/settings             JWT -> {keys: {openai_key,...}, wizard_done, apollo_notice}
 *   PUT  /api/v1/settings             JWT + {key_name, value} -> 200
 *   POST /api/v1/wizard/test-openai   {key} -> 200/400
 *   POST /api/v1/wizard/test-apollo   {key} -> 200/400 + tier hint
 *   POST /api/v1/wizard/test-maps     {key} -> 200/400
 *   POST /api/v1/wizard/complete      JWT -> 200
 *   POST /api/v1/jobs                 JWT + {industry, location, max_leads, filters} -> {job_id}
 *   GET  /api/v1/jobs/{job_id}/stream SSE (?token=): lead / progress / done / error events
 *   GET  /api/v1/jobs/{job_id}        JWT -> job row (poll / resume after restart)
 *   GET  /api/v1/jobs/{job_id}/export?format=csv|xlsx -> file download (browser)
 *   POST /api/v1/jobs/{job_id}/export-disk?format=csv|xlsx -> saved to ~/Downloads (desktop app)
 *   GET  /api/v1/meta -> {desktop: bool} (desktop wrapper vs real browser)
 *
 * API base resolution:
 *   VITE_API_URL (build-time) if set, else window.location.origin (same-origin).
 * Same-origin is correct for every production target — the desktop app, the
 * Docker image and Railway all serve this frontend from the backend itself —
 * so a hard-coded localhost:8000 fallback would break Railway (dynamic PORT)
 * and any desktop run on a non-default port. For `npm run dev`, set
 * VITE_API_URL=http://localhost:8000 (see frontend/.env.example).
 *
 * SSE event contract (JSON per message event):
 *   { "type": "lead",     "lead": { name, address, phone, website, rating,
 *                                   reviews, enrichment, email, email_status,
 *                                   pitch, score } }
 *   { "type": "progress", "leads": n, "requested": m, "searches": s,
 *                        "details": d, "google_cost_usd": x,
 *                        "apollo_credits_used": c, "status": "running" }
 *   { "type": "done",     "leads": n, "requested": m, ...same counters }
 *   { "type": "error",    "message": "..." }
 * The parser is tolerant: a message without "type" that looks like a lead
 * row is treated as { type: "lead", lead: <message> }.
 */

export const API_BASE = (
  import.meta.env.VITE_API_URL || window.location.origin
).replace(/\/$/, '');
export const API_PREFIX = '/api/v1';

export const api = axios.create({
  baseURL: API_BASE + API_PREFIX,
  timeout: 30000,
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('ls_token');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

export const ENDPOINTS = {
  register: '/auth/register',
  login: '/auth/login',
  forgotPassword: '/auth/forgot-password',
  resetPassword: '/auth/reset-password',
  changePassword: '/auth/change-password',
  settings: '/settings',
  wizardTestOpenAI: '/wizard/test-openai',
  wizardTestApollo: '/wizard/test-apollo',
  wizardTestMaps: '/wizard/test-maps',
  wizardComplete: '/wizard/complete',
  searchStart: '/jobs',
  jobStream: (jobId) => `/jobs/${jobId}/stream`,
  job: (jobId) => `/jobs/${jobId}`,
  export: (jobId, format) => `/jobs/${jobId}/export?format=${format}`,
  smtpSettings: '/email/smtp',
  smtpTest: '/email/test',
  bulkEmail: (jobId) => `/jobs/${jobId}/bulk-email`,
  emailEligibleCount: (jobId) => `/jobs/${jobId}/email-eligible-count`,
  campaign: (campaignId) => `/email/campaigns/${campaignId}`,
};

function streamUrl(jobId) {
  const token = localStorage.getItem('ls_token') || '';
  return `${API_BASE}${API_PREFIX}${ENDPOINTS.jobStream(jobId)}?token=${encodeURIComponent(token)}`;
}

/** Open the SSE stream for a job. Returns the EventSource (caller closes it). */
export function openJobStream(jobId, handlers) {
  const es = new EventSource(streamUrl(jobId));
  const parse = (ev) => {
    try {
      return JSON.parse(ev.data);
    } catch {
      return null; // ignore non-JSON keep-alives
    }
  };
  // Backend sends NAMED events (event: lead / progress / done / error),
  // so onmessage would never fire — listen for each name explicitly.
  for (const name of ['lead', 'progress', 'done', 'error']) {
    es.addEventListener(name, (ev) => {
      const msg = parse(ev);
      if (msg && handlers[name]) handlers[name](msg);
    });
  }
  es.onerror = () => {
    if (handlers.error) handlers.error({ message: 'Stream connection lost. The run continues on the server — reconnect to resume.' });
  };
  return es;
}

/** Capability probe (cached): are we inside the desktop wrapper (pywebview)
 *  or a real browser? The launcher sets DESKTOP_APP=1. */
let metaCache = null;
export async function getMeta() {
  if (!metaCache) metaCache = (await api.get('/meta')).data;
  return metaCache;
}

/** Download an export file for a job (csv or xlsx).
 *
 *  Desktop app (pywebview) cannot trigger file downloads from JS — a
 *  programmatic <a download> click is silently swallowed, so the classic
 *  blob flow produces no file there. On desktop the server writes the file
 *  to ~/Downloads and we return {path, leads}; in a real browser we keep
 *  the blob + anchor download and return null.
 */
export async function downloadExport(jobId, format) {
  const meta = await getMeta();
  if (meta.desktop) {
    const res = await api.post(`/jobs/${jobId}/export-disk?format=${format}`);
    return { path: res.data.path, leads: res.data.leads };
  }
  const res = await api.get(ENDPOINTS.export(jobId, format), { responseType: 'blob' });
  const blob = new Blob([res.data], {
    type: format === 'xlsx'
      ? 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
      : 'text/csv',
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `leads-${jobId}.${format === 'xlsx' ? 'xlsx' : 'csv'}`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  return null;
}
