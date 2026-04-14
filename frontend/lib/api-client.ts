export type ApiRequestOptions = RequestInit & {
  path: string;
};

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const API_KEY = process.env.NEXT_PUBLIC_API_KEY;

export type RunPipelineInput = {
  accountId: string;
  nicheText: string;
  mock?: boolean;
};

export type PipelineResult = {
  post?: {
    author?: string;
    content?: string;
    likes?: number;
    comments?: number;
  };
  analytics?: {
    viral_score?: number;
  };
  best_comment?: {
    text?: string;
  };
  [key: string]: unknown;
};

export type PipelineStartResponse = {
  status: string;
  execution_id: string;
  mode?: string | null;
};

export type ExecutionStatus = "pending" | "running" | "completed" | "failed";

export type ExecutionStatusResponse = {
  execution_id: string;
  status: ExecutionStatus;
  account_id: string;
  niche_text: string;
  mode: string;
  result_count: number;
  results: PipelineResult[];
  error?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
};

export type ExecutionHistoryItem = {
  execution_id: string;
  status: ExecutionStatus;
  result_count: number;
  started_at?: string | null;
  completed_at?: string | null;
  error?: string | null;
};

export async function apiRequest<T>(options: ApiRequestOptions): Promise<T> {
  try {
    const { path, headers, ...requestOptions } = options;
    const fullUrl = `${API_BASE_URL}${path}`;

    console.log("Calling API:", fullUrl);

    const response = await fetch(fullUrl, {
      ...requestOptions,
      headers: {
        "Content-Type": "application/json",
        ...(API_KEY ? { "X-API-KEY": API_KEY } : {}),
        ...headers,
      },
    });

    if (!response.ok) {
      const responseText = await response.text();
      console.error("API request failed:", {
        status: response.status,
        body: responseText,
      });
      throw new Error(`API request failed with status ${response.status}`);
    }

    const data = (await response.json()) as T;
    console.log("Response received:", data);
    return data;
  } catch (error) {
    console.error("Fetch error:", error);
    throw error;
  }
}

export async function getHealth(): Promise<{ status: string; service: string }> {
  return apiRequest<{ status: string; service: string }>({
    path: "/health",
    method: "GET",
  });
}

export async function runPipeline({
  accountId,
  nicheText,
  mock = true,
}: RunPipelineInput): Promise<PipelineStartResponse> {
  return apiRequest<PipelineStartResponse>({
    path: "/run",
    method: "POST",
    body: JSON.stringify({
      account_id: accountId,
      niche_text: nicheText,
      mock,
    }),
  });
}

export async function getExecutionStatus(
  executionId: string,
): Promise<ExecutionStatusResponse> {
  return apiRequest<ExecutionStatusResponse>({
    path: `/execution/${executionId}`,
    method: "GET",
  });
}

export async function getExecutions(
  accountId: string,
  limit = 20,
): Promise<ExecutionHistoryItem[]> {
  const query = new URLSearchParams({
    account_id: accountId,
    limit: String(limit),
  });

  return apiRequest<ExecutionHistoryItem[]>({
    path: `/executions?${query.toString()}`,
    method: "GET",
  });
}
