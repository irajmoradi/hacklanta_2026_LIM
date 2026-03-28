import { ThumbsUp, ThumbsDown, Play, Scissors } from "lucide-react";
import { Badge } from "./ui/badge";
import type { Clip } from "../api";

interface ClipsReviewProps {
  clips: Clip[];
  onPreviewTimestamp?: (seconds: number) => void;
}

export function ClipsReview({ clips, onPreviewTimestamp }: ClipsReviewProps) {
  if (clips.length === 0) return null;

  const goodCount = clips.filter((c) => c.type === "good").length;
  const badCount = clips.filter((c) => c.type === "bad").length;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold flex items-center gap-2">
          <Scissors className="w-4 h-4 text-purple-400" />
          Found Clips ({clips.length})
        </h3>
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          <span className="flex items-center gap-1 px-2 py-0.5 bg-green-500/10 rounded-full">
            <ThumbsUp className="w-3 h-3 text-green-400" />
            <span className="text-green-400 font-medium">{goodCount}</span>
          </span>
          <span className="flex items-center gap-1 px-2 py-0.5 bg-red-500/10 rounded-full">
            <ThumbsDown className="w-3 h-3 text-red-400" />
            <span className="text-red-400 font-medium">{badCount}</span>
          </span>
        </div>
      </div>

      <div className="grid gap-2 max-h-72 overflow-y-auto pr-1 scrollbar-thin">
        {clips.map((clip, i) => (
          <button
            key={i}
            onClick={() => onPreviewTimestamp?.(clip.start_seconds)}
            className="flex items-start gap-3 p-3 bg-card border border-border rounded-lg hover:bg-accent/50 hover:border-purple-500/30 transition-all duration-150 text-left w-full group"
          >
            <Badge
              variant={clip.type === "good" ? "default" : "destructive"}
              className={`text-[10px] px-1.5 py-0.5 shrink-0 mt-0.5 ${
                clip.type === "good"
                  ? "bg-green-600/20 text-green-400 border border-green-600/30"
                  : "bg-red-600/20 text-red-400 border border-red-600/30"
              }`}
            >
              {clip.type === "good" ? (
                <ThumbsUp className="w-2.5 h-2.5" />
              ) : (
                <ThumbsDown className="w-2.5 h-2.5" />
              )}
              {clip.type}
            </Badge>

            <div className="flex-1 min-w-0">
              <p className="text-xs leading-relaxed">{clip.description}</p>
              <p className="text-[10px] text-muted-foreground/60 mt-1 font-mono">
                {clip.start} &rarr; {clip.end}
              </p>
            </div>

            <div className="flex items-center gap-1 px-2 py-1 bg-purple-600/10 rounded-md opacity-0 group-hover:opacity-100 transition-opacity shrink-0 mt-0.5">
              <Play className="w-3 h-3 text-purple-400" />
              <span className="text-[10px] text-purple-400 font-medium">
                Preview
              </span>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
