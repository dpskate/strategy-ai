import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import { ResearchJob, ResearchResult } from "./api";

type GeneLib = {
  entry: Record<string, { desc: string; params: Record<string, number[]>; type: string }>;
  exit: Record<string, { desc: string; params: Record<string, number[]> }>;
} | null;

interface AppState {
  // Research tab — completed job
  researchJob: ResearchJob | null;
  setResearchJob: (job: ResearchJob | null) => void;

  // Optimize tab source
  optimizeDna: ResearchResult["dna"] | undefined;
  optimizeCode: string | undefined;
  optimizeDesc: string | undefined;
  setOptimizeSource: (dna?: ResearchResult["dna"], code?: string, desc?: string) => void;

  // Optimize results
  optJob: ResearchJob | null;
  optGeneLib: GeneLib;
  optSourceGenes: string[];
  optSymbol: string;
  optInterval: string;
  setOptJob: (job: ResearchJob | null) => void;
  setOptResults: (job: ResearchJob | null, geneLib: GeneLib, sourceGenes: string[], symbol: string, interval: string) => void;

  // Clear all research + optimize state
  resetAll: () => void;
  // Clear only optimize source (DNA/code/desc)
  resetOptimizeSource: () => void;
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      researchJob: null,
      setResearchJob: (job) => set({ researchJob: job }),

      optimizeDna: undefined,
      optimizeCode: undefined,
      optimizeDesc: undefined,
      setOptimizeSource: (dna, code, desc) =>
        set({ optimizeDna: dna, optimizeCode: code, optimizeDesc: desc }),

      optJob: null,
      optGeneLib: null,
      optSourceGenes: [],
      optSymbol: "BTCUSDT",
      optInterval: "4h",
      setOptJob: (job) => set({ optJob: job }),
      setOptResults: (job, geneLib, sourceGenes, symbol, interval) =>
        set({ optJob: job, optGeneLib: geneLib, optSourceGenes: sourceGenes, optSymbol: symbol, optInterval: interval }),

      resetAll: () =>
        set({
          researchJob: null,
          optimizeDna: undefined,
          optimizeCode: undefined,
          optimizeDesc: undefined,
          optJob: null,
          optGeneLib: null,
          optSourceGenes: [],
        }),
      resetOptimizeSource: () =>
        set({ optimizeDna: undefined, optimizeCode: undefined, optimizeDesc: undefined }),
    }),
    {
      name: "strategy-ai-store",
      storage: createJSONStorage(() =>
        typeof window !== "undefined" ? sessionStorage : (undefined as never)
      ),
    }
  )
);
