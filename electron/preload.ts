import { contextBridge, ipcRenderer } from "electron";

const api = {
  getSession: () => ipcRenderer.invoke("session") as Promise<{ apiBase: string; token: string }>,
  pickDirectory: () => ipcRenderer.invoke("pick-directory") as Promise<string | null>,
  openPath: (target: string) => ipcRenderer.invoke("open-path", target) as Promise<string>,
  browserAttach: (bounds: { x: number; y: number; width: number; height: number } | null) =>
    ipcRenderer.invoke("browser-bounds", bounds),
  browserNavigate: (url: string) => ipcRenderer.invoke("browser-navigate", url) as Promise<{ url: string; title: string }>,
  openVerification: (url: string, projectId: string, jobId: string) =>
    ipcRenderer.invoke("browser-open-verification", url, projectId, jobId) as Promise<{ url: string; title: string; partition: string }>,
  browserProbe: () =>
    ipcRenderer.invoke("browser-probe") as Promise<{ url: string; final_url: string; title: string; text: string; markers: string[]; iframes: string[]; scripts: string[]; status: number }>,
  closeVerification: (projectId: string, jobId: string) =>
    ipcRenderer.invoke("browser-close-verification", projectId, jobId) as Promise<{ closed: boolean }>,
  browserBack: () => ipcRenderer.invoke("browser-back"),
  browserForward: () => ipcRenderer.invoke("browser-forward"),
  browserReload: () => ipcRenderer.invoke("browser-reload"),
  browserZoom: (factor: number) => ipcRenderer.invoke("browser-zoom", factor),
  browserState: () =>
    ipcRenderer.invoke("browser-state") as Promise<{ url: string; title: string; canBack: boolean; canForward: boolean; loading: boolean }>,
  browserOverlay: (payload: {
    visible: boolean;
    selectedId?: string;
    categories?: string[];
    regions: { id: string; category: string; bbox: number[] }[];
  }) => ipcRenderer.invoke("browser-overlay", payload) as Promise<void>,
};

contextBridge.exposeInMainWorld("cpmh", api);

export type CpmhBridge = typeof api;
