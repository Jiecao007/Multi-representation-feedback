/**
 * Student-facing browser driver for Draw to Explore.
 *
 * Reads only rendered DOM, accessibility labels, form controls and SVG geometry.
 * All changes go through existing UI controls and pointer/keyboard handlers.
 * The driver never reads app globals, response bodies, source payloads or tutor
 * assessments, and never changes a scene with page.evaluate().
 */
import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';

const require = createRequire(import.meta.url);
const DEFAULT_PLAYWRIGHT = '/Users/jiecao/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright';
const safeName = value => String(value || 'case').replace(/[^a-zA-Z0-9._-]+/g, '_').replace(/^\.+/, '').slice(0, 120) || 'case';
const quoted = value => JSON.stringify(String(value));
const finitePoint = point => point && typeof point === 'object' && Number.isFinite(point.x) && Number.isFinite(point.y);

export class BrowserDriver {
  /** Open an isolated Chrome browser and select an example; does not call tutor. */
  static async open({baseURL = 'http://127.0.0.1:8765', caseId = 'math-2', outputDir,
    headless = false, viewport = {width: 1600, height: 1100}, timeoutMs = 660000,
    playwrightModule = process.env.PLAYWRIGHT_MODULE || DEFAULT_PLAYWRIGHT,
    setupPage, autoStart = false, initialExplanation = ''} = {}) {
    const {chromium} = require(playwrightModule);
    const driver = new BrowserDriver();
    driver.outputDir = path.resolve(outputDir || path.join('outputs', 'browser_student', safeName(caseId)));
    driver.caseId = caseId;
    driver.timeoutMs = timeoutMs;
    driver.sequence = 0;
    driver.stopped = false;
    driver.browserErrors = [];
    await fs.mkdir(driver.outputDir, {recursive: true});
    driver.browser = await chromium.launch({channel: 'chrome', headless});
    try {
      driver.context = await driver.browser.newContext({viewport, acceptDownloads: true});
      driver.page = await driver.context.newPage();
      driver.page.setDefaultTimeout(10000);
      driver.page.on('pageerror', error => driver.browserErrors.push(error.message));
      // Used only by offline smoke fixtures to serve the real app with mock APIs.
      if (setupPage) await setupPage(driver.page);
      const url = new URL(baseURL);
      url.searchParams.delete('example');
      await driver.page.goto(url.href, {waitUntil: 'domcontentloaded', timeout: 60000});
      await driver.page.locator('#examples').waitFor({state: 'visible'});
      await driver.page.waitForFunction(id => [...document.querySelectorAll('#examples option')].some(option => option.value === id), caseId, {timeout: 30000});
      await driver.page.locator('#examples').selectOption(caseId);
      await driver.page.waitForFunction(() => {
        const start = document.querySelector('#submitImage');
        return start && !start.disabled && document.querySelector('#submissionPreview')?.hidden === false;
      }, null, {timeout: timeoutMs});
      await driver.observe({label: 'example_ready'});
      if (autoStart) await driver.startSubmission({initialExplanation});
      return driver;
    } catch (error) {
      await driver.close();
      throw error;
    }
  }

  /** Fill the common initial response through the submission UI, then submit. */
  async startSubmission({initialExplanation = '', task, goals} = {}) {
    if (task != null) await this.page.locator('#task').fill(String(task));
    if (goals != null) {
      const details = this.page.locator('details.requirements');
      if (await details.getAttribute('open') === null) await details.locator('summary').click();
      await this.page.locator('#goals').fill(Array.isArray(goals) ? goals.join('\n') : String(goals));
    }
    await this.page.locator('#explanation').fill(String(initialExplanation));
    await this._click('#submitImage');
    await this.page.locator('#feedbackScreen').waitFor({state: 'visible', timeout: this.timeoutMs});
    await this._waitIdle();
    // Task details are a normal learner-visible control; expose them to the agent.
    if (await this.page.locator('#questionContext').getAttribute('open') === null) {
      await this.page.locator('#questionHeading').click();
    }
    const observation = await this.observe({label: 'initial_feedback'});
    const error = observation.messages.at(-1)?.error ? observation.messages.at(-1).text : null;
    return {ok: !error, ...(error ? {error} : {}), observation};
  }

