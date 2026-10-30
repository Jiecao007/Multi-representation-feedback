/* BrowserDriver uses the real hint button and preserves native two-turn gating. */
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {fileURLToPath} from 'node:url';
import {BrowserDriver} from './browser_driver.mjs';

const app = fileURLToPath(new URL('../../app/', import.meta.url));
const baseURL = 'http://127.0.0.1:18766';
const image = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEElEQVR4nGP8zwACTGCSAQANHQEDgslx/wAAAABJRU5ErkJggg==';
const scene = {title: 'Hint driver fixture', objects: [{id: 'part', label: 'Student part',
  verbatim_text: '', kind: 'box', bbox: {x: 200, y: 200, width: 160, height: 100},
  glyph: [{kind: 'rect', points: [{x: 0, y: 0}, {x: 1000, y: 1000}], text: '', filled: false}],
  members: [], origin: 'student', confidence: 1, evidence: 'Visible student mark.', ambiguity: ''}], relations: []};
const payload = {scene, record: {id: 'hint-driver-fixture', title: scene.title,
  width: 1000, height: 1000, task: 'Explain your diagram.'}, original: image,
  question: {text: 'Explain your diagram.', image: ''}};
const calls = [], unexpected = [];
let version = 0, remaining = 0;
const outputDir = await fs.mkdtemp(path.join(os.tmpdir(), 'learner-hint-driver-'));
let driver;

try {
  driver = await BrowserDriver.open({baseURL, caseId: payload.record.id, outputDir, headless: true,
    setupPage: async page => page.route(baseURL + '/**', async route => {
      const request = route.request(), p = new URL(request.url()).pathname;
      if (p === '/api/resume-case') return route.fulfill({status: 204, body: ''});
      if (p === '/api/examples') return route.fulfill({json: [{id: payload.record.id, title: scene.title}]});
      if (p === '/api/examples/' + payload.record.id) return route.fulfill({json: payload});
      if (p === '/api/feedback') {
        const data = request.postDataJSON();
        calls.push(data);
        if (data.trigger === 'message') remaining = data.intent === 'hint' ? 2 : Math.max(0, remaining - 1);
        const content = data.intent === 'hint' ? 'Look at one relationship in your diagram.' : 'What relationship does this part show?';
        return route.fulfill({json: {session_id: 'hint-driver-session', version: ++version, drawing_version: 1,
          response_mode: data.trigger === 'message' ? 'dialogue' : 'review', acknowledgment: '', acknowledgment_ids: [],
          follow_up: content, content, focus_ids: ['part'], learning_goal: 'Explain your diagram.', revision_plan: '',
          edit_enabled: false, awaiting_revision_reason: false, hint_request_pending: remaining > 0,
          hint_turns_remaining: remaining, stage: 'thinking-dialogue', review: [], criteria: [],
          visual_action: 'highlight', visual_delivery: 'automatic'}});
      }
      if (p.startsWith('/api/')) {
        unexpected.push(p);
        return route.fulfill({status: 500, json: {error: 'Unexpected fixture endpoint.'}});
      }
      try {
        return route.fulfill({body: await fs.readFile(path.join(app, p === '/' ? 'index.html' : p.slice(1))),
          contentType: p.endsWith('.js') ? 'application/javascript' : p.endsWith('.css') ? 'text/css' : 'text/html'});
      } catch {
        return route.fulfill({status: 404, body: ''});
      }
    })});
  const initial = await driver.startSubmission({initialExplanation: 'I drew the parts.'});
  assert.equal(initial.ok, true);
  assert.ok((await fs.readFile(initial.observation.screenshot_path)).length > 0);
  assert.equal(initial.observation.elements[0].locator_description, 'Student part. View only.');
  assert.equal(Object.hasOwn(initial.observation.elements[0], 'label'), false);
  assert.deepEqual(initial.observation.elements[0].texts, []);
  const first = await driver.execute({type: 'request_hint'});
  assert.equal(first.ok, true);
  assert.deepEqual(first.result, {hint_request_status: 'reply_received', hint_delivered: true});
  assert.equal(calls.at(-1).intent, 'hint');
  const afterFirst = calls.length;
  const messages = await driver.page.locator('#messages .message').count();
  await driver.page.locator('#chatInput').fill('My unfinished answer');
  const blocked = await driver.execute({type: 'request_hint'});
  assert.equal(blocked.ok, true);
  assert.equal(blocked.result.hint_request_status, 'blocked_by_cooldown');
  assert.equal(blocked.result.hint_delivered, false);
  assert.equal(blocked.result.hint_turns_remaining, 2);
  assert.equal(calls.length, afterFirst);
  assert.equal(await driver.page.locator('#messages .message').count(), messages);
  assert.equal(await driver.page.locator('#chatInput').inputValue(), 'My unfinished answer');
  assert.equal(blocked.observation.status.chat, blocked.result.notice);
  assert.equal((await driver.execute({type: 'send_message', text: 'This part shows the first relationship.'})).ok, true);
  const blockedAgain = await driver.execute({type: 'request_hint'});
  assert.equal(blockedAgain.result.hint_turns_remaining, 1);
  assert.equal(calls.length, afterFirst + 1);
  assert.equal((await driver.execute({type: 'send_message', text: 'It connects to the next part.'})).ok, true);
  const allowed = await driver.execute({type: 'request_hint'});
  assert.equal(allowed.ok, true);
  assert.equal(allowed.result.hint_request_status, 'reply_received');
  assert.equal(allowed.result.hint_delivered, true);
  assert.equal(calls.length, afterFirst + 3);
  assert.equal(calls.at(-1).intent, 'hint');
  assert.deepEqual(driver.browserErrors, []);
  assert.deepEqual(unexpected, []);
  console.log('PASS BrowserDriver request_hint: native replies, two-turn cooldown notices, no blocked API/messages, preserved draft, and unlock after two Dialogue turns. All APIs mocked.');
} finally {
  await driver?.close();
  await fs.rm(outputDir, {recursive: true, force: true});
}
