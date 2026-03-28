import { Loader2, Clock } from "lucide-react";

interface ProgressDisplayProps {
  currentStep: number;
  stepName: string;
  status: string;
  elapsed: number;
  isComplete?: boolean;
}

export function ProgressDisplay({
  stepName,
  status,
  elapsed,
  isComplete,
}: ProgressDisplayProps) {
  const formatTime = (seconds: number) => {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return m > 0 ? `${m}m ${s}s` : `${s}s`;
  };

  return (
    <div className="bg-card/80 backdrop-blur-sm border border-border rounded-2xl p-4 sm:p-5 shadow-lg shadow-black/10 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          {!isComplete && (
            <div className="relative">
              <Loader2 className="w-5 h-5 text-purple-400 animate-spin" />
              <div className="absolute inset-0 w-5 h-5 rounded-full bg-purple-400/20 animate-ping" />
            </div>
          )}
          <div>
            <p className="text-sm font-semibold">{stepName}</p>
            <p className="text-xs text-muted-foreground">{status}</p>
          </div>
        </div>
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground font-mono tabular-nums">
          <Clock className="w-3.5 h-3.5" />
          {formatTime(elapsed)}
        </div>
      </div>

      {/* Indeterminate progress bar */}
      {!isComplete && (
        <div className="h-1.5 bg-muted rounded-full overflow-hidden">
          <div className="h-full w-1/3 bg-gradient-to-r from-purple-600 to-pink-500 rounded-full animate-indeterminate" />
        </div>
      )}
    </div>
  );
}
