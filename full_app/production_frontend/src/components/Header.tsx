import { Sparkles, Code, Film } from "lucide-react";

export function Header() {
  return (
    <div className="space-y-3 py-2">
      <div className="text-center space-y-3">
        <div className="flex items-center justify-center gap-3">
          <div className="p-2.5 bg-gradient-to-br from-purple-600/20 to-pink-600/20 rounded-xl border border-purple-500/20">
            <Film className="w-8 h-8 text-purple-400" />
          </div>
          <h1 className="text-3xl sm:text-4xl font-bold bg-gradient-to-r from-purple-400 via-pink-400 to-purple-400 bg-clip-text text-transparent">
            AI Video Editor
          </h1>
        </div>

        <div className="flex items-center justify-center gap-4 text-sm text-muted-foreground">
          <div className="flex items-center gap-1.5">
            <Code className="w-3.5 h-3.5 text-blue-400" />
            <span>FFmpeg</span>
          </div>
          <span className="text-border">+</span>
          <div className="flex items-center gap-1.5">
            <Sparkles className="w-3.5 h-3.5 text-yellow-400" />
            <span>Gemini AI</span>
          </div>
        </div>
      </div>
    </div>
  );
}
