import assert from 'node:assert/strict';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { BusinessTaxonomyFields } from '../src/components/BusinessTaxonomyFields';
import { businessClassificationLabel } from '../src/components/BusinessDomainPanel';
import { clearReadCache, createMyFeedback, getBusinessTaxonomyOptions, type BusinessTaxonomyOptions } from '../src/api/feedbackApi';

const options: BusinessTaxonomyOptions = { domains: ['O2C','F2S','P2P','R2R','Custom Operations'],
  subdomains: { O2C: ['Order Creation','Credit Management'], F2S: ['Batch Management','Lifecycle Management'], 'Custom Operations':['Custom area'] }, allowCustom: true };

test('submission classification has two native labelled dropdowns and explicit custom-entry choices', () => {
  const html = renderToStaticMarkup(React.createElement(BusinessTaxonomyFields, { domain:'F2S', subdomain:'Batch Management', options, onChange() {} }));
  assert.match(html, /<select[^>]*aria-label="Business domain"/);
  assert.match(html, /<select[^>]*aria-label="Business subdomain"/);
  assert.match(html, /value="known:F2S" selected=""/); assert.match(html, /value="known:Batch Management" selected=""/);
  assert.match(html, /Other — enter a custom domain/); assert.match(html, /Other — enter a custom subdomain/);
  assert.match(html, /Lifecycle Management/); assert.doesNotMatch(html, />Credit Management</);
  assert.doesNotMatch(html, /<datalist|role="combobox"/);
});

test('an existing custom classification remains selectable before saved choices finish loading', () => {
  const html = renderToStaticMarkup(React.createElement(BusinessTaxonomyFields, { domain:'Private custom label', subdomain:'Existing custom area', onChange() {} }));
  assert.match(html, /value="known:Private custom label" selected=""/);
  assert.match(html, /value="known:Existing custom area" selected=""/);
  assert.match(html, /Loading saved business classifications/);
});

test('read-only classifications disable both fields without replacing their values or offering a save', () => {
  const html = renderToStaticMarkup(React.createElement(BusinessTaxonomyFields, { domain:'Custom Operations', subdomain:'Custom area', options, disabled:true, onChange() {} }));
  assert.match(html, /aria-label="Business domain" disabled=""/);
  assert.match(html, /aria-label="Business subdomain" disabled=""/);
  assert.match(html, /value="known:Custom Operations" selected=""/);
  assert.doesNotMatch(html, /Submit|Save|Run RCA/);
});

test('user-supplied classification is not labelled as document-verified', () => {
  const label = businessClassificationLabel({ businessDomain:'Custom Operations', businessSubdomain:'Custom area', domainSource:'user_submitted', domainVerified:false });
  assert.equal(label, 'Provided at submission · not independently verified');
  assert.notEqual(label, 'Confirmed classification');
});

test('saved choices use the authenticated caller scope without adding a reporter override', async (t) => {
  const originalFetch = globalThis.fetch; const descriptor = Object.getOwnPropertyDescriptor(globalThis,'localStorage');
  Object.defineProperty(globalThis,'localStorage',{configurable:true,value:{getItem:()=>null}});
  const paths: string[] = [];
  globalThis.fetch = async (url) => { paths.push(String(url)); return Response.json(options); };
  t.after(() => { globalThis.fetch=originalFetch; clearReadCache(); if(descriptor)Object.defineProperty(globalThis,'localStorage',descriptor);else Reflect.deleteProperty(globalThis,'localStorage'); });
  clearReadCache(); assert.deepEqual(await getBusinessTaxonomyOptions(),options);
  assert.deepEqual(paths,['/api/my/business-taxonomy']);
});

test('feedback API sends explicit domain/subdomain fields without fabricating a verified classification', async (t) => {
  const originalFetch = globalThis.fetch; const descriptor = Object.getOwnPropertyDescriptor(globalThis,'localStorage');
  Object.defineProperty(globalThis,'localStorage',{configurable:true,value:{getItem:()=>null}});
  const calls: Array<{url:string;init:RequestInit}> = [];
  globalThis.fetch = async (url,init) => { calls.push({url:String(url),init:init || {}}); return Response.json({ id:'fixture-submission' }); };
  t.after(() => { globalThis.fetch=originalFetch;clearReadCache();if(descriptor)Object.defineProperty(globalThis,'localStorage',descriptor);else Reflect.deleteProperty(globalThis,'localStorage'); });
  await createMyFeedback({ user_verdict:'Incorrect', issue_categories:[], feedback_text:'Missing rule', impact:'Medium', business_domain:'Custom Operations', business_subdomain:'Custom area' });
  assert.equal(calls.length,1); assert.equal(calls[0].url,'/api/my/feedback');
  const payload = JSON.parse(String(calls[0].init.body));
  assert.equal(payload.business_domain,'Custom Operations'); assert.equal(payload.business_subdomain,'Custom area');
  assert.doesNotMatch(String(calls[0].init.body), /domain_verified|workbook_import|confirmed_rca|expected_behavior_verified/);
});
