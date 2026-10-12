"""Explicit final two live attempts, sharing the original run's six-call cap."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'full_app'))


def main():
    from services.gemini_client import GeminiProvider
    from services.call_budget import CallBudget
    from services.provider_errors import classify
    output = Path(__file__).parent / 'out'
    key = sys.stdin.readline().strip()
    provider = GeminiProvider(api_key=key, vertexai=True)
    provider.budget = CallBudget(output / 'live-budget.sqlite3', limit=6)
    image_budget = CallBudget(output / 'diagnostic-budget.sqlite3', limit=2)
    results = []
    for role in ('intro', 'outro'):
        metadata = json.loads((output / 'valorant/cards' / f'{role}.json').read_text())
        try:
            provider.generate_thumbnail(output / 'valorant/cards' / f'{role}_frame.png',
                                        metadata['prompt'], output / f'diagnostic_{role}.png',
                                        image_budget=image_budget)
            result = dict(role=role, success=True)
        except Exception as error:
            # Redact runtime credential before retaining the diagnostic message.
            message = str(error).replace(key, '[REDACTED]')
            result = dict(role=role, success=False, reason=classify(error).code,
                          type=type(error).__name__, detail=message[:1600])
        results.append(result)
        print(json.dumps(result), flush=True)
        (output / 'diagnostics.json').write_text(json.dumps(dict(
            live_attempts=6-provider.budget.remaining, results=results), indent=2))
    provider.close()


if __name__ == '__main__':
    main()
