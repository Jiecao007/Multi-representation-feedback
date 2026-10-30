import type { Analysis, LabState } from './domain';
import type { DrawingSetup, DrawingRun, ImageSize } from './embedded-physics';
import type { WorkspaceEvent } from './workspace';
import type { FeedbackTrigger } from './talk-moves';
export type ReviewSnapshot = { analysis: Analysis; setup: DrawingSetup; parameters: LabState; dimensions: ImageSize; runs: DrawingRun[]; selectedId: string; version: number; activity: WorkspaceEvent[] };
export function drawingChanged(draft: ReviewSnapshot, committed: ReviewSnapshot | null): boolean {
  const content = (s: ReviewSnapshot) => ({ elements:s.analysis.elements, setup:s.setup, parameters:s.parameters, runs:s.runs });
  return !!committed && JSON.stringify(content(draft)) !== JSON.stringify(content(committed));
}
// Selecting, dragging, typing, and finishing an experiment never commit a draft.
// Even an explicit chat message sees only the last drawing the student submitted.
export function snapshotForFeedback(trigger: FeedbackTrigger, draft: ReviewSnapshot, committed: ReviewSnapshot | null): ReviewSnapshot {
  if (trigger === 'submission' || trigger === 'workspace-complete') return structuredClone(draft);
  if (!committed) throw new Error('Submit a response before starting a conversation.');
  return structuredClone(committed);
}
