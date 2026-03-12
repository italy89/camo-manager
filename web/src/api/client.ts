import axios from "axios";

/* ------------------------------------------------------------------ */
/*  Types (match backend response format exactly)                      */
/* ------------------------------------------------------------------ */

export interface Profile {
  name: string;
  proxy: { host: string; port: number; type: string } | string | null;
  proxy_type: string;         // "http" | "socks5"
  note: string;
  tags: string[];
  created_at: string | null;
  last_used: string | null;
  use_count: number;
  size_bytes: number;
  viewport?: { width: number; height: number };
  history?: Array<{ action: string; timestamp: string }>;
}

export interface ProxyCheckResult {
  status: "alive" | "dead" | "no_proxy" | "invalid";
  ip?: string;
  country?: string;
  country_code?: string;
  city?: string;
  message?: string;
}

export interface BrowserStatus {
  alive: boolean;
  uptime: number;
  url: string;
}

export interface SystemSummary {
  total_profiles: number;
  with_proxy: number;
  without_proxy: number;
  last_activity: string | null;
  tags: Record<string, number>;
}

/* ------------------------------------------------------------------ */
/*  Axios instance                                                     */
/* ------------------------------------------------------------------ */

const api = axios.create({
  baseURL: "",               // same-origin; vite proxy handles /api in dev
  timeout: 30000,
});

/* ------------------------------------------------------------------ */
/*  Profiles                                                           */
/* ------------------------------------------------------------------ */

/** List all profiles, optional tag filter */
export async function listProfiles(tag?: string): Promise<Profile[]> {
  const params: Record<string, string> = {};
  if (tag) params.tag = tag;
  const res = await api.get<Profile[]>("/api/profiles", { params });
  return res.data;
}

/** Get single profile with history */
export async function getProfile(name: string): Promise<Profile> {
  const res = await api.get<Profile>(`/api/profiles/${encodeURIComponent(name)}`);
  return res.data;
}

/** Create new profile */
export async function createProfile(data: {
  name: string;
  proxy?: string | null;
  proxy_type?: string;
  note?: string;
  tags?: string[];
}): Promise<Profile> {
  const res = await api.post<Profile>("/api/profiles", data);
  return res.data;
}

/** Update existing profile (partial) */
export async function updateProfile(
  name: string,
  data: {
    proxy?: string | null;
    proxy_type?: string;
    note?: string;
    tags?: string[];
    viewport?: { width: number; height: number } | null;
  }
): Promise<Profile> {
  const res = await api.put<Profile>(
    `/api/profiles/${encodeURIComponent(name)}`,
    data
  );
  return res.data;
}

/** Delete profile */
export async function deleteProfile(name: string): Promise<void> {
  await api.delete(`/api/profiles/${encodeURIComponent(name)}`);
}

/** Bulk delete profiles */
export async function bulkDelete(names: string[]): Promise<{
  deleted: string[];
  errors: Array<{ name: string; error: string }>;
}> {
  const res = await api.post("/api/profiles/bulk/delete", { names });
  return res.data;
}

