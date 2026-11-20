import { app, BrowserWindow, dialog, ipcMain, session, shell, WebContentsView } from "electron";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import http from "node:http";
import net from "node:net";
import path from "node:path";

const isDev = !app.isPackaged;

type SessionInfo = { apiBase: string; token: string };

let backend: ChildProcessWithoutNullStreams | null = null;
let mainWindow: BrowserWindow | null = null;
let browserView: WebContentsView | null = null;
let browserPartition = "";
let sessionInfo: SessionInfo = { apiBase: "", token: "" };
let allowedBrowserUrl = "";
let lastOverlay: unknown = null;

function stopRecordedBackend(): void {
  const pidFile = path.join(app.getPath("userData"), "backend.pid");
  if (!fs.existsSync(pidFile)) {
    return;
  }
  const pid = Number(fs.readFileSync(pidFile, "utf8"));
  if (Number.isInteger(pid) && pid > 0 && pid !== process.pid) {
    try {
      process.kill(pid, "SIGTERM");
    } catch {
      /* o processo anterior já não existe */
    }
  }
  fs.rmSync(pidFile, { force: true });
}

async function installOverlay(): Promise<void> {
  const contents = browserView?.webContents;
  if (!contents) {
    return;
  }
  const source = fs.readFileSync(path.join(__dirname, "overlay.js"), "utf8");
  await contents.executeJavaScript(source);
  if (lastOverlay) {
    await contents.executeJavaScript(`window.cpmhApplyOverlay(${JSON.stringify(lastOverlay)})`);
  }
}

function projectRoot(): string {
  return path.resolve(__dirname, "..", "..");
}

function pythonLaunch(): { command: string; args: string[]; pythonPath: string } {
  const root = projectRoot();
  const posix = path.join(root, "backend", ".venv", "bin", "python");
  const win = path.join(root, "backend", ".venv", "Scripts", "python.exe");
  const bundled = path.join(process.resourcesPath, "backend", process.platform === "win32" ? "cpmh-backend.exe" : "cpmh-backend");
  if (!app.isPackaged && fs.existsSync(posix)) {
    return { command: posix, args: ["-m", "cpmh_backend"], pythonPath: path.join(root, "backend") };
  }
  if (!app.isPackaged && fs.existsSync(win)) {
    return { command: win, args: ["-m", "cpmh_backend"], pythonPath: path.join(root, "backend") };
  }
  if (app.isPackaged) {
    if (!fs.existsSync(bundled)) {
      throw new Error("O backend empacotado não foi encontrado. A instalação está incompleta e o Python do sistema não será usado.");
    }
    return { command: bundled, args: [], pythonPath: "" };
  }
  if (fs.existsSync(bundled)) {
    return { command: bundled, args: [], pythonPath: "" };
  }
  return { command: process.platform === "win32" ? "python" : "python3", args: ["-m", "cpmh_backend"], pythonPath: path.join(root, "backend") };
}

function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      server.close(() => resolve(port));
    });
  });
}

function waitForHealth(port: number, token: string): Promise<void> {
  const started = Date.now();
  return new Promise((resolve, reject) => {
    const attempt = () => {
      const request = http.request(
        {
          host: "127.0.0.1",
          port,
          path: "/api/health",
          method: "GET",
          headers: { "X-CPMH-Token": token },
          timeout: 1500,
        },
        (response) => {
          response.resume();
          if (response.statusCode === 200) {
            resolve();
            return;
          }
          retry();
        },
      );
      request.on("error", retry);
      request.on("timeout", () => request.destroy());
      request.end();
    };
    const retry = () => {
      if (Date.now() - started > 20000) {
        reject(new Error("O backend local não respondeu em 127.0.0.1."));
        return;
      }
      setTimeout(attempt, 250);
    };
    attempt();
  });
}

async function validateWithBackend(url: string): Promise<string> {
  const response = await fetch(`${sessionInfo.apiBase}/api/security/validate-url`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CPMH-Token": sessionInfo.token,
    },
    body: JSON.stringify({ url }),
  });
  if (!response.ok) {
    let message = "URL recusada.";
    try {
      const body = (await response.json()) as { detail?: { message?: string } };
      message = body.detail?.message || message;
    } catch {
      message = await response.text();
    }
    throw new Error(message);
  }
  const body = (await response.json()) as { url: string };
  return body.url;
}

function verificationPartition(projectId: string, jobId: string): string {
  if (!/^[0-9a-f-]{36}$/i.test(projectId) || !/^[0-9a-f-]{36}$/i.test(jobId)) {
    throw new Error("A sessão de verificação precisa de um projeto e de uma tarefa.");
  }
  return `persist:cpmh-${projectId}-${jobId}`;
}

