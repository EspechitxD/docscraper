import { contextBridge, ipcRenderer } from "electron";

const api = {
  getSession: () => ipcRenderer.invoke("session") as Promise<{ apiBase: string; token: string }>,
  pickDirectory: () => ipcRenderer.invoke("pick-directory") as Promise<string | null>,
  openPath: (target: string) => ipcRenderer.invoke("open-path", target) as Promise<string>,
  browserAttach: (bounds: { x: number; y: number; width: number; height: number } | null) =>
    ipcRenderer.invoke("browser-bounds", bounds),
  browserNavigate: (url: string) => ipcRenderer.invoke("browser-navigate", url) as Promise<{ url: string; title: string }>,
  browserBack: () => ipcRenderer.invoke("browser-back"),
  browserForward: () => ipcRenderer.invoke("browser-forward"),
  browserReload: () => ipcRenderer.invoke("browser-reload"),
  browserZoom: (factor: number) => ipcRenderer.invoke("browser-zoom", factor),
  browserState: () =>
    ipcRenderer.invoke("browser-state") as Promise<{ url: string; title: string; canBack: boolean; canForward: boolean; loading: boolean }>,
};

contextBridge.exposeInMainWorld("cpmh", api);

export type CpmhBridge = typeof api;
