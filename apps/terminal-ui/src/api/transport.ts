const configuredBase = import.meta.env.VITE_RESEARCH_API_URL as string | undefined;
export const API_BASE = configuredBase?.replace(/\/$/, "") ?? "";

export class ApiError extends Error {
  readonly status: number | null;
  readonly technicalDetail: string;

  constructor(message: string, status: number | null, technicalDetail = message) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.technicalDetail = technicalDetail;
  }
}

export async function request<T>(
  path: string,
  init?: RequestInit,
  acceptedErrorStatuses: readonly number[] = [],
  timeoutMs = 15_000,
): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    let response: Response;
    try {
      response = await fetch(`${API_BASE}${path}`, {
        ...init,
        signal: controller.signal,
        headers: { "Content-Type": "application/json", ...init?.headers },
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        throw new ApiError("数据请求超时，请重试。", null, error.message);
      }
      throw new ApiError("WorldState 服务不可用，请确认程序已启动。", null, error instanceof Error ? error.message : String(error));
    }
    if (!response.ok && !acceptedErrorStatuses.includes(response.status)) {
      const raw = await response.text();
      let detail = raw;
      try {
        const parsed = JSON.parse(raw) as { detail?: string };
        detail = parsed.detail ?? raw;
      } catch {
        // Preserve the raw response for diagnostics when it is not JSON.
      }
      const userMessage = response.status >= 500
        ? "研究服务返回错误，请打开 Data Sources 查看诊断。"
        : response.status === 404
          ? "当前服务版本没有这项研究内容。"
          : detail || `请求失败（${response.status}）`;
      throw new ApiError(userMessage, response.status, detail || `HTTP ${response.status}`);
    }
    return (await response.json()) as T;
  } finally {
    window.clearTimeout(timeout);
  }
}
