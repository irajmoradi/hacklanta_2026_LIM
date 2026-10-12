"""Local optional OCR adapters; no API calls or implicit model downloads."""
import csv
import io
import shutil
import subprocess
from dataclasses import dataclass

import cv2


@dataclass(frozen=True)
class Word:
    text: str
    x: int
    y: int
    width: int
    height: int


class Tesseract:
    def __init__(self):
        self.executable = shutil.which("tesseract")
        if not self.executable:
            raise RuntimeError("Tesseract executable is unavailable")

    def read(self, frame):
        ok, png = cv2.imencode(".png", frame)
        if not ok:
            raise RuntimeError("could not encode OCR frame")
        result = subprocess.run(
            [self.executable, "stdin", "stdout", "--psm", "11", "tsv"],
            input=png.tobytes(), capture_output=True, check=True, timeout=30,
        )
        rows = csv.DictReader(io.StringIO(result.stdout.decode("utf-8", errors="replace")), delimiter="\t")
        return [Word(r["text"].strip(), int(r["left"]), int(r["top"]), int(r["width"]), int(r["height"]))
                for r in rows if r.get("text", "").strip() and float(r["conf"]) >= 0]


class RapidOCR:
    def __init__(self):
        # Explicit extra only: this package bundles its ONNX models.
        from rapidocr_onnxruntime import RapidOCR as Engine
        self.engine = Engine()

    def read(self, frame):
        result, _ = self.engine(frame)
        words = []
        for points, text, confidence in result or []:
            if not text.strip() or confidence < 0:
                continue
            xs, ys = zip(*points)
            x, y = int(min(xs)), int(min(ys))
            words.append(Word(text.strip(), x, y, int(max(xs)) - x + 1, int(max(ys)) - y + 1))
        return words


def get_reader(backend):
    if backend == "none":
        return None
    if backend == "rapidocr":
        return RapidOCR()
    return Tesseract()
