/* Standalone, submitted-only case rendering. No live UI, server or mutable state. */
(function (root) {
  'use strict';
  const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  const str = value => typeof value === 'string' ? value : typeof value === 'number' && Number.isFinite(value) ? String(value) : '';
  const esc = value => str(value).replace(/[&<>"']/g, character => ESC[character]);
  const list = value => Array.isArray(value) ? value : [];
  const obj = value => value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  const finite = value => typeof value === 'number' && Number.isFinite(value);
  const coordinate = value => finite(value) && value >= 0 && value <= 1000;
  const point = value => value && coordinate(value.x) && coordinate(value.y);
  const num = value => Math.round(value * 1000) / 1000;
  const ink = '#444052';
  const color = value => /^#[0-9a-f]{6}$/i.test(str(value)) ? value : ink;
  const moves = {
    recognize_strengths: 'Recognize strengths', press_for_accuracy: 'Press for accuracy',
    revoice: 'Revoice', ask_for_clarification: 'Ask for clarification',
    revoice_or_clarify: 'Revoice or clarify', build_on_prior_knowledge: 'Build on prior knowledge',
    invite_elaboration_reasoning: 'Invite elaboration and reasoning', prompt_reflection: 'Prompt reflection',
    provide_hints_guidance: 'Provide hints or guidance', propose_revision_plan: 'Propose a revision plan',
    invite_dialogue: 'Invite dialogue', clarify_goals: 'Clarify goals'
  };
  const phases = { 'feed-up': 'Feed up', 'feed-back': 'Feedback', feedback: 'Feedback', 'feed-forward': 'Feedforward' };
  const stages = {
    recognition: 'Recognizing strengths', inquiry: 'Checking the current issue',
    'thinking-dialogue': 'Supporting learning', 'revision-planning': 'Preparing a revision',
    'revision-explanation': 'Explaining a revision', dialogue: 'Further dialogue', complete: 'Completed'
  };

  // Validate both the MIME allowlist and raster signature; never embed arbitrary URLs/SVG.
  function raster(value) {
    const match = /^data:image\/(png|jpeg|webp);base64,([a-z0-9+/\r\n]*={0,2})$/i.exec(str(value).trim());
    if (!match) return '';
    const body = match[2].replace(/[\r\n]/g, '');
    if (!body || body.length % 4) return '';
    const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
    const bytes = []; let accumulator = 0, bits = 0;
    for (const character of body.slice(0, 24)) {
      if (character === '=') break;
      const index = alphabet.indexOf(character); if (index < 0) return '';
      accumulator = (accumulator << 6) | index; bits += 6;
      if (bits >= 8) { bits -= 8; bytes.push((accumulator >> bits) & 255); }
    }
    const mime = match[1].toLowerCase();
    const valid = mime === 'png' ? [137, 80, 78, 71, 13, 10, 26, 10].every((v, i) => bytes[i] === v)
      : mime === 'jpeg' ? bytes[0] === 255 && bytes[1] === 216 && bytes[2] === 255
      : [82, 73, 70, 70].every((v, i) => bytes[i] === v) && [87, 69, 66, 80].every((v, i) => bytes[i + 8] === v);
    return valid ? `data:image/${mime};base64,${body}` : '';
  }

  function dimensions(value, fallback) {
    const data = obj(value), backup = obj(fallback);
    const width = finite(data.width) && data.width > 0 ? data.width : finite(backup.width) && backup.width > 0 ? backup.width : 1000;
    const height = finite(data.height) && data.height > 0 ? data.height : finite(backup.height) && backup.height > 0 ? backup.height : width;
    return { width, height, ratio: height / width };
  }
  function validBox(value) {
    const box = obj(value);
    return coordinate(box.x) && coordinate(box.y) && finite(box.width) && finite(box.height)
      && box.width > 0 && box.height > 0 && box.x + box.width <= 1000.01 && box.y + box.height <= 1000.01;
  }
  function glyph(object, ratio) {
    const box = object.bbox, strokes = list(object.glyph);
    if (strokes.length && strokes.every(stroke => stroke.kind === 'text')) {
      const lines = (str(object.verbatim_text) || strokes.map(stroke => str(stroke.text)).join('\n')).split('\n');
      const physicalHeight = box.height * ratio;
      const size = Math.min(physicalHeight / (lines.length * 1.2), box.width / (Math.max(1, ...lines.map(line => Array.from(line).length)) * .55));
      return lines.map((line, i) => `<text x="${num(box.x)}" y="${num(box.y * ratio + physicalHeight / 2 + (i - (lines.length - 1) / 2) * size * 1.2)}" font-size="${num(size)}" dominant-baseline="middle" fill="${color(strokes[i] && strokes[i].color)}">${esc(line)}</text>`).join('');
    }
    return strokes.map(stroke => {
      if (!stroke || !['polyline', 'polygon', 'ellipse', 'rect', 'text'].includes(stroke.kind)) return '';
      const points = list(stroke.points); if (!points.every(point)) return '';
      const paint = color(stroke.color);
      if (stroke.kind === 'text') {
        if (!points.length) return '';
        const p = points[0], size = Math.max(1, Math.min(26, box.height * .36, box.width * (1000 - p.x) / 1000 / (Math.max(1, str(stroke.text).length) * .55)));
        return `<text x="${num(box.x + p.x * box.width / 1000)}" y="${num((box.y + p.y * box.height / 1000) * ratio)}" font-size="${num(size * ratio)}" dominant-baseline="hanging" fill="${paint}">${esc(stroke.text)}</text>`;
      }
      if (points.length < (stroke.kind === 'polygon' ? 3 : 2)) return '';
      const attributes = `fill="${stroke.filled ? paint : 'none'}" fill-opacity="${stroke.filled ? .28 : 1}" stroke="${paint}" stroke-width="1.8" vector-effect="non-scaling-stroke" stroke-linejoin="round" stroke-linecap="round"`;
      let shape;
      if (stroke.kind === 'rect' || stroke.kind === 'ellipse') {
        const a = points[0], z = points[1], x = Math.min(a.x, z.x), y = Math.min(a.y, z.y), width = Math.abs(a.x - z.x), height = Math.abs(a.y - z.y);
        shape = stroke.kind === 'rect' ? `<rect x="${num(x)}" y="${num(y)}" width="${num(width)}" height="${num(height)}" ${attributes}/>`
          : `<ellipse cx="${num(x + width / 2)}" cy="${num(y + height / 2)}" rx="${num(width / 2)}" ry="${num(height / 2)}" ${attributes}/>`;
      } else shape = `<${stroke.kind} points="${points.map(p => `${num(p.x)},${num(p.y)}`).join(' ')}" ${attributes}/>`;
      return `<g transform="translate(${num(box.x)} ${num(box.y * ratio)}) scale(${num(box.width / 1000)} ${num(box.height * ratio / 1000)})">${shape}</g>`;
    }).join('');
  }
  function arrowAt(points, fraction) {
    const lengths = []; let total = 0;
    for (let i = 1; i < points.length; i++) { const length = Math.hypot(points[i].x - points[i - 1].x, points[i].y - points[i - 1].y); lengths.push(length); total += length; }
    if (!total) return '';
    let distance = total * fraction;
    for (let i = 0; i < lengths.length; i++) {
      const length = lengths[i], a = points[i], b = points[i + 1];
      if ((distance <= length || i === lengths.length - 1) && length > 0) {
        const t = distance / length;
        return `translate(${num(a.x + (b.x - a.x) * t)} ${num(a.y + (b.y - a.y) * t)}) rotate(${num(Math.atan2(b.y - a.y, b.x - a.x) * 180 / Math.PI)})`;
      }
      distance -= length;
    }
    return '';
  }
  function mechanismRoutes(scene, mechanism, ratio) {
    const objects = new Set(list(scene.objects).map(object => str(object.id)));
    const relations = new Map(list(scene.relations).map(relation => [str(relation.id), relation]));
    const routes = [];
    for (const path of list(obj(mechanism).paths)) {
      const segments = [], seen = new Set(); let end = '', valid = true;
      for (const step of list(obj(path).steps)) {
        const relation = relations.get(str(obj(step).relation_id));
        if (!relation || !['forward', 'backward'].includes(step.direction) || seen.has(relation.id)
          || list(relation.points).length < 2 || !relation.points.every(point)) { valid = false; break; }
        const start = step.direction === 'forward' ? relation.source : relation.target;
        const stop = step.direction === 'forward' ? relation.target : relation.source;
        if (!objects.has(start) || !objects.has(stop) || (segments.length && end !== start)) { valid = false; break; }
        const points = relation.points.map(p => ({ x: p.x, y: p.y * ratio }));
        if (step.direction === 'backward') points.reverse();
        segments.push(points); seen.add(relation.id); end = stop;
      }
      if (valid && segments.length) routes.push({ label: str(path.label) || 'Illustrated path', segments, color: routes.length % 2 ? '#16838a' : '#7950ba' });
    }
    return routes;
  }
  function drawScene(input, size, visual, prefix) {
    const scene = obj(input), objects = list(scene.objects).map(obj), relations = list(scene.relations).map(obj);
    if (!objects.length && !relations.length) return '<p class="muted">No saved editable diagram is available for this version.</p>';
    const ratio = size.ratio, focus = new Set(list(obj(visual).ids).map(str)), accent = obj(visual).tone === 'response' ? '#7950ba' : '#16838a';
    const map = new Map(objects.map(object => [str(object.id), object]));
    function expand(id, visited) {
      if (visited.has(id)) return; visited.add(id);
      for (const child of list(obj(map.get(id)).members)) { focus.add(str(child)); expand(str(child), visited); }
    }
    for (const id of [...focus]) expand(id, new Set());
    const arrow = `${prefix}-arrow`;
    let svg = `<svg class="diagram-svg" xmlns="http://www.w3.org/2000/svg" viewBox="-24 ${num(-24 * ratio)} 1048 ${num(1048 * ratio)}" width="1000" height="${num(1000 * ratio)}" role="img" aria-label="Saved submitted diagram${focus.size ? ' with matching visual feedback' : ''}"><defs><marker id="${arrow}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 1 1 L 9 5 L 1 9" fill="none" stroke="context-stroke" stroke-width="1.8"/></marker></defs><g font-family="Arial, sans-serif">`;
    for (const relation of relations) {
      const points = list(relation.points); if (points.length < 2 || !points.every(point)) continue;
      const plotted = points.map(p => `${num(p.x)},${num(p.y * ratio)}`).join(' ');
      if (focus.has(str(relation.id))) svg += `<polyline class="matching-highlight" points="${plotted}" fill="none" stroke="${accent}" stroke-width="11" stroke-opacity=".2" vector-effect="non-scaling-stroke"/>`;
      const markers = `${['backward', 'both'].includes(relation.direction) ? ` marker-start="url(#${arrow})"` : ''}${['forward', 'both'].includes(relation.direction) ? ` marker-end="url(#${arrow})"` : ''}`;
      svg += `<polyline points="${plotted}" fill="none" stroke="${focus.has(str(relation.id)) ? accent : color(relation.color)}" stroke-width="${focus.has(str(relation.id)) ? 3 : 2}" stroke-linejoin="round" vector-effect="non-scaling-stroke"${markers}/>`;
      if (str(relation.verbatim_text) && point(relation.label_position)) svg += `<text x="${num(relation.label_position.x)}" y="${num(relation.label_position.y * ratio)}" font-size="22" fill="${color(relation.color)}">${esc(relation.verbatim_text)}</text>`;
    }
    for (const object of objects) {
      if (!validBox(object.bbox) || list(object.members).length) continue;
      const box = object.bbox;
      if (focus.has(str(object.id))) svg += `<rect class="matching-highlight" x="${num(box.x - 6)}" y="${num((box.y - 6) * ratio)}" width="${num(box.width + 12)}" height="${num((box.height + 12) * ratio)}" rx="6" fill="${accent}" fill-opacity=".08" stroke="${accent}" stroke-width="2" stroke-dasharray="5 4" vector-effect="non-scaling-stroke"/>`;
      svg += `<g><title>${esc(object.label || object.verbatim_text || 'Diagram mark')}</title>${glyph(object, ratio)}</g>`;
    }
    const routes = obj(visual).action === 'trace' ? mechanismRoutes(scene, obj(visual).mechanism, ratio) : [];
    for (const route of routes) for (const points of route.segments) {
      const plotted = points.map(p => `${num(p.x)},${num(p.y)}`).join(' '), transform = arrowAt(points, .56);
      svg += `<polyline class="mechanism-track" points="${plotted}" fill="none" stroke="${route.color}" stroke-width="3" stroke-opacity=".55" stroke-linejoin="round" vector-effect="non-scaling-stroke"/>`;
      if (transform) svg += `<g class="static-flow-arrow" transform="${transform}"><path d="M -8 -6 L 3 0 L -8 6" fill="none" stroke="${route.color}" stroke-width="3" stroke-linecap="round"/></g>`;
      const path = points.map((p, i) => `${i ? 'L' : 'M'} ${num(p.x)} ${num(p.y)}`).join(' ');
      svg += `<g class="motion-arrow"><path d="M -8 -6 L 3 0 L -8 6" fill="none" stroke="${route.color}" stroke-width="3" stroke-linecap="round"/><animateMotion path="${path}" dur="4s" begin="indefinite" repeatCount="indefinite" rotate="auto"/></g>`;
    }
    svg += '</g></svg><p class="diagram-scroll-note">Scroll sideways to inspect the full diagram on a small screen.</p>';
    const condition = str(obj(obj(visual).mechanism).condition);
    if (obj(visual).action === 'trace') {
      svg += `<div class="mechanism-caption">${condition ? `<p class="mechanism-condition"><strong>Demonstration condition:</strong> ${esc(condition)}</p>` : ''}${routes.length ? `<div class="path-legend">${routes.map(route => `<span><i style="background:${route.color}"></i>${esc(route.label)}</span>`).join('')}</div><p class="muted small">Qualitative overlays follow saved relations. Static arrows remain visible when printing.</p><button type="button" class="replay-mechanism">Replay arrows</button>` : '<p class="muted small">This saved path cannot be replayed reliably. The submitted diagram is shown without an invented route.</p>'}</div>`;
    }
    return svg;
  }

  function avatar(role) {
    if (role === 'system') return '<span class="avatar system-avatar" aria-hidden="true"><svg viewBox="0 0 48 48"><circle cx="24" cy="24" r="22" fill="#f5e8dd"/><path d="M24 12 37 35H11Z" fill="none" stroke="#9d6539" stroke-width="2.5"/><path d="M24 20v7m0 4v1" stroke="#9d6539" stroke-width="2.5" stroke-linecap="round"/></svg></span>';
    const tutor = role === 'assistant', background = tutor ? '#eee7f7' : '#def0ec', hair = tutor ? '#735299' : '#28796e';
    return `<span class="avatar ${tutor ? 'tutor-avatar' : 'learner-avatar'}" aria-hidden="true"><svg viewBox="0 0 48 48"><circle cx="24" cy="24" r="23" fill="${background}"/><path d="M11 45c1-10 6-14 13-14s12 4 13 14" fill="${hair}"/><ellipse cx="24" cy="22" rx="12" ry="14" fill="#f1c6a4"/><path d="M12 22C9 8 18 5 27 7c8 1 12 8 8 17l-4-12c-5 6-12 5-19 10" fill="${hair}"/><circle cx="19" cy="22" r="1.3" fill="#47314e"/><circle cx="29" cy="22" r="1.3" fill="#47314e"/><path d="M19 28q5 5 10 0" fill="none" stroke="#a85e62" stroke-width="1.7" stroke-linecap="round"/>${tutor ? '<g fill="none" stroke="#634574" stroke-width="1.3"><rect x="14" y="18" width="9" height="8" rx="3"/><rect x="25" y="18" width="9" height="8" rx="3"/><path d="M23 21h2"/></g>' : ''}</svg></span>`;
  }
  function imageFigure(value, label) {
    const source = raster(value);
    return source ? `<figure class="image-figure"><img src="${source}" alt="${esc(label)}"/><figcaption>${esc(label)}</figcaption></figure>` : '';
  }
  function metadata(entry) {
    const feedback = obj(entry.feedback), rows = [];
    const activeMoves = Array.isArray(feedback.talk_moves) && feedback.talk_moves.length ? feedback.talk_moves : [feedback.talk_move];
    const labels = [...new Set(activeMoves)].map(id => moves[id]).filter(Boolean);
    if (labels.length) rows.push([labels.length > 1 ? 'Moves' : 'Move', labels.join(' + ')]);
    if (phases[feedback.phase]) rows.push(['Function', phases[feedback.phase]]);
    if (stages[feedback.stage]) rows.push(['Stage', stages[feedback.stage]]);
    if (Number.isInteger(feedback.drawing_version) && feedback.drawing_version >= 0) rows.push(['Submitted version', String(feedback.drawing_version)]);
    if (str(feedback.revision_plan)) rows.push(['Revision plan', str(feedback.revision_plan)]);
    return rows.length ? `<details class="move-details"><summary>Move details</summary><dl>${rows.map(([name, value]) => `<div><dt>${name}</dt><dd>${esc(value)}</dd></div>`).join('')}</dl></details>` : '';
  }
  function snapshot(value, label, size, prefix) {
    const data = obj(value), scene = data.scene || value;
    const explanation = str(data.explanation), edits = list(data.edits).length;
    return `<figure class="snapshot submitted-snapshot"><figcaption>${esc(label)}</figcaption><div class="diagram-canvas">${drawScene(scene, dimensions(data.drawing_dimensions, size), {}, prefix)}</div>${explanation ? `<p class="snapshot-explanation"><strong>Submitted explanation:</strong> <span class="preserve">${esc(explanation)}</span></p>` : ''}${edits ? `<p class="muted small">${edits} submitted edit${edits === 1 ? '' : 's'} recorded.</p>` : ''}</figure>`;
  }
  function time(value) {
    if (!str(value)) return '';
    const date = new Date(value); if (Number.isNaN(date.getTime())) return '';
    return date.toISOString().replace('T', ' ').replace(/\.\d{3}Z$/, ' UTC');
  }

  const STYLE = `
:root{--purple:#7250a4;--teal:#237f7c;--ink:#332e43;--muted:#746e82;--line:#e4ddec;--paper:#fff;--wash:#f6f3fa}*{box-sizing:border-box}body{margin:0;background:var(--wash);color:var(--ink);font:18px/1.65 ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}main{max-width:1080px;margin:40px auto;padding:0 32px}h1,h2,h3,p,figure{margin:0}h1{font-size:36px;line-height:1.2;letter-spacing:-.6px;font-weight:720;margin:10px 0 14px}h2{font-size:24px;line-height:1.35;margin-bottom:18px}h3{font-size:18px;color:var(--purple);margin-bottom:8px}.eyebrow{font-size:13px;font-weight:750;letter-spacing:1.8px;text-transform:uppercase;color:var(--purple)}.case-header{padding:30px 0 28px;border-bottom:2px solid var(--purple)}.case-meta{font-size:15px;color:var(--muted)}.section{margin-top:30px;padding:28px 30px;background:var(--paper);border:1px solid var(--line);border-radius:16px}.task-text,.preserve,.message-text{white-space:pre-wrap;overflow-wrap:anywhere}.task-text{margin-bottom:18px}.goal{padding:14px 18px;background:#f0ebf7;border-left:4px solid var(--purple);border-radius:0 9px 9px 0;margin-top:16px}.requirements{margin:14px 0 0;padding-left:24px}.image-figure img{display:block;max-width:100%;max-height:480px;object-fit:contain;margin:auto;border-radius:7px}.image-figure{padding:16px;border:1px solid var(--line);border-radius:10px;margin-top:20px}.image-figure figcaption,.snapshot figcaption{font-size:14px;color:var(--muted);margin:10px 0 0}.snapshot-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}.snapshot{padding:15px;border:1px solid var(--line);border-radius:10px;background:#fff;margin-top:16px;min-width:0}.snapshot figcaption{margin:0 0 10px;font-weight:650;color:var(--purple)}.snapshot-explanation{font-size:16px;margin-top:12px}.snapshot .diagram-svg{max-height:300px}.diagram-canvas{background:#fff;border-radius:7px;overflow:auto}.diagram-svg{display:block;width:100%;height:auto;max-height:620px;min-width:360px}.diagram-scroll-note{display:none;font-size:12px;color:var(--muted);margin-top:7px}.muted{color:var(--muted)}.small{font-size:14px}.explanation{margin-top:18px;padding:14px 18px;background:#f7f5fa;border-radius:9px}.timeline{padding:0;list-style:none;margin:0}.transcript-entry{display:flex;gap:14px;margin:26px 0;align-items:flex-start;break-inside:avoid}.avatar{display:block;width:46px;height:46px;flex:0 0 46px;margin-top:4px}.avatar svg{display:block;width:100%;height:100%}.entry-content{flex:1;min-width:0}.entry-heading{display:flex;gap:12px;align-items:baseline;margin-bottom:6px}.entry-name{font-size:16px;font-weight:720;color:var(--purple)}[data-role=user] .entry-name{color:var(--teal)}[data-role=system] .entry-name{color:#96643e}.entry-number,.entry-time{color:var(--muted);font-size:12px}.entry-time{margin-left:auto}.message-text{padding:17px 20px;background:#f3eff8;border:1px solid #e9e0f2;border-radius:4px 14px 14px 14px;font-size:18px;line-height:1.7}[data-role=user] .message-text{background:#edf7f4;border-color:#d9ebe6}[data-role=system] .message-text{background:#fcf4ed;border-color:#ead5c3}.error-label{font-size:13px;font-weight:650;color:#96643e;margin-top:6px}.revision-reason{margin-top:12px;padding:12px 16px;border-left:3px solid var(--teal);background:#f5faf8;font-size:16px}.revision-reason strong{display:block;color:var(--teal)}details{margin-top:12px}summary{cursor:pointer;display:list-item;width:fit-content;font-size:15px;font-weight:650;color:var(--purple);padding:5px 0}summary:hover{color:#573a83}summary:focus-visible,button:focus-visible{outline:3px solid #bba3db;outline-offset:4px}.reference-content{padding:16px;margin-top:8px;border:1px solid var(--line);border-radius:10px;background:#fff}.reference-caption{font-size:14px;color:var(--muted);margin-bottom:10px}.move-details dl{font-size:14px;margin:6px 0 0;padding:12px 16px;background:#f7f5f9;border-radius:8px}.move-details dl div{display:grid;grid-template-columns:140px 1fr;gap:14px;margin:3px 0}.move-details dt{color:var(--muted)}.move-details dd{margin:0;white-space:pre-wrap;overflow-wrap:anywhere}.path-legend{display:flex;gap:18px;flex-wrap:wrap;font-size:14px}.path-legend span{display:inline-flex;align-items:center;gap:7px}.path-legend i{width:10px;height:10px;border-radius:50%;display:inline-block}.mechanism-caption{margin-top:12px}.mechanism-condition{font-size:15px;margin-bottom:8px}.replay-mechanism{margin-top:10px;border:1px solid #d7c9e7;background:#f5effa;color:var(--purple);border-radius:8px;padding:8px 13px;font:inherit;font-size:14px;font-weight:600;cursor:pointer}.motion-arrow{opacity:0}.motion-arrow.playing{opacity:1}.page-footer{font-size:13px;color:var(--muted);text-align:center;margin:32px 0}.top-actions{float:right}.print-case{border:1px solid var(--line);border-radius:7px;color:var(--purple);background:white;padding:8px 13px;font:inherit;font-size:14px;font-weight:600;cursor:pointer}.note{font-size:14px;color:var(--muted);margin-top:12px}
@media(max-width:700px){main{margin:16px auto;padding:0 16px}h1{font-size:29px}.section{padding:22px 17px}.case-header{padding-top:16px}.snapshot-grid{grid-template-columns:1fr}.transcript-entry{gap:9px}.avatar{width:36px;height:36px;flex-basis:36px}.entry-time{display:none}.message-text{padding:13px 14px}.move-details dl div{grid-template-columns:1fr;gap:0;margin:8px 0}.reference-content{padding:10px}.diagram-svg{min-width:440px}.diagram-scroll-note{display:block}.top-actions{float:none;margin-bottom:10px}}
@media(prefers-reduced-motion:reduce){.motion-arrow{display:none!important}}
@media print{body{background:white;color:#222;font-size:12pt}main{max-width:none;margin:0;padding:0}.case-header{padding:0 0 16px}.section{border:0;border-radius:0;padding:18px 0;margin-top:12px}h1{font-size:26pt}h2{font-size:17pt}.print-case,.replay-mechanism,.top-actions,.diagram-scroll-note{display:none!important}.diagram-svg{min-width:0;max-height:430px}.snapshot-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.transcript-entry{break-inside:auto;page-break-inside:auto;margin:16px 0}.entry-heading,.message-text{break-inside:avoid}.message-text{font-size:12pt;padding:10px 14px}.reference-content,.snapshot{break-inside:avoid;page-break-inside:avoid}.avatar{width:30px;height:30px;flex-basis:30px}summary{font-size:11pt}.motion-arrow{display:none!important}.matching-highlight,.mechanism-track,.static-flow-arrow{-webkit-print-color-adjust:exact;print-color-adjust:exact}.entry-time{display:none}.move-details dl{font-size:10pt}.page-footer{margin:20px 0}@page{margin:16mm}}
`;
  const SCRIPT = `
(function(){'use strict';var reduced=window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches;function stop(container){container.querySelectorAll('animateMotion').forEach(function(m){try{m.endElement();}catch(e){}m.parentElement.classList.remove('playing');});}function play(container){stop(container);if(reduced)return;container.querySelectorAll('animateMotion').forEach(function(m){if(typeof m.beginElement==='function'){m.parentElement.classList.add('playing');try{m.beginElement();}catch(e){m.parentElement.classList.remove('playing');}}});}document.querySelectorAll('.diagram-reference').forEach(function(d){d.addEventListener('toggle',function(){if(d.open)play(d);else stop(d);});});document.querySelectorAll('.replay-mechanism').forEach(function(b){b.addEventListener('click',function(){play(b.closest('.diagram-reference')||b.parentElement);});});var prior=[];window.addEventListener('beforeprint',function(){prior=Array.from(document.querySelectorAll('details')).map(function(d){var old=d.open;d.open=true;stop(d);return[d,old];});});window.addEventListener('afterprint',function(){prior.forEach(function(p){p[0].open=p[1];});prior=[];});document.querySelector('.print-case').addEventListener('click',function(){window.print();});})();
`;

  function build(value) {
    const data = obj(value), title = str(data.title) || 'Draw to Explore case', size = dimensions(data.drawing_dimensions);
    const question = obj(data.question), transcript = list(data.transcript), requirements = (Array.isArray(data.learning_requirements) ? data.learning_requirements : str(data.learning_requirements) ? [data.learning_requirements] : []).map(str).filter(Boolean);
    const original = imageFigure(data.original_image, 'Original student submission');
    const taskImage = imageFigure(question.image, 'Given task figure');
    const submitted = obj(data.committed_work);
    let html = `<!doctype html><html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/><meta name="referrer" content="no-referrer"/><title>${esc(title)}</title><style>${STYLE}</style></head><body><main><header class="case-header"><div class="top-actions"><button type="button" class="print-case">Print / Save PDF</button></div><p class="eyebrow">Draw to Explore · Learning case</p><h1>${esc(title)}</h1><p class="case-meta">Submitted work and feedback dialogue${time(data.exported_at) ? ` · Exported ${esc(time(data.exported_at))}` : ''}</p></header>`;
    html += `<section class="section task-section"><h2>Task and learning context</h2>${str(question.text) ? `<div class="task-text">${esc(question.text)}</div>` : '<p class="muted">The task is provided in the figure below.</p>'}${taskImage}${str(data.learning_goal) ? `<div class="goal"><h3>Learning goal</h3><p class="preserve">${esc(data.learning_goal)}</p></div>` : ''}${requirements.length ? `<h3 style="margin-top:18px">Learning requirements</h3><ul class="requirements">${requirements.map(requirement => `<li>${esc(requirement)}</li>`).join('')}</ul>` : ''}</section>`;
    html += `<section class="section work-section"><h2>Submitted work</h2>${original}${str(data.initial_explanation) ? `<div class="explanation"><h3>Initial written explanation</h3><p class="preserve">${esc(data.initial_explanation)}</p></div>` : ''}<div class="snapshot-grid">${data.original_scene ? snapshot({ scene: data.original_scene }, 'Initial diagram representation', size, 'initial') : ''}${submitted.scene ? snapshot(submitted, 'Latest submitted diagram', size, 'committed') : ''}</div><p class="note">Snapshots contain submitted work. Unsubmitted drafts are not included.</p></section>`;
    html += '<section class="section dialogue-section"><h2>Feedback dialogue</h2><ol class="timeline">';
    transcript.forEach((raw, index) => {
      const entry = obj(raw), system = entry.error === true || entry.role === 'system';
      const role = system ? 'system' : entry.role === 'user' ? 'user' : 'assistant';
      const label = system ? 'System notice' : role === 'user' ? 'Learner' : 'Tutor';
      html += `<li class="transcript-entry" data-role="${role}"${entry.error === true ? ' data-error="true"' : ''}>${avatar(role)}<div class="entry-content"><div class="entry-heading"><span class="entry-name">${label}</span><span class="entry-number">${index + 1}</span>${time(entry.at) ? `<time class="entry-time">${esc(time(entry.at))}</time>` : ''}</div><div class="message-text">${esc(entry.text)}</div>${entry.error === true ? '<p class="error-label">Delivery or system error; this is not tutor feedback.</p>' : ''}${str(entry.revision_reason) ? `<div class="revision-reason"><strong>Learner's revision explanation</strong><span class="preserve">${esc(entry.revision_reason)}</span></div>` : ''}`;
      if (!system) {
        if (entry.submitted_snapshot && obj(entry.submitted_snapshot).scene) html += snapshot(entry.submitted_snapshot, 'Submitted revision snapshot', size, `submission-${index}`);
        const visual = obj(entry.visual);
        if (visual.scene && (list(visual.ids).length || visual.action === 'trace' || visual.action === 'highlight')) {
          const version = Number.isInteger(obj(entry.feedback).drawing_version) ? `Submitted version ${entry.feedback.drawing_version}` : 'Saved diagram for this turn';
          html += `<details class="diagram-reference"><summary>Show diagram reference</summary><div class="reference-content"><p class="reference-caption">${version}${visual.action === 'trace' ? ' · Mechanism demonstration' : ' · Matching visual feedback'}</p><div class="diagram-canvas">${drawScene(visual.scene, dimensions(visual.drawing_dimensions, size), visual, `turn-${index}`)}</div></div></details>`;
        }
        html += metadata(entry);
      }
      html += '</div></li>';
    });
    if (!transcript.length) html += '<li class="muted">No conversation messages were recorded.</li>';
    html += '</ol></section><footer class="page-footer">Draw to Explore · Self-contained case record</footer></main><script>' + SCRIPT + '</script></body></html>';
    return html;
  }
  function filename(value) {
    const data = obj(value);
    const title = (str(data.title) || 'draw-to-explore-case').normalize('NFKD').replace(/[\u0300-\u036f]/g, '').replace(/[^a-z0-9]+/gi, '-').replace(/^-+|-+$/g, '').slice(0, 80).replace(/-+$/, '') || 'draw-to-explore-case';
    const date = /^\d{4}-\d{2}-\d{2}/.exec(str(data.exported_at));
    return `${title}${date ? `-${date[0]}` : ''}.html`;
  }
  const api = { build, filename };
  root.FeedbackCaseExport = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