  async _waitIdle() {
    // The visible New submission button is disabled while feedback/revision
    // authorization is in flight. Its DOM state replaces private app variables.
    await this.page.waitForFunction(() => {
      const button = document.querySelector('#newSubmission');
      return button && !button.disabled && !document.querySelector('#feedbackScreen')?.hidden;
    }, null, {timeout: this.timeoutMs});
  }

  async _click(selector) {
    const button = this.page.locator(selector);
    await button.waitFor({state: 'visible'});
    if (!(await button.isEnabled())) throw new Error(`The visible control is unavailable: ${selector}`);
    await button.click();
  }

  _element(id, kind) {
    if (!id) throw new Error('An observed element id is required.');
    return this.page.locator(`#canvas ${kind ? '.' + kind : ':is(.object,.relation)'}[data-id=${quoted(id)}]`);
  }

  async _select(id, kind) {
    const element = this._element(id, kind);
    await element.waitFor({state: 'visible'});
    await element.focus();
    await this.page.keyboard.press('Enter');
    return id;
  }

  async _selectedId(kind = 'object') {
    return this.page.locator(`#canvas .${kind}.selected`).getAttribute('data-id');
  }

  async _screenPoint(point, space = 'canvas') {
    if (!finitePoint(point)) throw new Error('A point with finite numeric x and y is required.');
    if (space === 'screen') return {x: point.x, y: point.y};
    if (space !== 'canvas') throw new Error('space must be canvas or screen.');
    return this.page.locator('#sceneRoot').evaluate((root, point) => {
      const matrix = root.getScreenCTM();
      const result = new DOMPoint(point.x, point.y).matrixTransform(matrix);
      return {x: result.x, y: result.y};
    }, point);
  }

  async _canvasPoint(point) {
    return this.page.locator('#sceneRoot').evaluate((root, point) => {
      const result = new DOMPoint(point.x, point.y).matrixTransform(root.getScreenCTM().inverse());
      return {x: result.x, y: result.y};
    }, point);
  }

  async _itemPoint(id) {
    const item = this._element(id);
    return item.evaluate(group => {
      // The existing object halo is its visible interaction area. Relations use
      // their rendered polyline, rather than a bounding-box point off the line.
      const line = group.classList.contains('relation') && group.querySelector('polyline.ink');
      if (line) {
        const point = line.getPointAtLength(line.getTotalLength() / 2);
        const screen = point.matrixTransform(line.getScreenCTM());
        return {x: screen.x, y: screen.y};
      }
      const rect = (group.querySelector('.halo') || group).getBoundingClientRect();
      return {x: rect.x + rect.width / 2, y: rect.y + rect.height / 2};
    });
  }

  async _drag(from, to) {
    await this.page.mouse.move(from.x, from.y);
    await this.page.mouse.down();
    try {
      await this.page.mouse.move(to.x, to.y, {steps: 12});
    } finally {
      await this.page.mouse.up();
    }
  }

  async _move(action) {
    await this._select(action.id);
    await this._assertEditing();
    const from = await this._itemPoint(action.id);
    const space = action.space || 'canvas';
    let to;
    if (finitePoint(action.to)) to = await this._screenPoint(action.to, space);
    else if (Number.isFinite(action.dx) || Number.isFinite(action.dy)) {
      const origin = space === 'screen' ? from : await this._canvasPoint(from);
      to = await this._screenPoint({x: origin.x + (action.dx || 0), y: origin.y + (action.dy || 0)}, space);
    } else throw new Error('move requires to:{x,y}, or dx and/or dy.');
    await this._drag(from, to);
    return {id: action.id, requested_screen_point: to};
  }

  async _assertEditing() {
    if (await this.page.locator('#canvas').getAttribute('data-editable') !== 'true') {
      throw new Error('The canvas is view only. Begin a revision to edit it.');
    }
  }

  async _editText(action, add = false) {
    if (!add) await this._select(action.id, 'object');
    await this._click(add ? '#addNote' : '#rename');
    await this.page.locator('#newName').fill(String(action.text ?? ''));
    if (!add && action.glyphTexts) {
      for (const [index, text] of Object.entries(action.glyphTexts)) {
        await this.page.locator(`#textParts textarea[data-glyph-index=${quoted(index)}]`).fill(String(text));
      }
    }
    await this._click('#renameForm button[type=submit]');
    if (await this.page.locator('#renameDialog').isVisible()) throw new Error('The text dialog did not accept this value.');
    return {id: await this._selectedId(), text: action.text};
  }

