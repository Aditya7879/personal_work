import type { AgentEnvironment, AgentEnvironmentConfig } from '../api/feedbackApi';
import type { FeedbackItem } from '../types';

export const unassignedSourceOption = 'source:unknown';

export function inboxEnvironmentFilter(environments: AgentEnvironmentConfig[], workspaceId: string | undefined,
  kind: AgentEnvironment | 'All', sharedWorkspace: boolean) {
  if (!sharedWorkspace) return { value: kind, options: [
    { value:'nonprod',label:'Non-production' },{ value:'prod',label:'Production' },{ value:'unknown',label:'Source not recorded' },
  ] };
  return { value:kind === 'unknown' ? unassignedSourceOption : workspaceId || 'All', options:[
    ...environments.map((row) => ({ value:row.id,label:row.name + (row.enabled ? '' : ' · disabled') })),
    { value:unassignedSourceOption,label:'Source not recorded' },
  ] };
}

export function inboxEnvironmentSelection(value: string): { workspaceId:string; kind:AgentEnvironment | 'All' } {
  return value === unassignedSourceOption ? { workspaceId:'All',kind:'unknown' } : { workspaceId:value,kind:'All' };
}

export function inboxRowEnvironment(item: Pick<FeedbackItem,'environment'|'environmentId'|'environmentLabel'|'environmentResult'|'mainEnvironmentId'|'mainEnvironmentKind'|'mainEnvironmentLabel'>,
  environments: AgentEnvironmentConfig[], workspaceId?: string, kind:AgentEnvironment | 'All' = 'All') {
  const source = item.environmentLabel || (item.environment === 'prod' ? 'Production' : item.environment === 'nonprod' ? 'Non-production' : 'Not recorded');
  if (workspaceId) {
    const selected = environments.find((row) => row.id === workspaceId);
    const here = item.environmentId === workspaceId;
    const linked = !here && item.environmentResult?.environmentId === workspaceId;
    return { label:selected?.name || (linked ? item.environmentResult?.environmentLabel : null) || 'Selected environment',
      detail:here ? 'Original reported environment' : linked ? `Linked validation attempt · reported in ${source}` : `Originally reported in ${source}`,
      linked };
  }
  if (item.mainEnvironmentId && item.mainEnvironmentKind) {
    const sourceLabel = item.environmentLabel || (item.environment === 'prod' ? 'Production' : item.environment === 'nonprod' ? 'Non-production' : 'Not recorded');
    return { label: item.mainEnvironmentLabel || (item.mainEnvironmentKind === 'prod' ? 'Production' : 'Non-production'),
      detail: `Main environment · originally reported in ${sourceLabel}`, linked: item.mainEnvironmentId !== item.environmentId };
  }
  const linked = kind !== 'All' && kind !== 'unknown' && item.environment !== kind;
  return { label:source,detail:linked ? `Linked ${kind === 'prod' ? 'Production' : 'Non-production'} activity · original source unchanged` : 'Original reported environment',linked };
}

export function inboxRcaContext(item: Pick<FeedbackItem,'environmentId'|'environmentResult'|'mainEnvironmentId'>, workspaceId?: string) {
  if (!workspaceId) {
    if (item.mainEnvironmentId) {
      if (item.environmentResult?.environmentId === item.mainEnvironmentId) return { kind:'attempt' as const,attempt:item.environmentResult };
      return { kind:'missing' as const };
    }
    return { kind:'source' as const };
  }
  if (item.environmentResult?.environmentId === workspaceId) return { kind:'attempt' as const,attempt:item.environmentResult };
  if (item.environmentId === workspaceId) return { kind:'source' as const };
  return { kind:'missing' as const };
}
