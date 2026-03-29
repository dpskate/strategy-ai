"use client";

import { useState, useEffect, useRef } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  SavedStrategy,
  loadStrategies,
  deleteStrategy,
  exportStrategies,
  importStrategies,
} from "@/lib/storage";
import {
  Bookmark,
  Trash2,
  Download,
  Upload,
  Play,
  ChevronDown,
  ChevronUp,
} from "lucide-react";

const gradeColor: Record<string, string> = {
  A: "bg-emerald-600",
  B: "bg-blue-600",
  C: "bg-yellow-600",
  D: "bg-orange-600",
  F: "bg-red-600",
};

export function SavedStrategiesPanel({
  onLoad,
}: {
  onLoad: (code: string, opts?: { sl?: number; tp?: number }) => void;
}) {
  const [strategies, setStrategies] = useState<SavedStrategy[]>([]);
  const [expanded, setExpanded] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setStrategies(loadStrategies());
  }, []);

  // Refresh when storage changes from other tabs/components
  useEffect(() => {
    const handler = () => setStrategies(loadStrategies());
    window.addEventListener("strategies-updated", handler);
    return () => window.removeEventListener("strategies-updated", handler);
  }, []);

  const handleDelete = (id: string) => {
    const updated = deleteStrategy(id);
    setStrategies(updated);
  };

  const handleExport = () => {
    const json = exportStrategies(strategies);
    const blob = new Blob([json], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `strategies_${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleImport = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const updated = importStrategies(reader.result as string);
        setStrategies(updated);
      } catch {
        alert("匯入失敗：檔案格式不正確");
      }
    };
    reader.readAsText(file);
    e.target.value = "";
  };

  if (strategies.length === 0 && !expanded) return null;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle
          className="text-base flex items-center justify-between cursor-pointer"
          onClick={() => setExpanded(!expanded)}
        >
          <span className="flex items-center gap-2">
            <Bookmark className="h-4 w-4" />
            已儲存策略
            {strategies.length > 0 && (
              <Badge variant="secondary" className="text-xs">
                {strategies.length}
              </Badge>
            )}
          </span>
          {expanded ? (
            <ChevronUp className="h-4 w-4" />
          ) : (
            <ChevronDown className="h-4 w-4" />
          )}
        </CardTitle>
      </CardHeader>
      {expanded && (
        <CardContent className="space-y-3">
          {/* Actions */}
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={handleExport} disabled={strategies.length === 0}>
              <Download className="h-3 w-3 mr-1" />
              匯出
            </Button>
            <Button variant="outline" size="sm" onClick={() => fileRef.current?.click()}>
              <Upload className="h-3 w-3 mr-1" />
              匯入
            </Button>
            <input ref={fileRef} type="file" accept=".json" className="hidden" onChange={handleImport} />
          </div>

          {/* List */}
          {strategies.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-4">
              還沒有儲存的策略。回測或研發後點「儲存」即可。
            </p>
          ) : (
            <div className="space-y-2 max-h-[400px] overflow-y-auto">
              {strategies.map((s) => (
                <div
                  key={s.id}
                  className="flex items-center gap-3 p-3 rounded-lg bg-muted/50 group"
                >
                  {/* Grade badge */}
                  {s.grade && (
                    <div
                      className={`w-8 h-8 rounded-md flex items-center justify-center text-white text-sm font-bold ${gradeColor[s.grade] || "bg-gray-600"}`}
                    >
                      {s.grade}
                    </div>
                  )}
                  {/* Info */}
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate">{s.name}</p>
                    <div className="flex items-center gap-2 text-xs text-muted-foreground">
                      {s.metrics && (
                        <>
                          <span className={s.metrics.roi_pct >= 0 ? "text-emerald-400" : "text-red-400"}>
                            ROI {s.metrics.roi_pct}%
                          </span>
                          <span>·</span>
                          <span>勝率 {s.metrics.win_rate}%</span>
                          <span>·</span>
                          <span>PF {s.metrics.profit_factor}</span>
                        </>
                      )}
                      {s.settings?.symbol && (
                        <>
                          <span>·</span>
                          <span>{s.settings.symbol}</span>
                        </>
                      )}
                    </div>
                  </div>
                  {/* Actions */}
                  <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 w-7 p-0"
                      onClick={() => onLoad(s.code, { sl: s.settings?.sl, tp: s.settings?.tp })}
                      title="載入回測"
                    >
                      <Play className="h-3 w-3" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 w-7 p-0 text-red-400 hover:text-red-300"
                      onClick={() => handleDelete(s.id)}
                      title="刪除"
                    >
                      <Trash2 className="h-3 w-3" />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      )}
    </Card>
  );
}