  async _addObject(action) {
    if (!(await this.page.locator('#libraryDialog').isVisible())) await this._click('#openLibrary');
    await this.page.locator('#libraryDialog').waitFor({state: 'visible'});
    if (action.topic != null) {
      const select = this.page.locator('#libraryTopic');
      const values = await select.locator('option').evaluateAll(options => options.map(option => option.value));
      await select.selectOption(values.includes(action.topic) ? {value: action.topic} : {label: action.topic});
    }
    // Omitting label lets the student inspect this normal object-library UI.
    if (action.label == null) return {library_open: true};
    await this.page.locator('#libraryItems .library-item').filter({has: this.page.getByText(String(action.label), {exact: true})}).first().click();
    if (await this.page.locator('#libraryDialog').isVisible()) throw new Error('The object library did not add this object.');
    return {id: await this._selectedId(), label: action.label};
  }

  async _connection(action, edit = false) {
    if (edit) await this._select(action.id, 'relation');
    await this._click(edit ? '#editConnection' : '#connect');
    for (const [field, selector] of [['from', '#connectionFrom'], ['to', '#connectionTo'], ['shape', '#connectionShape'], ['direction', '#connectionDirection']]) {
      if (action[field] != null) await this.page.locator(selector).selectOption(String(action[field]));
    }
    if (action.label != null) await this.page.locator('#connectionLabel').fill(String(action.label));
    await this._click('#connectionForm button[type=submit]');
    if (await this.page.locator('#connectionDialog').isVisible()) throw new Error('The connection dialog did not accept these values.');
    return {id: await this._selectedId('relation')};
  }

  async _reshape(action) {
    await this._select(action.id, 'relation');
    await this._assertEditing();
    const suffix = action.endpoint != null ? `[data-endpoint=${quoted(action.endpoint)}]` : action.control != null ? `[data-control=${quoted(action.control)}]` : '';
    if (!suffix) throw new Error('reshape_connection requires an endpoint or an observed control index.');
    const handle = this.page.locator(`#canvas [data-id=${quoted(action.id)}]${suffix}`);
    await handle.waitFor({state: 'visible'});
    const box = await handle.boundingBox();
    const from = {x: box.x + box.width / 2, y: box.y + box.height / 2};
    const to = await this._screenPoint(action.to, action.space || 'canvas');
    await this._drag(from, to);
    return {id: action.id, endpoint: action.endpoint ?? null, control: action.control ?? null, requested_screen_point: to};
  }