function ensureBrowserView(partition = ""): WebContentsView {
  if (browserView && browserPartition === partition && mainWindow) {
    return browserView;
  }
  if (browserView && mainWindow) {
    mainWindow.contentView.removeChildView(browserView);
    browserView.webContents.close();
    browserView = null;
  }
  const view = new WebContentsView({
    webPreferences: {
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false,
      webSecurity: true,
      partition: partition || undefined,
    },
  });
  browserPartition = partition;
  view.webContents.setWindowOpenHandler(({ url }) => {
    void openAuthorized(url);
    return { action: "deny" };
  });
  view.webContents.session.setPermissionRequestHandler((_contents, _permission, callback) => {
    callback(false);
  });
  view.webContents.on("will-navigate", (event, url) => {
    if (url === allowedBrowserUrl) {
      return;
    }
    event.preventDefault();
    void openAuthorized(url);
  });
  view.webContents.on("will-redirect", (event, url) => {
    if (url === allowedBrowserUrl) {
      return;
    }
    event.preventDefault();
    void openAuthorized(url);
  });
  view.webContents.on("did-finish-load", () => {
    void installOverlay();
  });
  mainWindow?.contentView.addChildView(view);
  browserView = view;
  return view;
}

async function openAuthorized(url: string, partition = browserPartition): Promise<{ url: string; title: string }> {
  const checked = await validateWithBackend(url);
  allowedBrowserUrl = checked;
  const view = ensureBrowserView(partition);
  await view.webContents.loadURL(checked);
  return { url: view.webContents.getURL(), title: view.webContents.getTitle() };
}

function browserSnapshot() {
  const contents = browserView?.webContents;
  return {
    url: contents?.getURL() || "",
    title: contents?.getTitle() || "",
    canBack: Boolean(contents?.navigationHistory.canGoBack()),
    canForward: Boolean(contents?.navigationHistory.canGoForward()),
    loading: Boolean(contents?.isLoading()),
  };
}

async function startBackend(): Promise<void> {
  const port = await freePort();
  const token = crypto.randomBytes(32).toString("hex");
  const launch = pythonLaunch();
  const staticDir = app.isPackaged
    ? path.join(process.resourcesPath, "ui")
    : "";
  const env = {
    ...process.env,
    CPMH_API_TOKEN: token,
    CPMH_HOST: "127.0.0.1",
    CPMH_PORT: String(port),
    CPMH_STATIC_DIR: staticDir,
    PYTHONPATH: launch.pythonPath || process.env.PYTHONPATH || "",
    PYTHONUNBUFFERED: "1",
  };
  stopRecordedBackend();
  backend = spawn(launch.command, launch.args, {
    env,
    stdio: "pipe",
    windowsHide: true,
  });
  const logDir = path.join(app.getPath("userData"), "logs");
  fs.mkdirSync(logDir, { recursive: true });
  const logStream = fs.createWriteStream(path.join(logDir, "backend.log"), { flags: "a" });
  backend.stdout.on("data", (chunk: Buffer) => {
    process.stdout.write(chunk);
    logStream.write(chunk);
  });
  backend.stderr.on("data", (chunk: Buffer) => {
    process.stderr.write(chunk);
    logStream.write(chunk);
  });
  if (backend.pid) {
    fs.writeFileSync(path.join(app.getPath("userData"), "backend.pid"), String(backend.pid));
  }
  backend.on("exit", (code) => {
    if (code && code !== 0 && mainWindow && !mainWindow.isDestroyed()) {
      dialog.showErrorBox("CPMH Document Intelligence", `O backend local encerrou com código ${code}.`);
    }
  });
  await waitForHealth(port, token);
  sessionInfo = { apiBase: `http://127.0.0.1:${port}`, token };
}

function createWindow(): void {
  const icon = path.join(projectRoot(), "assets", "branding", "cpmh-mark-512.png");
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1100,
    minHeight: 680,
    title: "CPMH Document Intelligence",
    backgroundColor: "#22272A",
    icon: fs.existsSync(icon) ? icon : undefined,
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
    },
  });
  if (isDev) {
    void mainWindow.loadURL("http://127.0.0.1:5173");
  } else {
    void mainWindow.loadURL(`${sessionInfo.apiBase}/`);
  }
  mainWindow.on("closed", () => {
    mainWindow = null;
    browserView = null;
  });
}

