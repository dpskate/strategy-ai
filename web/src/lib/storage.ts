import { Metrics } from "./api";

export interface SavedStrategy {
  id: string;
  name: string;
  code: string;
  grade?: string;
  score?: number;
  metrics?: Metrics;
  walkForward?: { train_roi: number; test_roi: number; overfit_ratio: number };
  settings?: {
    symbol?: string;
    interval?: string;
    sl?: number;
    tp?: number;
  };
  source: "backtest" | "research" | "optimize" | "import";
  savedAt: number; // timestamp
}

const STORAGE_KEY = "strategy_ai_saved";

export function loadStrategies(): SavedStrategy[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

export function saveStrategy(s: SavedStrategy): SavedStrategy[] {
  const list = loadStrategies();
  list.unshift(s);
  // Max 50
  const trimmed = list.slice(0, 50);
  localStorage.setItem(STORAGE_KEY, JSON.stringify(trimmed));
  return trimmed;
}

export function deleteStrategy(id: string): SavedStrategy[] {
  const list = loadStrategies().filter((s) => s.id !== id);
  localStorage.setItem(STORAGE_KEY, JSON.stringify(list));
  return list;
}

export function exportStrategies(strategies: SavedStrategy[]): string {
  return JSON.stringify(strategies, null, 2);
}

export function importStrategies(json: string): SavedStrategy[] {
  const imported: SavedStrategy[] = JSON.parse(json);
  const existing = loadStrategies();
  const existingIds = new Set(existing.map((s) => s.id));
  const newOnes = imported.filter((s) => !existingIds.has(s.id));
  const merged = [...newOnes, ...existing].slice(0, 50);
  localStorage.setItem(STORAGE_KEY, JSON.stringify(merged));
  return merged;
}

export function genId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
}