  /** Execute one student-chosen action. UI failures are returned without repair. */
  async execute(action) {
    if (!action || typeof action.type !== 'string') return {
      ok: false, error: 'An action.type is required.', action,
      observation: await this.observe({label: 'invalid_action'})};
    if (this.stopped) return {ok: false, error: 'This student has stopped.', action,
      observation: await this.observe({label: 'already_stopped'})};
    let result = {}, error = null;
    const previousErrorCount = await this.page.locator('#messages .message.error').count();
    try {
      switch (action.type) {
        case 'send_message':
          await this.page.locator('#chatInput').fill(String(action.text ?? ''));
          if (!String(action.text ?? '').trim()) throw new Error('A nonempty chat message is required.');
          await this._click('#send');
          await this._waitIdle();
          break;
        case 'request_hint': {
          const replies = this.page.locator('#messages .message:not(.user):not(.error)');
          const beforeReplies = await replies.count();
          await this._click('[data-intent="hint"]');
          await this._waitIdle();
          const notice = (await this.page.locator('#chatStatus').innerText()).trim();
          const cooldown = /^Please answer the Dialogue question for (\d+) more turns?, then try again\.$/.exec(notice);
          if (cooldown) {
            // The click succeeded, but the native UI declined another hint.
            // This is an expected interaction outcome, not an API/UI failure.
            result = {hint_request_status: 'blocked_by_cooldown', hint_delivered: false,
              hint_turns_remaining: Number(cooldown[1]), notice};
          } else if (await replies.count() > beforeReplies) {
            result = {hint_request_status: 'reply_received', hint_delivered: true};
          } else if (await this.page.locator('#messages .message.error').count() > previousErrorCount) {
            result = {hint_request_status: 'app_error', hint_delivered: false};
          } else {
            throw new Error('The hint click produced neither a visible reply nor a cooldown notice.');
          }
          break;
        }
        case 'show_feedback': {
          const messages = this.page.locator('#messages .message');
          const index = action.messageIndex;
          const button = index == null ? this.page.locator('#messages .inline-show').last() :
            (index < 0 ? messages.nth((await messages.count()) + index) : messages.nth(index)).locator('.inline-show');
          if (!(await button.count())) throw new Error('This conversation message has no Show control.');
          await button.click();
          break;
        }
        case 'begin_revision': await this._click('[data-intent="begin_revision"]'); await this._waitIdle(); break;
        case 'exit_revision': await this._click('#exitRevision'); await this._waitIdle(); break;
        case 'return_to_draft': await this._click('#returnToDraft'); break;
        case 'select': result = {id: await this._select(action.id)}; break;
        case 'add_text': result = await this._editText(action, true); break;
        case 'edit_text': result = await this._editText(action); break;
        case 'add_object': result = await this._addObject(action); break;
        case 'move': result = await this._move(action); break;
        case 'add_connection': result = await this._connection(action); break;
        case 'edit_connection': result = await this._connection(action, true); break;
        case 'reshape_connection': result = await this._reshape(action); break;
        case 'resize': {
          await this._select(action.id);
          const steps = action.steps ?? 1;
          if (!Number.isInteger(steps) || steps < 1 || steps > 20) throw new Error('resize steps must be an integer from 1 to 20.');
          if (!['larger', 'smaller'].includes(action.direction)) throw new Error('resize direction must be larger or smaller.');
          for (let i = 0; i < steps; i++) await this._click('#' + action.direction);
          break;
        }
        case 'delete': await this._select(action.id); await this._click('#deletePart'); break;
        case 'undo': await this._click('#undo'); break;
        case 'submit_revisions':
          // A null optional reason means this submission supplies no explanation.
          // Clear any text retained from an earlier draft; preserve explicit text.
          await this.page.locator('#revisionReason').fill(String(action.reason ?? ''));
          await this._click('#reviewChanges');
          await this._waitIdle();
          break;
        case 'cancel_dialog': {
          const visible = this.page.locator('dialog[open]');
          const id = action.id || await visible.first().getAttribute('id');
          const selectors = {renameDialog: '#cancelRename', connectionDialog: '#cancelConnection', libraryDialog: '#closeLibrary', taskFigureDialog: '#closeTaskFigure'};
          if (!selectors[id]) throw new Error('No matching open dialog can be closed.');
          await this._click(selectors[id]);
          break;
        }
        case 'stop': this.stopped = true; result = {stopped: true}; break;
        default: throw new Error(`Unsupported student action: ${action.type}`);
      }
      if (await this.page.locator('#messages .message.error').count() > previousErrorCount) {
        error = await this.page.locator('#messages .message.error .message-text').last().innerText();
      }
    } catch (cause) {
      error = cause.message;
    }
    const observation = await this.observe({label: action.type});
    return {ok: !error, action, result, ...(error ? {error} : {}), observation};
  }

