/** Only carry display state, never an arbitrary redirect or identity override. */
export function frameworkTreeQuery(params: URLSearchParams): string {
  const result = new URLSearchParams({ view: 'framework' });
  for (const key of ['environment_id', 'device_id']) {
    const value = params.get(key);
    if (value) result.set(key, value);
  }
  return result.toString();
}
