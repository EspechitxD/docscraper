export {};

declare global {
  interface Window {
    cpmh?: {
      getSession: () => Promise<{ apiBase: string; token: string }>;
      pickDirectory: () => Promise<string | null>;
      openPath: (target: string) => Promise<string>;
      browserAttach: (bounds: { x: number; y: number; width: number; height: number } | null) => Promise<void>;
      browserNavigate: (url: string) => Promise<{ url: string; title: string }>;
      openVerification: (url: string, projectId: string, jobId: string) => Promise<{ url: string; title: string; partition: string }>;
      browserProbe: () => Promise<{ url: string; final_url: string; title: string; text: string; markers: string[]; iframes: string[]; scripts: string[]; status: number }>;
      closeVerification: (projectId: string, jobId: string) => Promise<{ closed: boolean }>;
      browserBack: () => Promise<void>;
      browserForward: () => Promise<void>;
      browserReload: () => Promise<void>;
      browserZoom: (factor: number) => Promise<number>;
      browserState: () => Promise<{ url: string; title: string; canBack: boolean; canForward: boolean; loading: boolean }>;
      browserOverlay: (payload: {
        visible: boolean;
        selectedId?: string;
        categories?: string[];
        regions: { id: string; category: string; bbox: number[] }[];
      }) => Promise<void>;
    };
  }
}