  /** Observe the learner's rendered workspace, then save a screenshot. */
  async observe({label = 'observation'} = {}) {
    const observation = await this.page.evaluate(() => {
      const visible = element => {
        if (!element || element.closest('[hidden]')) return false;
        const style = getComputedStyle(element), box = element.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' && box.width > 0 && box.height > 0;
      };
      const box = rect => ({x: rect.x, y: rect.y, width: rect.width, height: rect.height});
      const text = selector => {
        const element = document.querySelector(selector);
        return visible(element) ? element.innerText || element.textContent || '' : '';
      };
      const canvas = document.querySelector('#canvas'), root = document.querySelector('#sceneRoot');
      const elements = visible(canvas) ? [...canvas.querySelectorAll('.object,.relation')].map(element => {
        const line = element.querySelector('polyline.ink');
        return {id: element.getAttribute('data-id'), kind: element.classList.contains('object') ? 'object' : 'relation',
          locator_description: element.getAttribute('aria-label'), texts: [...element.querySelectorAll('text')].map(node => node.textContent),
          selected: element.classList.contains('selected'), highlighted: element.classList.contains('highlight'),
          bounds: box(element.getBoundingClientRect()), canvas_bounds: box(element.getBBox()),
          ...(line ? {points: [...line.points].map(point => ({x: point.x, y: point.y})),
            arrow_start: line.hasAttribute('marker-start'), arrow_end: line.hasAttribute('marker-end')} : {})};
      }) : [];
      const handles = visible(canvas) ? [...canvas.querySelectorAll('[data-endpoint],[data-control]')].map(element => {
        const bounds = element.getBoundingClientRect(), local = element.getBBox();
        return {id: element.getAttribute('data-id'), endpoint: element.getAttribute('data-endpoint'),
          control: element.hasAttribute('data-control') ? Number(element.getAttribute('data-control')) : null,
          locator_description: element.getAttribute('aria-label'), screen_center: {x: bounds.x + bounds.width / 2, y: bounds.y + bounds.height / 2},
          canvas_center: {x: local.x + local.width / 2, y: local.y + local.height / 2}};
      }) : [];
      const controls = [...document.querySelectorAll('button')].filter(visible).map(button => ({
        id: button.id || null, label: button.getAttribute('aria-label') || button.innerText,
        disabled: button.disabled, pressed: button.getAttribute('aria-pressed')}));
      const dialogs = [...document.querySelectorAll('dialog[open]')].filter(visible).map(dialog => ({
        id: dialog.id, title: dialog.querySelector('h3')?.innerText || '', text: dialog.innerText,
        fields: [...dialog.querySelectorAll('input,textarea,select')].filter(visible).map(field => ({
          id: field.id || null, label: field.labels?.[0]?.innerText || field.getAttribute('aria-label') || '', value: field.value,
          glyph_index: field.getAttribute('data-glyph-index'),
          ...(field.tagName === 'SELECT' ? {options: [...field.options].map(option => ({value: option.value, label: option.textContent}))} : {})})),
        ...(dialog.id === 'libraryDialog' ? {items: [...dialog.querySelectorAll('.library-item')].map(button => ({label: button.querySelector('span')?.innerText || button.innerText}))} : {})}));
      return {visible_text: document.body.innerText, task: text('#questionText') || text('#task'), goal: text('#learningGoal'),
        messages: [...document.querySelectorAll('#messages .message')].map((message, index) => ({index,
          role: message.classList.contains('user') ? 'user' : 'assistant', text: message.querySelector('.message-text')?.innerText || '',
          error: message.classList.contains('error'), show_available: !!message.querySelector('.inline-show')})),
        controls, elements, handles, dialogs,
        canvas: visible(canvas) ? {view_box: canvas.getAttribute('viewBox'), screen_bounds: box(canvas.getBoundingClientRect()),
          coordinate_system: 'sceneRoot SVG coordinates', editable: canvas.getAttribute('data-editable') === 'true',
          screen_transform: root ? (() => {const m = root.getScreenCTM(); return {a:m.a,b:m.b,c:m.c,d:m.d,e:m.e,f:m.f};})() : null} : null,
        status: {chat: text('#chatStatus'), draft: text('#draftStatus'), change_hint: text('#changeHint'),
          model_badge: text('#modelBadge'), selected_name: text('#selectedName')}};
    });
    const screenshotPath = path.join(this.outputDir, `${String(this.sequence++).padStart(4, '0')}_${safeName(label)}.png`);
    await this.page.screenshot({path: screenshotPath, fullPage: true});
    return {...observation, screenshot_path: screenshotPath, screenshotPath, stopped: this.stopped};
  }

  /** Download through the existing Export case HTML and Save buttons. */
  async exportArtifacts({label = this.caseId} = {}) {
    await this._waitIdle();
    const download = async (selector, suffix) => {
      const button = this.page.locator(selector);
      await button.waitFor({state: 'visible'});
      if (!(await button.isEnabled())) throw new Error(`The visible control is unavailable: ${selector}`);
      const pending = this.page.waitForEvent('download', {timeout: 120000});
      await button.click();
      const item = await pending;
      const outputPath = path.join(this.outputDir, safeName(label) + suffix);
      await item.saveAs(outputPath);
      const failure = await item.failure();
      if (failure) throw new Error(failure);
      return {path: outputPath, suggested_filename: item.suggestedFilename()};
    };
    const html = await download('#exportCase', '.case.html');
    const saved = await download('#save', '.exploration.json');
    const observation = await this.observe({label: 'exported'});
    return {html, saved, htmlPath: html.path, savePath: saved.path, explorationPath: saved.path, jsonPath: saved.path, observation};
  }

  async close() {
    await this.context?.close().catch(() => {});
    await this.browser?.close().catch(() => {});
  }
}

export default BrowserDriver;
