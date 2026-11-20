export const ACCESS_STATES: Record<string, string> = {
  ACCESS_GRANTED: "Acesso aberto",
  CAPTCHA_DETECTED: "CAPTCHA detectado",
  HUMAN_VERIFICATION_REQUIRED: "Verificação humana",
  AUTHENTICATION_REQUIRED: "Autenticação exigida",
  ACCESS_DENIED: "Acesso negado",
  RATE_LIMITED: "Limite de pedidos",
  UNKNOWN_BLOCK: "Bloqueio não classificado",
  NAVIGATION_ERROR: "Falha de rede",
  JAVASCRIPT_REQUIRED: "JavaScript obrigatório",
  SESSION_EXPIRED: "Sessão expirada",
  BROWSER_ERROR: "Erro do navegador",
};

export const ACCESS_METHODS: Record<string, string> = {
  capture: "Captura da URL",
  human_verification: "Verificação humana no site",
  manual_login: "Login manual no navegador",
  human_browser: "Abrir no navegador integrado",
  wait: "Esperar e retomar manualmente",
  recheck: "Nova checagem",
  public_pdf: "PDF público indicado pela página",
  import_file: "Importar o arquivo",
};

export const ACCESS_MECHANISMS: Record<string, string> = {
  captcha: "CAPTCHA",
  cloudflare_challenge: "Desafio Cloudflare",
  rate_limit: "Limite de pedidos",
  javascript_required: "JavaScript obrigatório",
  session_expired: "Sessão expirada",
  authentication: "Autenticação",
  access_denied: "Bloqueio de acesso",
  network: "Falha de rede",
  browser: "Erro do navegador",
  robots: "robots.txt",
  none: "Nenhum",
  unknown: "Não classificado",
};

export const ACCESS_PROVIDERS: Record<string, string> = {
  recaptcha_v2: "Google reCAPTCHA",
  hcaptcha: "hCaptcha",
  turnstile: "Cloudflare Turnstile",
  cloudflare_challenge: "Desafio Cloudflare",
  unknown: "Não identificado",
  none: "—",
};

export const STATES: Record<string, string> = {
  draft: "Rascunho",
  queued: "Aguardando",
  validating: "Validando",
  capturing: "Capturando",
  processing: "Processando",
  ocr: "OCR",
  structuring: "Reconhecendo estrutura",
  extracting_images: "Extraindo imagens",
  translating: "Traduzindo",
  reconstructing: "Reconstruindo",
  awaiting_review: "Aguardando revisão",
  exporting: "Exportando",
  completed: "Concluído",
  paused: "Pausado",
  cancelled: "Cancelado",
  failed: "Falhou",
  inconclusive: "Inconclusivo",
  active: "Ativo",
  archived: "Arquivado",
};

export const CATEGORIES: { id: string; label: string }[] = [
  { id: "title", label: "Título" },
  { id: "subtitle", label: "Subtítulo" },
  { id: "paragraph", label: "Parágrafo" },
  { id: "running_text", label: "Texto corrido" },
  { id: "header", label: "Cabeçalho" },
  { id: "footer", label: "Rodapé" },
  { id: "page_number", label: "Numeração" },
  { id: "image", label: "Imagem" },
  { id: "photograph", label: "Fotografia" },
  { id: "chart", label: "Gráfico" },
  { id: "table", label: "Tabela" },
  { id: "formula", label: "Fórmula" },
  { id: "caption", label: "Legenda" },
  { id: "footnote", label: "Nota de rodapé" },
  { id: "reference", label: "Referência" },
  { id: "equation", label: "Equação" },
  { id: "diagram", label: "Diagrama" },
  { id: "unknown", label: "Área desconhecida" },
];

export function stateLabel(value: string): string {
  return STATES[value] || value || "—";
}

export function nextStep(state: string): string {
  if (state === "draft") return "Ainda não extraído. Clique em Extrair.";
  if (state === "queued") return "Na fila. A extração começa em seguida.";
  if (state === "paused") return "Pausado. Abra o documento para ver o motivo.";
  if (state === "failed") return "A extração não concluiu. Clique em Extrair de novo.";
  if (state === "awaiting_review" || state === "completed") return "Extraído. Pergunte em Knowledge AI.";
  if (state === "inconclusive") return "Extraído em parte. Confira antes de perguntar.";
  if (state === "cancelled") return "Cancelado.";
  if (isActiveState(state)) return `${stateLabel(state)}. A barra mostra o andamento.`;
  return stateLabel(state);
}

export function categoryLabel(value: string): string {
  return CATEGORIES.find((item) => item.id === value)?.label || value;
}

export function formatWhen(value: string | null | undefined): string {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short",
    timeStyle: "short",
    timeZone: "America/Sao_Paulo",
  }).format(date);
}

export function formatBytes(value: number | null | undefined): string {
  if (!value && value !== 0) {
    return "—";
  }
  if (value < 1024) {
    return `${value} B`;
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  if (value < 1024 * 1024 * 1024) {
    return `${(value / (1024 * 1024)).toFixed(1)} MB`;
  }
  return `${(value / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

const ACTIVE = new Set([
  "queued",
  "validating",
  "capturing",
  "processing",
  "ocr",
  "structuring",
  "extracting_images",
  "translating",
  "reconstructing",
  "exporting",
  "paused",
]);

export function isActiveState(value: string): boolean {
  return ACTIVE.has(value);
}

export const TRANSLATION_MODES: { id: string; label: string }[] = [
  { id: "none", label: "Sem tradução" },
  { id: "selected_regions", label: "Somente regiões selecionadas" },
  { id: "document_pt_br", label: "Documento em português" },
  { id: "bilingual", label: "Original e tradução" },
];

const TRANSLATION_ALIASES: Record<string, string> = {
  full: "document_pt_br",
  portuguese: "document_pt_br",
  portuguese_only: "document_pt_br",
  selected: "selected_regions",
  selection: "selected_regions",
  side_by_side: "bilingual",
};

export function canonicalTranslationMode(value: string): string {
  return TRANSLATION_ALIASES[value] || value || "none";
}
