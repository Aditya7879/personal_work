"""Repair only imported business classification; never replace feedback or its history."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import uuid
from collections import Counter
from pathlib import Path

from google.cloud import bigquery

from app.bigquery import BigQueryRepository
from scripts.replace_feedback_xlsx import read_feedback_workbook


def repair(repo: BigQueryRepository, path: Path, apply: bool = False) -> dict:
    payloads = read_feedback_workbook(path)
    source_hash = payloads[0].run_context['source_sha256']
    by_number = {str(payload.run_context['legacy_row']): payload for payload in payloads}
    current = repo.workflow_query(f"""SELECT feedback_id, COALESCE(revision,1) AS revision,
        business_domain, business_subdomain, domain_source, domain_verified, domain_confidence,
        domain_reason, domain_evidence_json, run_context_json FROM `{repo.feedback_ref}`
        WHERE JSON_VALUE(run_context_json,'$.source_sha256') = @hash
            AND JSON_VALUE(run_context_json,'$.source') = 'legacy_xlsx_import'""",
        [bigquery.ScalarQueryParameter('hash', 'STRING', source_hash)])
    updates, backups, seen = [], [], set()
    for row in current:
        context = repo._json_object(row['run_context_json'])
        number = str(context.get('legacy_row'))
        if number in seen:
            raise ValueError('Duplicate workbook row mapping; no metadata changed')
        seen.add(number)
        payload = by_number.get(number)
        if not payload or context.get('sub_domain') != payload.run_context.get('sub_domain'):
            raise ValueError('Workbook source mapping changed; no metadata changed')
        domain = payload.run_context.get('domain')
        subdomain = payload.run_context.get('business_subdomain')
        if not domain or row.get('domain_verified') or row.get('domain_source') in {'reviewer_confirmed', 'user_confirmed'}:
            continue
        if (row.get('business_domain'), row.get('business_subdomain'), row.get('domain_source')) == (domain, subdomain, 'workbook_import'):
            continue
        updates.append(bigquery.StructQueryParameter(None,
            bigquery.ScalarQueryParameter('id', 'STRING', row['feedback_id']),
            bigquery.ScalarQueryParameter('revision', 'INT64', row['revision']),
            bigquery.ScalarQueryParameter('domain', 'STRING', domain),
            bigquery.ScalarQueryParameter('subdomain', 'STRING', subdomain),
            bigquery.ScalarQueryParameter('raw', 'STRING', context.get('sub_domain')),
            bigquery.ScalarQueryParameter('old_domain', 'STRING', row.get('business_domain')),
            bigquery.ScalarQueryParameter('old_subdomain', 'STRING', row.get('business_subdomain')),
            bigquery.ScalarQueryParameter('old_source', 'STRING', row.get('domain_source'))))
        backups.append({key: value for key, value in row.items() if key != 'run_context_json'})
    summary = {'matchedWorkbookRows': len(current), 'corrections': len(updates),
               'correctedDomains': dict(Counter(value.struct_values['domain'] for value in updates)), 'applied': False}
    if not apply or not updates:
        return summary
    directory = Path(tempfile.mkdtemp(prefix='feedback-taxonomy-fix-', dir='/tmp/opencode'))
    descriptor = os.open(directory / 'metadata-before.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as output:
        json.dump(backups, output, indent=2, default=str)
    run_id = uuid.uuid4().hex
    parameters = [bigquery.ArrayQueryParameter('updates', 'STRUCT', updates),
        bigquery.ScalarQueryParameter('hash', 'STRING', source_hash),
        bigquery.ScalarQueryParameter('expected', 'INT64', len(updates)),
        bigquery.ScalarQueryParameter('run_id', 'STRING', run_id)]
    result = repo.workflow_query(f"""BEGIN TRANSACTION;
        UPDATE `{repo.feedback_ref}` f SET business_domain = s.domain, business_subdomain = s.subdomain,
            domain_source = 'workbook_import', domain_confidence = NULL, domain_evidence_json = '[]',
            domain_reason = 'Domain and subdomain taken from the authoritative workbook classification, including unambiguous matches to explicitly prefixed workbook labels. Not an AI inference.',
            updated_at = CURRENT_TIMESTAMP()
        FROM UNNEST(@updates) s WHERE f.feedback_id = s.id AND COALESCE(f.revision,1) = s.revision
            AND NOT COALESCE(f.domain_verified,FALSE)
            AND COALESCE(f.business_domain,'') = COALESCE(s.old_domain,'')
            AND COALESCE(f.business_subdomain,'') = COALESCE(s.old_subdomain,'')
            AND COALESCE(f.domain_source,'') = COALESCE(s.old_source,'')
            AND JSON_VALUE(f.run_context_json,'$.source_sha256') = @hash
            AND JSON_VALUE(f.run_context_json,'$.sub_domain') = s.raw;
        ASSERT @@row_count = @expected AS 'Metadata changed concurrently; repair rolled back';
        INSERT INTO `{repo.events_ref}` (event_id,feedback_id,event_type,created_at,actor,payload_json)
        SELECT CONCAT('workbook-taxonomy:',@run_id,':',s.id),s.id,'workbook_taxonomy_corrected',
            CURRENT_TIMESTAMP(),'system:workbook_taxonomy_correction',
            TO_JSON_STRING(STRUCT(s.domain AS business_domain,s.subdomain AS business_subdomain,
                s.raw AS imported_label,@hash AS source_sha256)) FROM UNNEST(@updates) s;
        COMMIT TRANSACTION;
        SELECT @expected AS corrected;""", parameters)
    summary.update(applied=True, corrected=int(result[0]['corrected']), artifacts=str(directory), runId=run_id)
    (directory / 'result.json').write_text(json.dumps(summary, indent=2))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(repair(BigQueryRepository(), args.path, args.apply), indent=2))


if __name__ == '__main__':
    main()
