/** Decode API failures even when a server or proxy returns plain text. */
export async function readApiResponse<T = any>(response: Response): Promise<T> {
  const text = await response.text();
  let data: any;
  try { data = text ? JSON.parse(text) : null; } catch { /* Report HTTP failures below. */ }
  if (!response.ok) {
    const detail = data?.detail;
    const message = typeof detail === "string" ? detail : detail?.message;
    throw new Error(message || (detail ? JSON.stringify(detail) :
      `The server could not complete this request (HTTP ${response.status}). Check that the library drive is connected, then retry.`));
  }
  if (data === undefined) throw new Error("The server returned an unreadable response. Retry after checking the service.");
  return data as T;
}
