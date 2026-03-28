import { Download } from "lucide-react";
import { Button } from "./ui/button";

interface DownloadButtonProps {
  downloadUrl: string;
  disabled?: boolean;
}

export function DownloadButton({ downloadUrl, disabled }: DownloadButtonProps) {
  const handleDownload = () => {
    const a = document.createElement("a");
    a.href = downloadUrl;
    a.download = "edited_video.mp4";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  return (
    <Button
      onClick={handleDownload}
      disabled={disabled}
      className="w-full bg-green-600 hover:bg-green-700 text-white h-12 text-base shadow-lg shadow-green-600/20"
      size="lg"
    >
      <Download className="w-5 h-5 mr-2" />
      Download Edited Video
    </Button>
  );
}
