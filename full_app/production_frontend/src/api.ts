// API client for the Flask backend

let _apiKey: string | null = null;

export function setApiKey(key: string) {
  _apiKey = key || null;
}

export function getApiKey(): string | null {
  return _apiKey;
}

function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (_apiKey) headers["X-API-Key"] = _apiKey;
  return headers;
}

export interface ServerInfo {
  model: string;
  video_effects: Record<string, string>;
  sound_effects: Record<string, string>;
  edit_styles: Record<string, string>;
  has_api_key: boolean;
}

export interface UploadResult {
  job_id: string;
  meta: {
    duration: number;
    width: number;
    height: number;
    fps: number;
    video_codec: string;
    audio_codec: string;
  };
}

export interface Clip {
  start: number;
  end: number;
  start_seconds: number;
  end_seconds: number;
  type: "good" | "bad";
  description: string;
}

export interface AnalyzeResult {
  clips: Clip[];
  elapsed: number;
  splits: number;
}

export interface EditSegment {
  source_start: number;
  source_end: number;
  video_effects?: string[];
  speed?: number;
  transition_in?: string;
  sound_effects?: { sfx_key: string; offset_in_segment: number }[];
  [key: string]: unknown;
}

export interface EditPlan {
  segments: EditSegment[];
  [key: string]: unknown;
}

export interface PlanResult {
  edit_plan: EditPlan;
  elapsed: number;
}

export interface RenderResult {
  elapsed: number;
  download_url: string;
}

export interface JobStatus {
  job_id: string;
  status: string;
  has_clips: boolean;
  has_plan: boolean;
  has_output: boolean;
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text();
    let msg: string;
    try {
      const json = JSON.parse(text);
      msg = json.error || json.message || text;
    } catch {
      msg = text;
    }
    throw new Error(msg || `HTTP ${res.status}`);
  }
  return res.json();
}

export async function fetchInfo(): Promise<ServerInfo> {
  const res = await fetch("/api/info");
  return handleResponse(res);
}

export async function uploadVideo(file: File): Promise<UploadResult> {
  const form = new FormData();
  form.append("video", file);
  const res = await fetch("/api/upload", { method: "POST", body: form });
  return handleResponse(res);
}

export async function analyzeVideo(params: {
  job_id: string;
  prompt: string;
  splits: number;
  attitude: "nice" | "mean";
}): Promise<AnalyzeResult> {
  const res = await fetch("/api/analyze", {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify(params),
  });
  return handleResponse(res);
}

export async function planEdit(params: {
  job_id: string;
  max_duration: number;
  edit_style: string;
  prompt: string;
}): Promise<PlanResult> {
  const res = await fetch("/api/plan", {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify(params),
  });
  return handleResponse(res);
}

export async function renderVideo(params: {
  job_id: string;
  edit_plan?: EditPlan;
  generate_thumbnails?: boolean;
}): Promise<RenderResult> {
  const res = await fetch("/api/render", {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify(params),
  });
  return handleResponse(res);
}

export async function fetchStatus(jobId: string): Promise<JobStatus> {
  const res = await fetch(`/api/status/${jobId}`);
  return handleResponse(res);
}

export async function fetchLog(jobId: string): Promise<string> {
  const res = await fetch(`/api/log/${jobId}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.text();
}

export function getDownloadUrl(jobId: string): string {
  return `/api/download/${jobId}`;
}

export function getStreamUrl(jobId: string): string {
  return `/api/stream/${jobId}`;
}
