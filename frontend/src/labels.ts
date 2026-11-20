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
