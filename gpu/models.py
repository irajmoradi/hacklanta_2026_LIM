"""Lazy real-model runners; one model family resident at a time."""
import gc
import json
import os
from pathlib import Path
import tempfile

import numpy as np
from PIL import Image

from gpu.schemas import MAX_RESPONSE, MODEL_ID, REQUESTS, decode, validate_response


def rle(mask):
    """Row-major alternating zero/one runs, beginning with a zero run."""
    flat = np.asarray(mask, dtype=np.uint8).ravel()
    changes = np.flatnonzero(flat[1:] != flat[:-1]) + 1
    counts = np.diff(np.r_[0, changes, len(flat)]).tolist()
    return ([0] if flat[0] else []) + counts


class Engine:
    def __init__(self):
        self.family = None
        self.model = None
        self.processor = None
        self.identity = None

    def load(self, family):
        if family == self.family:
            return
        if self.family == "track" and self.model is not None:
            self.model.shutdown()
        self.model = self.processor = None
        self.family = None
        gc.collect()
        import torch
        torch.cuda.empty_cache()
        if family == "segment":
            from sam3.model_builder import build_sam3_image_model
            from sam3.model.sam3_image_processor import Sam3Processor
            self.model = build_sam3_image_model()
            self.processor = Sam3Processor(self.model)
        elif family == "track":
            from sam3.model_builder import build_sam3_video_predictor
            self.model = build_sam3_video_predictor()
        elif family == "transcribe":
            from faster_whisper import WhisperModel
            self.model = WhisperModel("large-v3", device="cuda", compute_type="float16")
        else:
            from transformers import AutoModel, AutoVideoProcessor
            revision = os.environ["VJEPA_REVISION"]
            self.processor = AutoVideoProcessor.from_pretrained(MODEL_ID, revision=revision)
            self.model = AutoModel.from_pretrained(MODEL_ID, revision=revision).to("cuda").eval()
            resolved = getattr(self.model.config, "_commit_hash", None) or revision
            self.identity = f"hf-mean-v1:{MODEL_ID}@{resolved}"
        self.family = family

    def infer(self, kind, values):
        request = REQUESTS[kind].model_validate(values)
        media = decode(kind, request)
        self.load(kind)
        if kind == "segment":
            import torch
            with torch.inference_mode():
                state = self.processor.set_image(Image.fromarray(media))
                out = self.processor.set_text_prompt(state=state, prompt=request.prompt)
            masks = out["masks"].detach().cpu().numpy()
            # Union of all matching instances; empty detection is a zero mask.
            mask = np.zeros(media.shape[:2], dtype=np.uint8)
            if len(masks):
                mask = np.any(masks.reshape(-1, *media.shape[:2]) > 0, axis=0).astype(np.uint8)
            result = {"mask": mask.tolist()}
        elif kind == "track":
            result = self.track(media, request)
        elif kind == "transcribe":
            segments, info = self.model.transcribe(media.copy(), word_timestamps=True, vad_filter=True)
            words = [{"start": float(w.start), "end": float(w.end), "text": w.word.strip(),
                      "probability": float(w.probability)}
                     for segment in segments for w in (segment.words or [])
                     if w.word.strip() and w.end > w.start]
            result = {"words": words, "language": info.language}
        else:
            if request.encoder != self.identity:
                raise ValueError("Encoder fingerprint differs")
            import torch
            inputs = self.processor(videos=[media], return_tensors="pt", do_resize=False,
                                    do_center_crop=False, do_sample_frames=False).to("cuda")
            with torch.inference_mode():
                features = self.model.get_vision_features(**inputs)
            result = {"features": features.mean(dim=1).float().cpu().numpy()[0].tolist(),
                      "encoder": self.identity}
        return validate_response(kind, result, request, media)

    def track(self, frames, request):
        h, w = frames.shape[1:3]
        with tempfile.TemporaryDirectory(prefix="lim-sam-") as directory:
            for index, frame in enumerate(frames):
                Image.fromarray(frame).save(Path(directory) / f"{index:05d}.jpg")
            session = self.model.handle_request({"type": "start_session", "resource_path": directory})
            sid = session["session_id"]
            try:
                self.model.handle_request({"type": "add_prompt", "session_id": sid,
                                           "frame_index": 0, "text": request.prompt})
                rows = {}
                response_bytes = 0
                for response in self.model.handle_stream_request({
                    "type": "propagate_in_video", "session_id": sid,
                    "propagation_direction": "forward", "start_frame_index": 0,
                }):
                    index, outputs = response["frame_index"], response["outputs"]
                    objects = []
                    if len(outputs["out_obj_ids"]) > 32:
                        raise ValueError("Too many detected objects")
                    for obj_id, mask in zip(outputs["out_obj_ids"], outputs["out_binary_masks"]):
                        mask = np.asarray(mask).reshape(h, w).astype(bool)
                        y, x = np.nonzero(mask)
                        if len(x):
                            objects.append({"id": int(obj_id), "rle": rle(mask),
                                            "box": [float(x.min()/w), float(y.min()/h),
                                                    float((x.max()+1)/w), float((y.max()+1)/h)]})
                    rows[index] = {"frame_index": index, "time": index/request.fps, "objects": objects}
                    response_bytes += len(json.dumps(rows[index], separators=(",", ":")))
                    if response_bytes > MAX_RESPONSE - 1024:
                        raise ValueError("Tracking output exceeds response limit")
                return {"width": w, "height": h, "frames": [rows[i] for i in range(len(frames))]}
            finally:
                self.model.handle_request({"type": "close_session", "session_id": sid})
