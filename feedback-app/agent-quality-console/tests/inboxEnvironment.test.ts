import assert from 'node:assert/strict';
import test from 'node:test';
import type { AgentEnvironmentConfig, WorkflowAttempt } from '../src/api/feedbackApi';
import { clearReadCache, listFeedback } from '../src/api/feedbackApi';
import { inboxEnvironmentFilter, inboxEnvironmentSelection, inboxRcaContext, inboxRowEnvironment, unassignedSourceOption } from '../src/utils/inboxEnvironment';

const environments: AgentEnvironmentConfig[] = [
  {id:'neo-nonprod',agentId:'neo-rules-agent',name:'Non-production',kind:'nonprod',enabled:true,revision:1,configured:true,canRetest:true,canManage:true,persisted:true,accessStatus:'unverified'},
  {id:'neo-prod',agentId:'neo-rules-agent',name:'Production',kind:'prod',enabled:true,revision:1,configured:true,canRetest:true,canManage:true,persisted:true,accessStatus:'unverified'},
  {id:'dev',agentId:'neo-rules-agent',name:'DEV',kind:'nonprod',enabled:true,revision:1,configured:true,canRetest:true,canManage:true,persisted:true,accessStatus:'unverified'},
  {id:'uat',agentId:'neo-rules-agent',name:'UAT',kind:'nonprod',enabled:false,revision:1,configured:true,canRetest:false,canManage:true,persisted:true,accessStatus:'unverified'},
];
const attempt: WorkflowAttempt = {id:'JOB-PROD',kind:'retest',status:'completed',environment:'prod',environmentId:'neo-prod',environmentLabel:'Production',revision:1,createdAt:'now'};
const source = {environment:'nonprod' as const,environmentId:'neo-nonprod',environmentLabel:'Non-production',environmentResult:attempt};

test('inbox environment choices use the same exact named IDs as the header including disabled history views',()=>{
  const control=inboxEnvironmentFilter(environments,'neo-prod','All',true);
  assert.equal(control.value,'neo-prod');assert.equal(control.options.find(item=>item.value==='neo-prod')?.label,'Production');
  assert.equal(control.options.find(item=>item.value==='uat')?.label,'UAT · disabled');
  assert.ok(control.options.some(item=>item.value==='dev'));
  assert.ok(!control.options.some(item=>item.value==='prod'));
});

test('selecting Production scopes results by its ID and clears the old source-kind predicate',()=>{
  assert.deepEqual(inboxEnvironmentSelection('neo-prod'),{workspaceId:'neo-prod',kind:'All'});
  assert.deepEqual(inboxEnvironmentSelection('All'),{workspaceId:'All',kind:'All'});
  assert.deepEqual(inboxEnvironmentSelection('uat'),{workspaceId:'uat',kind:'All'});
});

test('unassigned source is an explicit source-only choice, not a fictional named environment',()=>{
  assert.deepEqual(inboxEnvironmentSelection(unassignedSourceOption),{workspaceId:'All',kind:'unknown'});
  assert.equal(inboxEnvironmentFilter(environments,undefined,'unknown',true).value,unassignedSourceOption);
});

test('a linked Production row clearly keeps its Non-prod origin without mutating report metadata',()=>{
  const before=JSON.stringify(source);const cell=inboxRowEnvironment(source,environments,'neo-prod');
  assert.equal(cell.label,'Production');assert.equal(cell.linked,true);
  assert.match(cell.detail,/Linked validation attempt/);assert.match(cell.detail,/reported in Non-production/);
  assert.equal(JSON.stringify(source),before);
});

test('a promoted record shows its selected main environment while preserving its original source label',()=>{
  const promoted={...source,mainEnvironmentId:'neo-prod',mainEnvironmentKind:'prod' as const,mainEnvironmentLabel:'Production'};
  const cell=inboxRowEnvironment(promoted,environments);
  assert.equal(cell.label,'Production');assert.equal(cell.linked,true);
  assert.match(cell.detail,/Main environment/);assert.match(cell.detail,/originally reported in Non-production/);
  assert.equal(promoted.environmentId,'neo-nonprod');
});

test('all-environment RCA context follows a promoted main target while selected source filters remain exact',()=>{
  const promoted={...source,mainEnvironmentId:'neo-prod',mainEnvironmentKind:'prod' as const,mainEnvironmentLabel:'Production'};
  assert.equal(inboxRcaContext(promoted).kind,'attempt');
  assert.equal(inboxRcaContext(promoted,'neo-nonprod').kind,'source');
  assert.equal(inboxRcaContext(promoted,'neo-prod').kind,'attempt');
  assert.equal(inboxRcaContext({...promoted,environmentId:'neo-prod',environmentResult:null}).kind,'missing');
});

test('failed attempts establish a link without claiming that a Production answer succeeded',()=>{
  const item={...source,environmentResult:{...attempt,status:'failed' as const}};
  assert.equal(inboxRowEnvironment(item,environments,'neo-prod').linked,true);
  assert.equal(inboxRcaContext(item,'neo-prod').kind,'attempt');
});

test('native-source RCA remains available in its exact named environment without a retest',()=>{
  const item={...source,environmentResult:null};
  assert.equal(inboxRcaContext(item,'neo-nonprod').kind,'source');
  assert.equal(inboxRcaContext(item,'neo-prod').kind,'missing');
  assert.equal(inboxRcaContext(item).kind,'source');
});

test('named environments of the same kind never borrow each other results or the source RCA',()=>{
  const item={environment:'nonprod' as const,environmentId:'dev',environmentLabel:'DEV',
    environmentResult:{...attempt,environment:'nonprod' as const,environmentId:'uat',environmentLabel:'UAT'}};
  assert.equal(inboxRcaContext(item,'uat').kind,'attempt');
  assert.equal(inboxRcaContext(item,'dev').kind,'source');
  assert.equal(inboxRcaContext(item,'neo-nonprod').kind,'missing');
});

test('a standalone kind-filtered inbox still explains matching activity rather than changing the origin',()=>{
  const control=inboxEnvironmentFilter([],undefined,'prod',false);assert.equal(control.value,'prod');
  const cell=inboxRowEnvironment(source,[],undefined,'prod');
  assert.equal(cell.label,'Non-production');assert.match(cell.detail,/Linked Production activity/);
});

test('named inbox requests send the exact header ID without the old source-kind predicate and reset to page one',async(t)=>{
  const originalFetch=globalThis.fetch;const paths:string[]=[];
  const storageDescriptor=Object.getOwnPropertyDescriptor(globalThis,'localStorage');
  Object.defineProperty(globalThis,'localStorage',{configurable:true,value:{getItem:()=>null}});
  globalThis.fetch=async(url)=>{paths.push(String(url));return Response.json({items:[],total:20,page:1,pageSize:25});};
  t.after(()=>{globalThis.fetch=originalFetch;clearReadCache();
    if(storageDescriptor)Object.defineProperty(globalThis,'localStorage',storageDescriptor);else Reflect.deleteProperty(globalThis,'localStorage');
  });clearReadCache();
  for(const value of ['neo-prod','uat','All',unassignedSourceOption]){
    const selection=inboxEnvironmentSelection(value);
    await listFeedback({environmentId:selection.workspaceId,environment:selection.kind,page:1,pageSize:25});
  }
  assert.deepEqual(paths,[
    '/api/feedback?environment_id=neo-prod&page=1&page_size=25',
    '/api/feedback?environment_id=uat&page=1&page_size=25',
    '/api/feedback?page=1&page_size=25',
    '/api/feedback?environment=unknown&page=1&page_size=25',
  ]);
});
