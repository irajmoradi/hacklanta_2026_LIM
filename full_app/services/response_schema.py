"""SDK-compatible request schemas; original Pydantic models validate responses."""
import json
import logging
import math
from pydantic import ValidationError
from models.schemas import Clip, ClipList
LOG = logging.getLogger(__name__)

def compatible_schema(value):
    if isinstance(value, list): return [compatible_schema(v) for v in value]
    if isinstance(value, dict):
        return { {'exclusiveMinimum': 'minimum', 'exclusiveMaximum': 'maximum'}.get(k, k): compatible_schema(v)
                 for k, v in value.items() }
    return value

def parse_response(schema, text):
    if schema is not ClipList: return schema.model_validate_json(text)
    raw = json.loads(text)
    if not isinstance(raw, dict) or set(raw) != {'clips'} or not isinstance(raw['clips'], list):
        return schema.model_validate(raw)
    valid = []
    for index, row in enumerate(raw['clips']):
        try:
            if isinstance(row, dict):
                row = dict(row)
                for key in ('start', 'start_seconds'):
                    if type(row.get(key)) in (int, float) and math.isfinite(row[key]) and row[key] < 0:
                        LOG.warning('Clamped negative model timestamp item=%d field=%s', index, key)
                        row[key] = 0.
            valid.append(Clip.model_validate(row))
        except ValidationError:
            LOG.warning('Dropped invalid model clip item=%d', index)
    return ClipList(clips=valid)
