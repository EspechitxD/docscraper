export type Project = {
  id: string;
  name: string;
  description: string;
  status: string;
  glossary_id: string | null;
  document_count: number;
  created_at: string;
  updated_at: string;
};

export type DocumentItem = {
  id: string;
  project_id: string;
  origin: string;
  url: string;
  title: string;
  domain: string;
  source_kind: string;
  state: string;
  page_count_estimate: number | null;
  page_count: number | null;
  language: string;
  progress: number;
  error_message: string;
  priority: number;
  added_at: string;
  completed_at: string | null;
  capture_status: string;
  exported_formats: string[];
};

export type Job = {
  id: string;
  document_id: string;
  priority: number;
  state: string;
  stage: string;
  progress: number;
  attempts: number;
  error: string;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  checkpoint: Record<string, unknown>;
  options: Record<string, unknown>;
  steps: { name: string; state: string; message: string; created_at: string }[];
};

export type PageItem = {
  id: string;
  sequence: number;
  reported_number: string;
  width: number;
  height: number;
  sha256: string;
  phash: string;
  state: string;
  blank: boolean;
  partial: boolean;
  captured_at: string | null;
  source_url: string;
};

export type Region = {
  id: string;
  page_id: string;
  document_id: string;
  category: string;
  text: string;
  confidence: number;
  bbox: [number, number, number, number];
  language: string;
  review_state: string;
  source: string;
  deleted: boolean;
  original_text: string;
  original_category: string;
  original_bbox: [number, number, number, number];
  evidence?: string;
};

export type ElementItem = {
  id: string;
  kind: string;
  order: number;
  text: string;
  confidence: number;
  level: number;
  page_ids: string[];
  region_ids: string[];
  continued_from: string | null;
  continued_in: string | null;
  skip_export: boolean;
};

export type ImageItem = {
  id: string;
  name: string;
  category: string;
  caption: string;
  confidence: number;
  width: number;
  height: number;
  page_id: string;
  bbox?: [number, number, number, number];
  format?: string;
  review_state?: string;
  page_sequence?: number | null;
};

export type TableItem = {
  id: string;
  rows: string[][];
  confidence: number;
  reliable: boolean;
  review_state: string;
  notes: string;
  page_sequence: number;
};

export type FormulaItem = {
  id: string;
  text: string;
  latex: string;
  reliable: boolean;
  confidence: number;
  notes: string;
  page_id: string;
};

export type Dashboard = {
  documents_total: number;
  completed: number;
  in_progress: number;
  awaiting_review: number;
  failed: number;
  inconclusive: number;
  queue: Job[];
  recent: DocumentItem[];
};

export type Glossary = { id: string; name: string; description: string; project_id: string | null };
export type Term = { id: string; source: string; target: string; context: string; do_not_translate: boolean };
