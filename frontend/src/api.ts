export type ApiError = { status: number; code: string; message: string; path?: string };

let apiBase = "";
let token = "";

export function configureApi(next: { apiBase: string; token: string }): void {
  apiBase = next.apiBase.replace(/\/$/, "");
  token = next.token;
}

export function apiOrigin(): string {
  return apiBase;
}

export function hasDesktopBridge(): boolean {
  return typeof window !== "undefined" && Boolean(window.cpmh);
}

async function parseError(response: Response): Promise<ApiError> {
  let code = "error";
  let message = response.statusText || "Falha na comunicação com o backend.";
  let path = "";
  try {
    const body = await response.json();
    const detail = body.detail ?? body;
    if (typeof detail === "string") {
      message = detail;
    } else if (detail && typeof detail === "object") {
      code = detail.code || code;
      message = detail.message || message;
      path = detail.path || "";
    }
  } catch {
    message = (await response.text()) || message;
  }
  return { status: response.status, code, message, path };
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("X-CPMH-Token", token);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${apiBase}/api${path}`, { ...init, headers });
  if (!response.ok) {
    throw await parseError(response);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  const type = response.headers.get("content-type") || "";
  if (type.includes("application/json")) {
    return (await response.json()) as T;
  }
  return (await response.text()) as T;
}

export async function apiDownload(path: string, init: RequestInit = {}): Promise<{ blob: Blob; filename: string }> {
  const headers = new Headers(init.headers);
  headers.set("X-CPMH-Token", token);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${apiBase}/api${path}`, { ...init, headers });
  if (!response.ok) {
    throw await parseError(response);
  }
  const blob = await response.blob();
  return { blob, filename: filenameFromDisposition(response.headers.get("content-disposition") || "", blob.type) };
}

function filenameFromDisposition(header: string, blobType: string): string {
  const encoded = /filename\*=(?:UTF-8''|utf-8'')([^;]+)/i.exec(header);
  if (encoded?.[1]) {
    try {
      return decodeURIComponent(encoded[1].trim().replace(/"/g, ""));
    } catch {
      return encoded[1].trim();
    }
  }
  const quoted = /filename="([^"]+)"/i.exec(header);
  if (quoted?.[1]) return quoted[1];
  const plain = /filename=([^;]+)/i.exec(header);
  if (plain?.[1]) return plain[1].trim().replace(/^"|"$/g, "");
  const ext = blobType.includes("pdf") ? "pdf" : blobType.includes("json") ? "json" : blobType.includes("zip") ? "zip" : blobType.startsWith("text/") ? "txt" : "docx";
  return `documento.${ext}`;
}

export async function apiBlob(path: string): Promise<Blob> {
  const response = await fetch(`${apiBase}/api${path}`, { headers: { "X-CPMH-Token": token } });
  if (!response.ok) {
    throw await parseError(response);
  }
  return response.blob();
}

export function isApiError(error: unknown): error is ApiError {
  return Boolean(error && typeof error === "object" && "status" in error && "message" in error);
}
