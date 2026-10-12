"""Opt-in Modal extraction scaffold. Importing does not deploy or invoke a GPU."""
from pathlib import Path


def build_app(gpu="L4"):
    import modal
    app = modal.App("lim-vjepa-extraction")
    image = (modal.Image.debian_slim(python_version="3.11").apt_install("ffmpeg")
             .pip_install("numpy>=1.24", "torch>=2.6", "torchvision>=0.21", "transformers>=4.56,<6")
             .add_local_python_source("vjepa"))
    volume = modal.Volume.from_name("lim-vjepa-data", create_if_missing=True)

    @app.function(image=image, gpu=gpu, volumes={"/data": volume}, timeout=3600)
    def extract_match(video_name: str, output_name: str, revision: str, batch_size: int = 2):
        from .features import HFEncoder, extract, atomic_npz
        # Inputs must already exist on the mounted volume; no video byte uploads in function args.
        root = Path("/data").resolve()
        video, output = (root / video_name).resolve(), (root / output_name).resolve()
        if root not in video.parents or root not in output.parents or video == output:
            raise ValueError("distinct input/output paths inside /data required")
        encoder = HFEncoder(revision=revision, device="cuda")
        data = extract(video, encoder, root / "cache", batch_size=batch_size)
        import json
        atomic_npz(output, features=data["features"], windows=data["windows"],
                   metadata=json.dumps({k: v for k, v in data.items() if k not in ("features", "windows")}))
        volume.commit()
        return {"output": output_name, "windows": len(data["windows"])}

    return app, extract_match
