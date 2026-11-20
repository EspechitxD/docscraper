export {};

declare global {
  interface Window {
    cpmh?: {
      getSession: () => Promise<{ apiBase: string; token: string }>;
      pickDirectory: () => Promise<string | null>;
      openPath: (target: string) => Promise<string>;
      browserAttach: (bounds: { x: number; y: number; width: number; height: number } | null) => Promise<void>;
      browserNavigate: (url: string) => Promise<{ url: string; title: string }>;
      browserBack: () => Promise<void>;
      browserForward: () => Promise<void>;
      browserReload: () => Promise<void>;
      browserZoom: (factor: number) => Promise<number>;
      browserState: () => Promise<{ url: string; title: string; canBack: boolean; canForward: boolean; loading: boolean }>;
    };
  }
}
