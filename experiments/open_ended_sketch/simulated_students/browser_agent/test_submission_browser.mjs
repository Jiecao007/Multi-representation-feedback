/* Optional revision explanations are chosen per submission, never carried over. */
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {createRequire} from 'node:module';
import {BrowserDriver} from './browser_driver.mjs';

const require = createRequire(import.meta.url);
const {chromium} = require(process.env.PLAYWRIGHT_MODULE ||
  '/Users/jiecao/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const outputDir = await fs.mkdtemp(path.join(os.tmpdir(), 'learner-submission-driver-'));
const driver = new BrowserDriver();
driver.outputDir = outputDir;
driver.timeoutMs = 5000;
driver.sequence = 0;
driver.stopped = false;
driver.browserErrors = [];
const unexpectedRequests = [];

try {
  driver.browser = await chromium.launch({channel: 'chrome', headless: true});
  driver.context = await driver.browser.newContext();
  driver.page = await driver.context.newPage();
  driver.page.setDefaultTimeout(5000);
  driver.page.on('pageerror', error => driver.browserErrors.push(error.message));
  await driver.page.route('**/*', route => {
    unexpectedRequests.push(route.request().url());
    return route.abort();
  });
  // A local DOM fixture reproduces the app's optional reason field and its
  // submission bubble. It has no server, tutor, scene state, or model API.
  await driver.page.setContent(`<!doctype html><meta charset="utf-8">
    <section id="feedbackScreen">
      <button id="newSubmission">New submission</button>
      <textarea id="revisionReason">A previous, longer explanation.</textarea>
      <button id="reviewChanges">Review changes</button>
      <output id="submittedReason"></output><div id="messages"></div>
    </section>
    <script>
      document.querySelector('#reviewChanges').onclick = () => {
        const reason = document.querySelector('#revisionReason').value;
        document.querySelector('#submittedReason').textContent = reason;
        const bubble = document.createElement('div');
        bubble.className = 'message user';
        const text = document.createElement('div');
        text.className = 'message-text';
        text.textContent = ['I have finished my changes. Please review my diagram.',
          reason && 'My reason: ' + reason].filter(Boolean).join(' ');
        bubble.append(text); document.querySelector('#messages').append(bubble);
      };
    </script>`);

  const noReason = await driver.execute({type: 'submit_revisions', reason: null});
  assert.equal(noReason.ok, true);
  assert.equal(await driver.page.locator('#submittedReason').textContent(), '');
  assert.equal(noReason.observation.messages.at(-1).text,
    'I have finished my changes. Please review my diagram.');

  const explicit = 'This is −6.';
  const withReason = await driver.execute({type: 'submit_revisions', reason: explicit});
  assert.equal(withReason.ok, true);
  assert.equal(await driver.page.locator('#submittedReason').textContent(), explicit);
  assert.equal(withReason.observation.messages.at(-1).text,
    'I have finished my changes. Please review my diagram. My reason: ' + explicit);

  const nextWithoutReason = await driver.execute({type: 'submit_revisions'});
  assert.equal(nextWithoutReason.ok, true);
  assert.equal(await driver.page.locator('#submittedReason').textContent(), '');
  assert.equal(nextWithoutReason.observation.messages.at(-1).text,
    'I have finished my changes. Please review my diagram.');
  assert.equal(nextWithoutReason.observation.messages.length, 3);
  assert.deepEqual(driver.browserErrors, []);
  assert.deepEqual(unexpectedRequests, []);
  console.log('PASS BrowserDriver submit_revisions: null/omitted reasons clear retained text; explicit reason is preserved exactly. Fixed UI submission text remains. Local fixture only; zero server or model requests.');
} finally {
  await driver.close();
  await fs.rm(outputDir, {recursive: true, force: true});
}
