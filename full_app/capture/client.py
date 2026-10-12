"""Streaming uploads using the application's asynchronous jobs API."""
from urllib.parse import quote

import httpx
from server.security import api_headers, safe_component


class UploadClient:
    def __init__(self, api, *, transport=None):
        self.http = httpx.Client(base_url=api.rstrip('/') + '/', timeout=300,
                                 transport=transport, follow_redirects=False,
                                 headers=api_headers(api), trust_env=False)

    def upload(self, path):
        with path.open('rb') as video:
            response = self.http.post('api/jobs', files={'video': (path.name, video)})
        response.raise_for_status()
        data = response.json()
        job = data.get('job_id') or data.get('id')
        if not isinstance(job, str) or not job:
            raise ValueError('Upload response has no job id')
        return safe_component(job)

    def analyze(self, job, options):
        response = self.http.post(f'api/jobs/{quote(safe_component(job), safe="")}/analyze', json=options)
        response.raise_for_status()

    def close(self):
        self.http.close()
