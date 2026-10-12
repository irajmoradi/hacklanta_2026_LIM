"""Provider identities and credential selection shared by all entry points."""
import os

PROVIDERS = ('gemini', 'local', 'local_vlm')


def validate_provider(provider):
    if provider not in PROVIDERS:
        raise ValueError(f'Unknown provider: {provider}')
    return provider


def gemini_credentials(api_key=None, vertexai=None):
    if vertexai is None:
        vertexai = os.getenv('GOOGLE_GENAI_USE_VERTEXAI', '').lower() == 'true'
    return api_key or os.getenv('GOOGLE_API_KEY' if vertexai else 'GEMINI_API_KEY'), vertexai


def configuration(provider='gemini'):
    """Public configuration only; never return a credential."""
    validate_provider(provider)
    key, vertex = gemini_credentials()
    return dict(provider=provider, has_api_key=bool(key), vertexai=vertex,
                planning_provider='gemini', hybrid=provider != 'gemini')
