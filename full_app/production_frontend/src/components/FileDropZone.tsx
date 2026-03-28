import { Upload, Video } from "lucide-react";
import { useState, useCallback } from "react";

interface FileDropZoneProps {
  onFileSelect: (file: File) => void;
  disabled?: boolean;
}

export function FileDropZone({ onFileSelect, disabled }: FileDropZoneProps) {
  const [isDragging, setIsDragging] = useState(false);

  const handleDragOver = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      if (!disabled) setIsDragging(true);
    },
    [disabled]
  );

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      if (disabled) return;

      const files = Array.from(e.dataTransfer.files);
      const videoFile = files.find((file) => file.type.startsWith("video/"));
      if (videoFile) onFileSelect(videoFile);
    },
    [onFileSelect, disabled]
  );

  const handleFileInput = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) onFileSelect(file);
    },
    [onFileSelect]
  );

  return (
    <div
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      className={`
        relative border-2 border-dashed rounded-xl p-12 sm:p-16 text-center
        transition-all duration-300 ease-out
        ${
          isDragging
            ? "border-purple-500 bg-purple-500/10 scale-[1.01]"
            : "border-muted-foreground/20 hover:border-purple-500/50 hover:bg-purple-500/5"
        }
        ${disabled ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}
      `}
    >
      <input
        type="file"
        accept="video/*"
        onChange={handleFileInput}
        disabled={disabled}
        className="absolute inset-0 w-full h-full opacity-0 cursor-pointer disabled:cursor-not-allowed"
      />

      <div className="flex flex-col items-center gap-5">
        <div
          className={`p-5 rounded-2xl transition-all duration-300 ${
            isDragging
              ? "bg-purple-500/20 scale-110"
              : "bg-muted"
          }`}
        >
          {isDragging ? (
            <Video className="w-14 h-14 text-purple-400" />
          ) : (
            <Upload className="w-14 h-14 text-muted-foreground" />
          )}
        </div>

        <div>
          <p className="text-xl mb-1.5 font-semibold">
            {isDragging ? "Drop your video here" : "Drop a video file here"}
          </p>
          <p className="text-sm text-muted-foreground">
            or click to browse &mdash; MP4, MOV, AVI, MKV supported
          </p>
        </div>
      </div>
    </div>
  );
}
