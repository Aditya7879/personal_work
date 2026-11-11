"""Meaningful assessment-input changes versus audited descriptive/opinion edits."""
import json
from datetime import datetime, timezone


# These change the evaluated input, criteria or exact execution/provenance context.
# A reporter opinion, title, impact, categories and business labels do not.
REVISION_FIELDS = frozenset({'question', 'answer', 'expected_behavior', 'feedback_text', 'follow_up',
    'environment', 'environment_id', 'agent_id', 'agent_version', 'run_id', 'conversation_id', 'data_source', 'language'})


def meaningful_updates(current: dict, context: dict, updates: dict) -> dict:
    changes = {}
    for key, value in updates.items():
        if value is None and key in {'user_verdict', 'issue_categories', 'impact'}:
            continue
        if key in {'data_source', 'language', 'follow_up', 'environment_id'}:
            previous = context.get(key)
        elif key == 'expected_behavior':
            previous = current.get('ground_truth_hint', current.get('expected_behavior'))
        elif key == 'feedback_text':
            previous = current.get('full_quote') or current.get('feedback_text')
        elif key == 'issue_categories':
            try: previous = json.loads(current.get('issue_categories_json') or '[]')
            except (TypeError, ValueError): previous = []
        elif key == 'environment':
            previous = context.get('environment_kind') or current.get('environment')
        else:
            previous = current.get(key)
        if isinstance(value, str): value = value.strip()
        if isinstance(previous, str): previous = previous.strip()
        if (value or None) != (previous or None):
            changes[key] = value
    return changes


def timestamp(value):
    if value is None: return None
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
