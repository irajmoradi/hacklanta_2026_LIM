import { useState, useRef, useCallback, useEffect } from "react";
import { Header } from "./components/Header";
import { FileDropZone } from "./components/FileDropZone";
import { AttitudeSelector } from "./components/AttitudeSelector";
import { ProgressDisplay } from "./components/ProgressDisplay";
import { PipelineStepper } from "./components/PipelineStepper";
import { ClipsReview } from "./components/ClipsReview";
import { VideoPreview } from "./components/VideoPreview";
import { DownloadButton } from "./components/DownloadButton";
import { ErrorDisplay } from "./components/ErrorDisplay";
import { Button } from "./components/ui/button";
import { Label } from "./components/ui/label";
import { Input } from "./components/ui/input";
import { Textarea } from "./components/ui/textarea";
import { Checkbox } from "./components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "./components/ui/select";
import {
  FileVideo,
  Scissors,
  Wand2,
  Clapperboard,
  RotateCcw,
  Sparkles,
  Upload,
  ChevronDown,
  ChevronUp,
  Key,
} from "lucide-react";

import * as api from "./api";
import type { Clip, EditPlan } from "./api";

type PipelineStep =
  | "idle"
  | "uploading"
  | "analyzing"
  | "planning"
  | "rendering"
  | "done";

