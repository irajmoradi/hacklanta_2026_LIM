import { Play } from "lucide-react";
import { useEffect, useRef } from "react";

interface VideoPreviewProps {
  videoUrl: string;
  title?: string;
  seekTo?: number;
}

export function VideoPreview({ videoUrl, title, seekTo }: VideoPreviewProps) {
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    if (videoRef.current) {
      videoRef.current.load();
    }
  }, [videoUrl]);

  useEffect(() => {
    if (videoRef.current && seekTo !== undefined && seekTo >= 0) {
      videoRef.current.currentTime = seekTo;
      videoRef.current.play().catch(() => {});
    }
  }, [seekTo]);

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <div className="p-1 bg-green-600/20 rounded">
          <Play className="w-4 h-4 text-green-400" />
        </div>
        <h3 className="text-sm font-semibold">{title || "Video Preview"}</h3>
      </div>

      <div className="relative bg-black rounded-xl overflow-hidden aspect-video border border-border shadow-lg shadow-black/30">
        <video
          ref={videoRef}
          controls
          className="w-full h-full"
          src={videoUrl}
        >
          Your browser does not support the video tag.
        </video>
      </div>
    </div>
  );
}
