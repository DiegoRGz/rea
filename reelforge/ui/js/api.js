// Cliente de la API local. El token llega en la URL (?token=) desde Electron.
const params = new URLSearchParams(location.search);
if (params.get("token")) {
  sessionStorage.setItem("rf-token", params.get("token"));
  history.replaceState(null, "", location.pathname + location.hash);
}
export const TOKEN = sessionStorage.getItem("rf-token") || "";

async function request(method, path, body) {
  const opts = { method, headers: { "x-reelforge-token": TOKEN } };
  if (body instanceof FormData) opts.body = body;
  else if (body !== undefined) {
    opts.headers["content-type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    let msg = data && data.detail ? data.detail : `Error ${res.status}`;
    if (Array.isArray(msg)) msg = msg.map((d) => `${(d.loc || []).slice(-1)[0]}: ${d.msg}`).join(" · ");
    throw new Error(msg);
  }
  return data;
}

export const api = {
  get: (p) => request("GET", p),
  post: (p, b = {}) => request("POST", p, b),
  put: (p, b) => request("PUT", p, b),
  patch: (p, b) => request("PATCH", p, b),
  del: (p) => request("DELETE", p),
  upload: (files) => {
    const fd = new FormData();
    for (const f of files) fd.append("files", f);
    return request("POST", "/api/media/upload", fd);
  },
};

export const fileUrl = {
  media: (id) => `/files/media/${id}?t=${encodeURIComponent(TOKEN)}`,
  thumb: (id) => `/files/thumb/${id}?t=${encodeURIComponent(TOKEN)}`,
  font: (name) => `/files/fonts/${name}?t=${encodeURIComponent(TOKEN)}`,
  export: (name) => `/files/export/${encodeURIComponent(name)}?t=${encodeURIComponent(TOKEN)}`,
  withToken: (url) => `${url}${url.includes("?") ? "&" : "?"}t=${encodeURIComponent(TOKEN)}`,
};

// ------------------------------------------------------------ trabajos
const listeners = new Set();
const waiters = new Map();
let jobs = [];
let timer = null;

export function onJobs(fn) {
  listeners.add(fn);
  fn(jobs);
  return () => listeners.delete(fn);
}

async function poll() {
  try {
    jobs = await api.get("/api/jobs");
  } catch {
    schedule(3000);
    return;
  }
  for (const fn of listeners) fn(jobs);
  for (const job of jobs) {
    const w = waiters.get(job.id);
    if (!w) continue;
    w.onProgress?.(job);
    if (job.status === "done") {
      waiters.delete(job.id);
      w.resolve(job.result);
    } else if (job.status === "error" || job.status === "cancelled") {
      waiters.delete(job.id);
      w.reject(new Error(job.status === "cancelled" ? "Cancelado" : job.error || "Error"));
    }
  }
  const active = jobs.some((j) => j.status === "running" || j.status === "queued") || waiters.size;
  schedule(active ? 700 : 4000);
}

function schedule(ms) {
  clearTimeout(timer);
  timer = setTimeout(poll, ms);
}

/** Lanza un trabajo (respuesta de un POST) y espera su resultado. */
export async function runJob(startPromise, onProgress) {
  const job = await startPromise;
  return new Promise((resolve, reject) => {
    waiters.set(job.id, { resolve, reject, onProgress });
    schedule(150);
  });
}

export const cancelJob = (id) => api.post(`/api/jobs/${id}/cancel`);
export function startPolling() {
  schedule(100);
}
