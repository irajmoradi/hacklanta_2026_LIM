"""Owner-deployed only: modal deploy -m gpu.modal_app. Import does not deploy."""
import os
import re
import modal

SAM_COMMIT = "0570b3a5be9c4e694f23d85232fb55f4a6f1f7fc"
revision = os.environ.get("VJEPA_REVISION", "")
if not re.fullmatch(r"[0-9a-f]{40}", revision):
    raise ValueError("Set VJEPA_REVISION to the full Hugging Face checkpoint commit before deployment")

app = modal.App("lim-optional-gpu")
secret = modal.Secret.from_name("lim-gpu-auth", required_keys=["GPU_API_TOKEN", "HF_TOKEN"])
base = (modal.Image.debian_slim(python_version="3.12")
        .pip_install("fastapi>=0.115,<1", "pydantic>=2,<3", "numpy>=1.26,<3", "pillow>=10,<13"))
gpu_image = (base.apt_install("git", "ffmpeg", "libgl1", "libglib2.0-0")
             .pip_install("torch==2.7.1", "torchvision==0.22.1",
                          index_url="https://download.pytorch.org/whl/cu126")
             .pip_install("faster-whisper==1.2.1", "transformers==4.57.1", "accelerate>=1,<2",
                          "einops", "decord", "opencv-python-headless==4.11.0.86",
                          "setuptools<81", "scipy", "pycocotools",
                          "nvidia-cudnn-cu12>=9,<10",
                          f"sam3 @ git+https://github.com/facebookresearch/sam3.git@{SAM_COMMIT}")
             .env({"HF_HOME": "/cache/huggingface", "VJEPA_REVISION": revision,
                   "LD_LIBRARY_PATH": "/usr/local/lib/python3.12/site-packages/nvidia/cudnn/lib:"
                                      "/usr/local/lib/python3.12/site-packages/nvidia/cublas/lib"})
             .add_local_python_source("gpu"))
cpu_image = base.add_local_python_source("gpu")
cache = modal.Volume.from_name("lim-gpu-model-cache", create_if_missing=True)


@app.cls(image=gpu_image, gpu="A100-80GB", cpu=2, memory=16384,
         min_containers=0, max_containers=1, buffer_containers=0,
         scaledown_window=30, timeout=240, retries=0,
         secrets=[secret], volumes={"/cache": cache})
class Worker:
    @modal.enter()
    def start(self):
        from gpu.models import Engine
        self.engine = Engine()

    @modal.method()
    def infer(self, kind, payload):
        return self.engine.infer(kind, payload)


@app.function(image=cpu_image, min_containers=0, max_containers=1,
              buffer_containers=0, scaledown_window=30, timeout=300,
              secrets=[secret])
@modal.asgi_app()
def api():
    from gpu.server import create_api
    worker = Worker()

    async def infer(kind, payload):
        return await worker.infer.remote.aio(kind, payload)

    return create_api(infer)
