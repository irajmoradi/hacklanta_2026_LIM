"""Allowlisted diagnostics safe for job status (never echo provider messages)."""
class ProviderFailure(RuntimeError):
    def __init__(self, code):
        self.code = code if code in MESSAGES else 'provider'
        super().__init__(MESSAGES[self.code])

MESSAGES = {
    'credentials': 'Gemini authentication failed; check the API key and Vertex/AI Studio backend selection.',
    'quota': 'Gemini quota exhausted; check project quota or retry later.',
    'schema': 'Gemini response/schema was invalid; verify google-genai compatibility and the configured model.',
    'model': 'Gemini model unavailable; check GEMINI_MODEL for the selected backend.',
    'timeout': 'Gemini timed out; retry with shorter video chunks.',
    'budget': 'Gemini job call budget exhausted; increase MAX_GEMINI_CALLS_PER_JOB or use local planning.',
    'provider': 'Gemini request failed; check backend, model, network and video size settings.',
}

def classify(error):
    from pydantic import ValidationError
    if isinstance(error, ProviderFailure):
        return error
    status = str(getattr(error, 'code', None) or getattr(error, 'status_code', None))
    code = {'401': 'credentials', '403': 'credentials', '429': 'quota', '404': 'model', '400': 'schema'}.get(status, 'provider')
    if isinstance(error, ValidationError): code = 'schema'
    if isinstance(error, TimeoutError): code = 'timeout'
    return ProviderFailure(code)