export default function App() {
  // API key state
  const [needsApiKey, setNeedsApiKey] = useState(false);
  const [apiKey, setApiKeyState] = useState("");
  const [apiKeySet, setApiKeySet] = useState(false);

  // Check if server has API key on mount
  useEffect(() => {
    api.fetchInfo().then((info) => {
      if (!info.has_api_key) {
        setNeedsApiKey(true);
      }
    }).catch(() => {});
  }, []);

  const handleSetApiKey = () => {
    if (!apiKey.trim()) return;
    api.setApiKey(apiKey.trim());
    setApiKeySet(true);
  };

  // File & job state
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [videoMeta, setVideoMeta] = useState<api.UploadResult["meta"] | null>(
    null
  );

  // Pipeline state
  const [step, setStep] = useState<PipelineStep>("idle");
  const [stepIndex, setStepIndex] = useState(0);
  const [stepStatus, setStepStatus] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Config
  const [attitude, setAttitude] = useState<"nice" | "mean">("nice");
  const [splits, setSplits] = useState("4");
  const [prompt, setPrompt] = useState("");
  const [editStyle, setEditStyle] = useState("hype_montage");
  const [maxDuration, setMaxDuration] = useState("60");
  const [generateThumbnails, setGenerateThumbnails] = useState(false);

  // Results
  const [clips, setClips] = useState<Clip[]>([]);
  const [editPlan, setEditPlan] = useState<EditPlan | null>(null);
  const [editPlanJson, setEditPlanJson] = useState("");
  const [downloadUrl, setDownloadUrl] = useState<string | null>(null);
  const [previewSeek, setPreviewSeek] = useState<number | undefined>(
    undefined
  );

  // Error
  const [error, setError] = useState<string | null>(null);

  // Completed steps tracking
  const [uploadDone, setUploadDone] = useState(false);
  const [analyzeDone, setAnalyzeDone] = useState(false);
  const [planDone, setPlanDone] = useState(false);

  // UI state
  const [editPlanExpanded, setEditPlanExpanded] = useState(false);

  // Timer helpers
  const startTimer = useCallback(() => {
    setElapsed(0);
    if (timerRef.current) clearInterval(timerRef.current);
    const start = Date.now();
    timerRef.current = setInterval(() => {
      setElapsed((Date.now() - start) / 1000);
    }, 100);
  }, []);

  const stopTimer = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  useEffect(() => {
    return () => stopTimer();
  }, [stopTimer]);

  // ---- PIPELINE ACTIONS ----

  const handleFileSelect = (file: File) => {
    setSelectedFile(file);
    setError(null);
    setJobId(null);
    setVideoMeta(null);
    setClips([]);
    setEditPlan(null);
    setEditPlanJson("");
    setDownloadUrl(null);
    setUploadDone(false);
    setAnalyzeDone(false);
    setPlanDone(false);
    setStep("idle");
    setStepIndex(0);
  };

  const handleUpload = async () => {
    if (!selectedFile) return;
    setError(null);
    setStep("uploading");
    setStepIndex(0);
    setStepStatus("Uploading video to server...");
    startTimer();

    try {
      const result = await api.uploadVideo(selectedFile);
      stopTimer();
      setJobId(result.job_id);
      setVideoMeta(result.meta);
      setUploadDone(true);
      setStep("idle");
      setStepStatus("Upload complete");
    } catch (err: any) {
      stopTimer();
      setError(err.message || "Upload failed");
      setStep("idle");
    }
  };

  const handleAnalyze = async () => {
    if (!jobId) return;
    setError(null);
    setStep("analyzing");
    setStepIndex(1);
    setStepStatus("AI is analyzing your video...");
    startTimer();

    try {
      const result = await api.analyzeVideo({
        job_id: jobId,
        prompt: prompt || "Find the best and worst moments",
        splits: parseInt(splits),
        attitude,
      });
      stopTimer();
      setClips(result.clips);
      setAnalyzeDone(true);
      setStep("idle");
      setStepStatus(
        `Found ${result.clips.length} clips in ${result.elapsed.toFixed(1)}s`
      );
    } catch (err: any) {
      stopTimer();
      setError(err.message || "Analysis failed");
      setStep("idle");
    }
  };

  const handlePlan = async () => {
    if (!jobId) return;
    setError(null);
    setStep("planning");
    setStepIndex(2);
    setStepStatus("AI is creating your edit plan...");
    startTimer();

    try {
      const result = await api.planEdit({
        job_id: jobId,
        max_duration: parseInt(maxDuration) || 60,
        edit_style: editStyle,
        prompt: prompt || "",
      });
      stopTimer();
      setEditPlan(result.edit_plan);
      setEditPlanJson(JSON.stringify(result.edit_plan, null, 2));
      setPlanDone(true);
      setStep("idle");
      setStepStatus(
        `Plan created with ${result.edit_plan.segments.length} segments`
      );
    } catch (err: any) {
      stopTimer();
      setError(err.message || "Planning failed");
      setStep("idle");
    }
  };

  const handleRender = async () => {
    if (!jobId) return;
    setError(null);
    setStep("rendering");
    setStepIndex(3);
    setStepStatus("Rendering your video with FFmpeg...");
    startTimer();

    try {
      let planToUse: EditPlan | undefined;
      if (editPlanJson) {
        try {
          planToUse = JSON.parse(editPlanJson);
        } catch {
          stopTimer();
          setError("Invalid JSON in edit plan. Please fix and try again.");
          setStep("idle");
          return;
        }
      }

      const result = await api.renderVideo({
        job_id: jobId,
        edit_plan: planToUse,
        generate_thumbnails: generateThumbnails,
      });
      stopTimer();
      setDownloadUrl(result.download_url || api.getDownloadUrl(jobId));
      setStep("done");
      setStepStatus(`Rendered in ${result.elapsed.toFixed(1)}s`);
    } catch (err: any) {
      stopTimer();
      setError(err.message || "Render failed");
      setStep("idle");
    }
  };

  const handleReset = () => {
    stopTimer();
    setSelectedFile(null);
    setJobId(null);
    setVideoMeta(null);
    setStep("idle");
    setStepIndex(0);
    setStepStatus("");
    setElapsed(0);
    setClips([]);
    setEditPlan(null);
    setEditPlanJson("");
    setDownloadUrl(null);
    setError(null);
    setUploadDone(false);
    setAnalyzeDone(false);
    setPlanDone(false);
    setPrompt("");
    setPreviewSeek(undefined);
  };

  const isProcessing =
    step === "uploading" ||
    step === "analyzing" ||
    step === "planning" ||
    step === "rendering";

  const completedStepCount = planDone ? 3 : analyzeDone ? 2 : uploadDone ? 1 : 0;
  const activeStepIndex = isProcessing ? stepIndex : completedStepCount;

  return (
    <div className="min-h-screen bg-background">
      {/* Gradient background accent */}
      <div className="fixed inset-0 bg-gradient-to-br from-purple-950/20 via-background to-background pointer-events-none" />

      <div className="relative z-10 p-4 sm:p-6 lg:p-8">
        <div className="max-w-5xl mx-auto space-y-6">
          <Header />

          {/* Pipeline stepper -- always visible once a file is selected */}
          {selectedFile && (
            <PipelineStepper
              completedSteps={completedStepCount}
              activeStep={activeStepIndex}
              isProcessing={isProcessing}
              isDone={step === "done"}
            />
          )}

          {/* Progress bar -- visible during processing */}
          {isProcessing && (
            <ProgressDisplay
              currentStep={stepIndex}
              stepName={
                step === "uploading"
                  ? "Uploading"
                  : step === "analyzing"
                    ? "Analyzing"
                    : step === "planning"
                      ? "Planning"
                      : "Rendering"
              }
              status={stepStatus}
              elapsed={elapsed}
            />
          )}

          {/* Error display */}
          {error && (
            <ErrorDisplay
              message={error}
              onRetry={() => {
                setError(null);
                if (!uploadDone) handleUpload();
                else if (!analyzeDone) handleAnalyze();
                else if (!planDone) handlePlan();
                else handleRender();
              }}
            />
          )}

          {/* Main content card */}
          <div className="bg-card/80 backdrop-blur-sm border border-border rounded-2xl shadow-2xl shadow-black/30 overflow-hidden">
            {/* ========== API KEY INPUT (only if not in .env) ========== */}
            {needsApiKey && !apiKeySet && (
              <div className="p-6 sm:p-8">
                <div className="space-y-4 p-5 sm:p-6 bg-amber-500/5 rounded-xl border border-amber-500/20">
                  <h3 className="text-lg font-semibold flex items-center gap-2">
                    <div className="p-1.5 bg-amber-600/20 rounded-md">
                      <Key className="w-4 h-4 text-amber-400" />
                    </div>
                    Gemini API Key Required
                  </h3>
                  <p className="text-sm text-muted-foreground">
                    No API key found in server config. Enter your Gemini API key to get started.
                    Get one free at{" "}
                    <a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener noreferrer" className="text-purple-400 underline">
                      aistudio.google.com/apikey
                    </a>
                  </p>
                  <div className="flex gap-3">
                    <Input
                      type="password"
                      placeholder="Enter your Gemini API key..."
                      value={apiKey}
                      onChange={(e) => setApiKeyState(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && handleSetApiKey()}
                      className="flex-1 h-12"
                    />
                    <Button onClick={handleSetApiKey} className="h-12 bg-amber-600 hover:bg-amber-700 text-white" disabled={!apiKey.trim()}>
                      Set Key
                    </Button>
                  </div>
                </div>
              </div>
            )}

            {/* ========== STEP 1: FILE UPLOAD ========== */}
            {(!needsApiKey || apiKeySet) && !selectedFile && !isProcessing && (
              <div className="p-6 sm:p-8">
                <FileDropZone onFileSelect={handleFileSelect} />
              </div>
            )}

            {/* File selected but not yet uploaded */}
            {selectedFile && !uploadDone && !isProcessing && (
              <div className="p-6 sm:p-8 space-y-4">
                <div className="flex items-center gap-4 p-4 bg-purple-500/5 rounded-xl border border-purple-500/20">
                  <div className="p-2.5 bg-purple-600/20 rounded-lg">
                    <FileVideo className="w-7 h-7 text-purple-400" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="font-semibold truncate">
                      {selectedFile.name}
                    </p>
                    <p className="text-sm text-muted-foreground">
                      {(selectedFile.size / 1024 / 1024).toFixed(1)} MB
                    </p>
                  </div>
                </div>
                <div className="flex gap-3">
                  <Button
                    onClick={handleUpload}
                    className="flex-1 bg-purple-600 hover:bg-purple-700 text-white h-12 text-base"
                    size="lg"
                  >
                    <Upload className="w-5 h-5 mr-2" />
                    Upload Video
                  </Button>
                  <Button
                    onClick={handleReset}
                    variant="outline"
                    size="lg"
                    className="h-12"
                  >
                    Cancel
                  </Button>
                </div>
              </div>
            )}

            {/* Upload complete -- video meta summary */}
            {uploadDone && videoMeta && (
              <div className="px-6 sm:px-8 pt-6 sm:pt-8">
                <div className="flex items-center gap-4 p-4 bg-green-500/5 rounded-xl border border-green-500/20">
                  <div className="p-2.5 bg-green-600/20 rounded-lg">
                    <FileVideo className="w-7 h-7 text-green-400" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="font-semibold truncate">
                      {selectedFile?.name}
                    </p>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      {videoMeta.width}x{videoMeta.height} &middot;{" "}
                      {videoMeta.fps} fps &middot;{" "}
                      {videoMeta.duration.toFixed(1)}s &middot;{" "}
                      {videoMeta.video_codec}
                      {videoMeta.audio_codec
                        ? ` / ${videoMeta.audio_codec}`
                        : ""}
                    </p>
                  </div>
                </div>
              </div>
            )}

            {/* ========== STEP 2: ANALYZE ========== */}
            {uploadDone && !analyzeDone && !isProcessing && (
              <div className="p-6 sm:p-8">
                <div className="space-y-5 p-5 sm:p-6 bg-accent/30 rounded-xl border border-border">
                  <h3 className="text-lg font-semibold flex items-center gap-2">
                    <div className="p-1.5 bg-purple-600/20 rounded-md">
                      <Scissors className="w-4 h-4 text-purple-400" />
                    </div>
                    Analyze Video
                  </h3>

                  <div className="space-y-4">
                    <div className="space-y-1.5">
                      <Label htmlFor="prompt">Prompt (optional)</Label>
                      <Input
                        id="prompt"
                        placeholder="e.g. Find the funniest moments, highlight the best plays..."
                        value={prompt}
                        onChange={(e) => setPrompt(e.target.value)}
                      />
                      <p className="text-xs text-muted-foreground">
                        Guide the AI on what to look for in your video
                      </p>
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                      <AttitudeSelector
                        value={attitude}
                        onChange={setAttitude}
                      />

                      <div className="space-y-2">
                        <Label>Video Splits</Label>
                        <Select value={splits} onValueChange={setSplits}>
                          <SelectTrigger className="h-12">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="1">
                              1 split (fast, less detail)
                            </SelectItem>
                            <SelectItem value="2">
                              2 splits (balanced)
                            </SelectItem>
                            <SelectItem value="3">
                              3 splits (more detail)
                            </SelectItem>
                            <SelectItem value="4">
                              4 splits (max detail)
                            </SelectItem>
                          </SelectContent>
                        </Select>
                        <p className="text-xs text-muted-foreground">
                          More splits = better analysis for long videos
                        </p>
                      </div>
                    </div>
                  </div>

                  <Button
                    onClick={handleAnalyze}
                    className="w-full bg-purple-600 hover:bg-purple-700 text-white h-12 text-base"
                    size="lg"
                  >
                    <Sparkles className="w-5 h-5 mr-2" />
                    Analyze Video
                  </Button>
                </div>
              </div>
            )}

            {/* Clips review */}
            {analyzeDone && clips.length > 0 && (
              <div className="px-6 sm:px-8 pb-2">
                <ClipsReview
                  clips={clips}
                  onPreviewTimestamp={(s) => setPreviewSeek(s)}
                />
              </div>
            )}

            {/* Source video preview for clip timestamps */}
            {uploadDone && jobId && previewSeek !== undefined && (
              <div className="px-6 sm:px-8 pb-2">
                <VideoPreview
                  videoUrl={api.getStreamUrl(jobId)}
                  title="Source Video Preview"
                  seekTo={previewSeek}
                />
              </div>
            )}

            {/* ========== STEP 3: PLAN ========== */}
            {analyzeDone && !planDone && !isProcessing && (
              <div className="p-6 sm:p-8">
                <div className="space-y-5 p-5 sm:p-6 bg-accent/30 rounded-xl border border-border">
                  <h3 className="text-lg font-semibold flex items-center gap-2">
                    <div className="p-1.5 bg-purple-600/20 rounded-md">
                      <Wand2 className="w-4 h-4 text-purple-400" />
                    </div>
                    Create Edit Plan
                  </h3>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <div className="space-y-1.5">
                      <Label>Edit Style</Label>
                      <Select value={editStyle} onValueChange={setEditStyle}>
                        <SelectTrigger className="h-12">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="hype_montage">
                            Hype Montage
                          </SelectItem>
                          <SelectItem value="clean_edit">Clean Edit</SelectItem>
                          <SelectItem value="meme_edit">Meme Edit</SelectItem>
                          <SelectItem value="cinematic">Cinematic</SelectItem>
                        </SelectContent>
                      </Select>
                      <p className="text-xs text-muted-foreground">
                        Determines pacing, effects, and transitions
                      </p>
                    </div>

                    <div className="space-y-1.5">
                      <Label htmlFor="maxDuration">
                        Max Duration (seconds)
                      </Label>
                      <Input
                        id="maxDuration"
                        type="number"
                        min="5"
                        max="600"
                        value={maxDuration}
                        onChange={(e) => setMaxDuration(e.target.value)}
                        className="h-12"
                      />
                      <p className="text-xs text-muted-foreground">
                        Target length for the final edit
                      </p>
                    </div>
                  </div>

                  <Button
                    onClick={handlePlan}
                    className="w-full bg-purple-600 hover:bg-purple-700 text-white h-12 text-base"
                    size="lg"
                  >
                    <Wand2 className="w-5 h-5 mr-2" />
                    Generate Edit Plan
                  </Button>
                </div>
              </div>
            )}

            {/* ========== STEP 4: RENDER ========== */}
            {planDone && step !== "done" && !isProcessing && (
              <div className="p-6 sm:p-8">
                <div className="space-y-5 p-5 sm:p-6 bg-accent/30 rounded-xl border border-border">
                  <h3 className="text-lg font-semibold flex items-center gap-2">
                    <div className="p-1.5 bg-purple-600/20 rounded-md">
                      <Clapperboard className="w-4 h-4 text-purple-400" />
                    </div>
                    Render Video
                  </h3>

                  {/* Edit plan JSON editor (collapsible) */}
                  <div className="space-y-2">
                    <button
                      onClick={() => setEditPlanExpanded(!editPlanExpanded)}
                      className="flex items-center justify-between w-full text-left"
                    >
                      <Label className="cursor-pointer">
                        Edit Plan JSON
                        <span className="text-xs text-muted-foreground font-normal ml-2">
                          (editable)
                        </span>
                      </Label>
                      {editPlanExpanded ? (
                        <ChevronUp className="w-4 h-4 text-muted-foreground" />
                      ) : (
                        <ChevronDown className="w-4 h-4 text-muted-foreground" />
                      )}
                    </button>
                    {editPlanExpanded && (
                      <Textarea
                        className="font-mono text-xs min-h-48 resize-y"
                        value={editPlanJson}
                        onChange={(e) => setEditPlanJson(e.target.value)}
                        spellCheck={false}
                      />
                    )}
                    {!editPlanExpanded && editPlan && (
                      <p className="text-xs text-muted-foreground">
                        {editPlan.segments.length} segment
                        {editPlan.segments.length !== 1 ? "s" : ""} in plan.
                        Click to expand and edit.
                      </p>
                    )}
                  </div>

                  <div className="flex items-center gap-3 p-3 bg-card rounded-lg border border-border">
                    <Checkbox
                      id="thumbnails"
                      checked={generateThumbnails}
                      onCheckedChange={(checked) =>
                        setGenerateThumbnails(checked === true)
                      }
                    />
                    <div>
                      <Label htmlFor="thumbnails" className="cursor-pointer">
                        Generate AI Thumbnails
                      </Label>
                      <p className="text-xs text-muted-foreground">
                        Create thumbnail images for the video
                      </p>
                    </div>
                  </div>

                  <Button
                    onClick={handleRender}
                    className="w-full bg-gradient-to-r from-purple-600 to-pink-600 hover:from-purple-700 hover:to-pink-700 text-white h-12 text-base"
                    size="lg"
                  >
                    <Clapperboard className="w-5 h-5 mr-2" />
                    Render Final Video
                  </Button>
                </div>
              </div>
            )}

            {/* ========== DONE: PREVIEW + DOWNLOAD ========== */}
            {step === "done" && downloadUrl && jobId && (
              <div className="p-6 sm:p-8 space-y-6">
                <div className="text-center space-y-2">
                  <div className="inline-flex items-center gap-2 px-4 py-2 bg-green-500/10 border border-green-500/20 rounded-full">
                    <div className="w-2 h-2 bg-green-400 rounded-full animate-pulse" />
                    <span className="text-sm font-medium text-green-400">
                      Video rendered successfully in {elapsed.toFixed(1)}s
                    </span>
                  </div>
                </div>

                <VideoPreview
                  videoUrl={downloadUrl}
                  title="Rendered Video"
                />

                <div className="flex flex-col sm:flex-row gap-3">
                  <div className="flex-1">
                    <DownloadButton downloadUrl={downloadUrl} />
                  </div>
                  <Button
                    onClick={handleReset}
                    variant="outline"
                    size="lg"
                    className="h-12 sm:w-auto"
                  >
                    <RotateCcw className="w-4 h-4 mr-2" />
                    Edit Another Video
                  </Button>
                </div>
              </div>
            )}
          </div>

          {/* Footer */}
          <p className="text-center text-xs text-muted-foreground pb-6">
            AI Video Editor &mdash; Powered by FFmpeg + Gemini AI
          </p>
        </div>
      </div>
    </div>
  );
}
