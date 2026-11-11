"""Read-only discovery of the owner's current saved-answer review; never a write grant."""


def user_verdict(confirmation):
    return {'fixed': 'Correct', 'partially_fixed': 'Partially correct', 'still_incorrect': 'Incorrect'}.get(confirmation)


def review_summary(context: dict, completed: dict | None, latest: dict | None) -> dict:
    completed, latest = completed or {}, latest or {}
    result = {'state': 'no_fresh_answer', 'attemptId': None, 'answerId': None,
        'environmentId': context.get('environmentId'), 'environmentKind': context.get('environmentKind') or 'unknown',
        'environmentLabel': context.get('environmentLabel'), 'revision': int(context.get('revision') or 1),
        'confirmation': None}
    if result['environmentKind'] not in {'nonprod', 'prod'} or not result['environmentId']:
        result['state'] = 'environment_unknown'
    elif completed.get('id'):
        result.update(state='already_responded' if completed.get('confirmation') else 'available',
            attemptId=completed['id'], answerId='answer:' + completed['id'], confirmation=completed.get('confirmation'))
    elif latest.get('id'):
        if int(latest.get('revision') or 1) != result['revision']:
            result['state'] = 'outdated_revision'
        elif latest.get('environmentId') != result['environmentId'] or latest.get('environmentKind') != result['environmentKind']:
            result['state'] = 'different_environment'
        elif latest.get('status') in {'queued', 'running'}:
            result['state'] = 'processing'
        elif latest.get('status') in {'failed', 'cancelled'}:
            result['state'] = 'unavailable'
    displayed = completed if completed.get('id') else latest if (latest.get('saved_answer')
        and latest.get('environmentId') == result['environmentId'] and latest.get('environmentKind') == result['environmentKind']) else {}
    if displayed:
        result.update(displayAnswerId='answer:' + displayed['id'], displayAnswerRevision=int(displayed.get('revision') or 1),
            userVerdict=user_verdict(displayed.get('confirmation')))
    return result