/** Import profiles from JSON file */
export async function importProfiles(file: File): Promise<{
  created: string[];
  skipped: string[];
  errors: Array<{ name?: string; error: string }>;
  total_created: number;
}> {
  const form = new FormData();
  form.append("file", file);
  const res = await api.post("/api/profiles/import", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return res.data;
}

/** Export all profiles as JSON blob */
export async function exportProfiles(): Promise<Blob> {
  const res = await api.get("/api/profiles/export", { responseType: "blob" });
  return res.data as Blob;
}

/** Check proxy status for a profile */
export async function checkProxy(name: string): Promise<ProxyCheckResult> {
  const res = await api.get<ProxyCheckResult>(
    `/api/profiles/${encodeURIComponent(name)}/check-proxy`
  );
  return res.data;
}

/* ------------------------------------------------------------------ */
/*  Browser control                                                    */
/* ------------------------------------------------------------------ */

/** Start browser for profile */
export async function startBrowser(
  name: string,
  headless?: boolean
): Promise<{ message: string; name: string; status: string }> {
  const res = await api.post(`/api/profiles/${encodeURIComponent(name)}/start`, {
    headless: headless ?? null,
  });
  return res.data;
}

/** Stop browser for profile */
export async function stopBrowser(name: string): Promise<void> {
  await api.post(`/api/profiles/${encodeURIComponent(name)}/stop`);
}

/** Show/bring browser window to front */
export async function showBrowser(name: string): Promise<void> {
  await api.post(`/api/profiles/${encodeURIComponent(name)}/show`);
}

/** Get browser status for single profile */
export async function getBrowserStatus(name: string): Promise<BrowserStatus> {
  const res = await api.get<BrowserStatus>(
    `/api/profiles/${encodeURIComponent(name)}/status`
  );
  return res.data;
}

/** Take screenshot — returns image URL (blob) */
export async function getScreenshot(name: string): Promise<string> {
  const res = await api.get(
    `/api/profiles/${encodeURIComponent(name)}/screenshot`,
    { responseType: "blob" }
  );
  return URL.createObjectURL(res.data);
}

/** Get all running browsers status.
 *  Backend returns {browsers: {name: {alive, uptime, url}}, total_running}
 *  We normalize to a Map for easy lookup.
 */
export async function getAllBrowserStatus(): Promise<
  Record<string, BrowserStatus>
> {
  const res = await api.get<{
    browsers: Record<string, BrowserStatus>;
    total_running: number;
  }>("/api/browser/status");
  return res.data.browsers;
}

/** Stop all running browsers */
export async function stopAllBrowsers(): Promise<void> {
  await api.post("/api/browser/stop-all");
}

/* ------------------------------------------------------------------ */
/*  System                                                             */
/* ------------------------------------------------------------------ */

export async function getSystemSummary(): Promise<SystemSummary> {
  const res = await api.get<SystemSummary>("/api/system/summary");
  return res.data;
}

/** Get all unique tags */
export async function getTags(): Promise<string[]> {
  const res = await api.get<{ tags: string[] }>("/api/tags");
  return res.data.tags;
}

/* ------------------------------------------------------------------ */
/*  Proxy helpers (for UI display)                                     */
/* ------------------------------------------------------------------ */

/** Parse proxy (can be string "user:pass@host:port" or object {host, port, type}) into parts */
export function parseProxyString(
  proxy: Profile["proxy"],
  proxyType: string
) {
  if (!proxy)
    return {
      type: proxyType || "http",
      host: "",
      port: undefined as number | undefined,
      username: "",
      password: "",
    };

  // Object format: {host, port, type}
  if (typeof proxy === "object") {
    return {
      type: proxy.type || proxyType || "http",
      host: proxy.host || "",
      port: proxy.port || undefined,
      username: "",
      password: "",
    };
  }

  // String format: "user:pass@host:port"
  let auth = "";
  let hostPort = proxy;

  if (proxy.includes("@")) {
    const idx = proxy.lastIndexOf("@");
    auth = proxy.substring(0, idx);
    hostPort = proxy.substring(idx + 1);
  }

  const parts = hostPort.split(":");
  const host = parts[0] || "";
  const port = parts[1] ? parseInt(parts[1], 10) : undefined;

  let username = "";
  let password = "";
  if (auth) {
    const authParts = auth.split(":", 2);
    username = authParts[0] || "";
    password = authParts[1] || "";
  }

  return { type: proxyType || "http", host, port, username, password };
}

/** Build proxy string from parts */
export function buildProxyString(
  host: string,
  port: number | undefined,
  username: string,
  password: string
): string | null {
  if (!host) return null;
  const auth = username ? `${username}${password ? ":" + password : ""}@` : "";
  return `${auth}${host}${port ? ":" + port : ""}`;
}

/** Format proxy for table display */
export function formatProxy(
  proxy: Profile["proxy"],
  proxyType?: string
): string {
  if (!proxy) return "(no proxy)";
  const p = parseProxyString(proxy, proxyType || "http");
  const auth = p.username ? `${p.username}:***@` : "";
  return `${p.type}://${auth}${p.host}:${p.port ?? "?"}`;
}
