import { normalizeAnalysis, type Analysis } from './domain.ts';

export const CRITERIA = {
  machines: 'Identify three simple machines',
  forces: 'Label forces on one simple machine',
  newton: 'Explain with Newton’s laws',
} as const;
export type Criterion = keyof typeof CRITERIA;
export type CriterionReview = {criterion:Criterion; status:'established'|'developing'|'not-yet-visible'; strength:string; gap:string};
export function normalizeReview(raw:unknown):CriterionReview[] {
  if(!Array.isArray(raw))return [];
  const result:CriterionReview[]=[];
  for(const criterion of Object.keys(CRITERIA) as Criterion[]){
    const row=raw.find(r=>r&&r.criterion===criterion);
    if(!row||!['established','developing','not-yet-visible'].includes(row.status))return [];
    const brief=(text:unknown)=>typeof text==='string'?text.trim().split(/\s+/).slice(0,14).join(' ').slice(0,180):'';
    result.push({criterion,status:row.status,strength:brief(row.strength),gap:brief(row.gap)});
  }
  return result;
}
// One current overview, while per-turn snapshots remain in the exported history.
// A pending, failed, or legacy turn without a complete review cannot erase it.
export function latestReview(messages: readonly { role?: unknown; review?: unknown }[]): CriterionReview[] {
  for (let i=messages.length-1;i>=0;i--) {
    if(messages[i]?.role!=='assistant')continue;
    const review=normalizeReview(messages[i].review);
    if(review.length===3)return review;
  }
  return [];
}
export type ImageRole = 'task-diagram' | 'student-response' | 'none';
export type Submission = { imageRole: ImageRole; analysis: Analysis };
export type NextStep = { kind: 'identify' | 'annotate' | 'explain' | 'experiment' | 'revise' | 'clarify'; instruction: string };
export type FeedbackGuide = { criterion: Criterion; evidenceQuote: string; evidenceSource: 'original' | 'revision'; nextStep: NextStep };
export const EMPTY_ANALYSIS: Analysis = { summary: 'No image provided.', elements: [], uncertainties: [] };

// Initial evidence remains separate from the editable workspace throughout the session.
export function normalizeSubmission(raw: unknown, original: string): Submission {
  const s = raw && typeof raw === 'object' ? raw as Record<string, unknown> : {};
  const imageRole: ImageRole = s.imageRole === 'student-response' || s.imageRole === 'task-diagram' ? s.imageRole : 'none';
  if (!original.trim() && imageRole !== 'student-response') throw new Error('Add the student’s written response or a student response image before requesting feedback. A task diagram alone is not a student response.');
  const analysis = s.analysis ? normalizeAnalysis(s.analysis) : structuredClone(EMPTY_ANALYSIS);
  // Printed or handwritten material in the task image is never a student transcript.
  if (imageRole !== 'student-response') analysis.transcription = '';
  return { imageRole, analysis };
}

export function normalizeGuide(raw: Record<string, unknown>, original: string, revision: string, hasDrawing: boolean): FeedbackGuide {
  const criterion: Criterion = Object.hasOwn(CRITERIA, String(raw.criterion)) ? raw.criterion as Criterion : 'newton';
  const evidenceSource = raw.evidenceSource === 'revision' ? 'revision' : 'original';
  const source = evidenceSource === 'revision' ? revision : original;
  const quote = typeof raw.evidenceQuote === 'string' ? raw.evidenceQuote.trim().split(/\s+/).slice(0,12).join(' ') : '';
  const step = raw.nextStep && typeof raw.nextStep === 'object' ? raw.nextStep as Record<string, unknown> : {};
  const kinds = ['identify','annotate','explain','experiment','revise','clarify'];
  let kind = kinds.includes(String(step.kind)) ? step.kind as NextStep['kind'] : 'explain';
  let instruction = typeof step.instruction === 'string' ? step.instruction.slice(0,300) : 'Explain your thinking in the conversation.';
  if (!hasDrawing && ['identify','annotate','experiment'].includes(kind)) {
    kind = 'explain'; instruction = 'Describe your idea in the conversation using the task and your response.';
  }
  return { criterion, evidenceSource, evidenceQuote: quote && source.includes(quote) ? quote : '', nextStep: { kind, instruction } };
}