function registerIpc(): void {
  ipcMain.handle("session", () => sessionInfo);
  ipcMain.handle("pick-directory", async () => {
    if (!mainWindow) {
      return null;
    }
    const result = await dialog.showOpenDialog(mainWindow, {
      properties: ["openDirectory", "createDirectory"],
      title: "Escolher pasta de destino",
    });
    return result.canceled ? null : result.filePaths[0];
  });
  ipcMain.handle("open-path", async (_event, target: string) => {
    const error = await shell.openPath(target);
    return error;
  });
  ipcMain.handle("browser-bounds", (_event, bounds: { x: number; y: number; width: number; height: number } | null) => {
    if (!bounds || bounds.width < 20 || bounds.height < 20) {
      if (browserView && mainWindow) {
        mainWindow.contentView.removeChildView(browserView);
      }
      return;
    }
    const view = ensureBrowserView();
    view.setBounds({
      x: Math.round(bounds.x),
      y: Math.round(bounds.y),
      width: Math.round(bounds.width),
      height: Math.round(bounds.height),
    });
  });
  ipcMain.handle("browser-navigate", (_event, url: string) => openAuthorized(url, ""));
  ipcMain.handle("browser-open-verification", async (_event, url: string, projectId: string, jobId: string) => {
    const partition = verificationPartition(projectId, jobId);
    const checked = await validateWithBackend(url);
    allowedBrowserUrl = checked;
    const view = ensureBrowserView(partition);
    await view.webContents.loadURL(checked);
    return { url: view.webContents.getURL(), title: view.webContents.getTitle(), partition };
  });
  ipcMain.handle("browser-probe", async () => {
    const contents = browserView?.webContents;
    if (!contents) {
      throw new Error("O navegador não está aberto.");
    }
    const observed = (await contents.executeJavaScript(`(() => {
      const src = (el) => el.getAttribute("src") || "";
      const selectors = [".g-recaptcha", "#g-recaptcha-response", ".h-captcha", ".cf-turnstile", "#challenge-form", ".cf-browser-verification", "input[type='password']", "#captcha", ".captcha"];
      return {
        title: document.title || "",
        text: document.body ? document.body.innerText.slice(0, 1500) : "",
        iframes: Array.from(document.querySelectorAll("iframe")).map(src).filter(Boolean).slice(0, 20),
        scripts: Array.from(document.querySelectorAll("script")).map(src).filter(Boolean).slice(0, 30),
        markers: selectors.filter((selector) => document.querySelector(selector))
      };
    })()`)) as { title: string; text: string; iframes: string[]; scripts: string[]; markers: string[] };
    return { ...observed, url: contents.getURL(), final_url: contents.getURL(), status: 0 };
  });
  ipcMain.handle("browser-close-verification", async (_event, projectId: string, jobId: string) => {
    const partition = verificationPartition(projectId, jobId);
    await session.fromPartition(partition).clearStorageData();
    if (browserPartition === partition && browserView && mainWindow) {
      mainWindow.contentView.removeChildView(browserView);
      browserView.webContents.close();
      browserView = null;
      browserPartition = "";
    }
    return { closed: true };
  });
  ipcMain.handle("browser-back", () => {
    const history = browserView?.webContents.navigationHistory;
    if (history?.canGoBack()) {
      history.goBack();
    }
    return browserSnapshot();
  });
  ipcMain.handle("browser-forward", () => {
    const history = browserView?.webContents.navigationHistory;
    if (history?.canGoForward()) {
      history.goForward();
    }
    return browserSnapshot();
  });
  ipcMain.handle("browser-reload", () => {
    browserView?.webContents.reload();
    return browserSnapshot();
  });
  ipcMain.handle("browser-zoom", (_event, factor: number) => {
    const next = Math.min(2, Math.max(0.5, Number(factor) || 1));
    browserView?.webContents.setZoomFactor(next);
    return next;
  });
  ipcMain.handle("browser-state", () => browserSnapshot());
  ipcMain.handle("browser-overlay", async (_event, payload: unknown) => {
    lastOverlay = payload;
    if (!browserView) {
      return;
    }
    await installOverlay();
  });
}

app.whenReady().then(async () => {
  app.setName("CPMH Document Intelligence");
  registerIpc();
  try {
    await startBackend();
  } catch (error) {
    dialog.showErrorBox(
      "CPMH Document Intelligence",
      error instanceof Error ? error.message : "Falha ao iniciar o backend local.",
    );
    app.quit();
    return;
  }
  createWindow();
});

app.on("window-all-closed", () => {
  if (backend && !backend.killed) {
    backend.kill();
  }
  app.quit();
});

app.on("before-quit", () => {
  if (backend && !backend.killed) {
    backend.kill();
  }
});
