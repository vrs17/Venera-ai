/**
 * QueueStore'ning xotiradagi nusxasi - testlar va SQLite ochilmay qolgan
 * holat uchun. Shartnoma SQLite bilan bir xil (`__tests__/queueStore.test.ts`).
 */
import type { QueueRow, QueueStore } from './queueStore';

export function createMemoryQueueStore(initial: QueueRow[] = []): QueueStore & { rows: Map<string, QueueRow> } {
  const rows = new Map<string, QueueRow>(initial.map((r) => [r.clientId, { ...r, marks: [...r.marks] }]));
  const listeners = new Set<() => void>();
  const notify = () => listeners.forEach((l) => l());
  const copy = (r: QueueRow): QueueRow => ({ ...r, marks: r.marks.map((m) => ({ ...m })) });

  return {
    rows,
    async insert(row) {
      rows.set(row.clientId, copy(row));
      notify();
    },
    async get(clientId) {
      const r = rows.get(clientId);
      return r ? copy(r) : null;
    },
    async update(clientId, patch) {
      const cur = rows.get(clientId);
      if (!cur) return null;
      const next = copy({ ...cur, ...patch, clientId });
      rows.set(clientId, next);
      notify();
      return copy(next);
    },
    async list() {
      return [...rows.values()].sort((a, b) => a.startedAt.localeCompare(b.startedAt)).map(copy);
    },
    async remove(clientId) {
      rows.delete(clientId);
      notify();
    },
    async clear() {
      rows.clear();
      notify();
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}
