/** Never substitute another record when a link names an inaccessible one. */
export function selectVisibleRecord<T extends { id: string }>(records: readonly T[], requestedId?: string): T | null {
  return (requestedId ? records.find((record) => record.id === requestedId) : records[0]) ?? null;
}
