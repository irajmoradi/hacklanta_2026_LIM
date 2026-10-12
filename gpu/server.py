"""CPU authentication/validation gateway. No model loads before validation."""
import hmac
import json
import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from gpu.schemas import MAX_BODY, MAX_RESPONSE, REQUESTS, decode, validate_response


def create_api(infer):
    api = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @api.post("/{kind}")
    async def endpoint(kind: str, request: Request):
        token = os.environ.get("GPU_API_TOKEN", "")
        supplied = request.headers.get("authorization", "")
        if not token or not hmac.compare_digest(supplied.encode(), ("Bearer " + token).encode()):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        if kind not in REQUESTS:
            return JSONResponse({"error": "Unknown endpoint"}, status_code=404)
        if request.headers.get("content-type", "").split(";")[0] != "application/json":
            return JSONResponse({"error": "Expected JSON"}, status_code=415)
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_BODY:
                return JSONResponse({"error": "Request too large"}, status_code=413)
            body.extend(chunk)
        try:
            payload = REQUESTS[kind].model_validate_json(body)
            media = decode(kind, payload)
        except Exception:
            return JSONResponse({"error": "Invalid request"}, status_code=422)
        try:
            result = await infer(kind, payload.model_dump())
            validate_response(kind, result, payload, media)
            encoded = json.dumps(result, allow_nan=False, separators=(",", ":"))
            if len(encoded.encode()) > MAX_RESPONSE:
                raise ValueError("Response too large")
            return JSONResponse(result)
        except Exception:
            # Never return credentials, model paths, media, or provider exception text.
            return JSONResponse({"error": "GPU backend unavailable"}, status_code=503)

    return api
