/**
 * Typed client for the grievance backend.
 *
 * Every policy flag shown in the UI comes from these payloads, which the
 * backend reads from the category master at request time. The frontend never
 * decides whether a case is sensitive, and never holds a list of categories.
 */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

/** AI output arrives pre-wrapped by the backend so it cannot render unlabelled. */
export type AiLabelled<T> = {
  kind: string;
  value: T;
  label: string;
  verified: boolean;
  model: string;
};

export type Sentiment = {
  sentiment: "ANGRY" | "DISTRESSED" | "NEUTRAL" | "APPRECIATIVE";
  confidence: number;
  key_points: string[];
};

export type CasePolicy = {
  sensitive: boolean;
  identity_hiding: boolean;
  auto_resolution_allowed: boolean;
  policy_note: string;
  default_priority: string;
};

export type CaseGate = {
  outcome: "AUTO_RESOLVE" | "HUMAN_QUEUE";
  rule_applied: string;
  reason: string;
  confidence: number;
  confidence_threshold: number;
  model: string;
  trace_url: string | null;
};

export type SlaAlert = {
  risk: string;
  reason: string;
  predicted_days: number | null;
  historical_p80_days: number | null;
  sample_size: number;
  acknowledged_by: string | null;
};

export type QueueRow = {
  reference_no: string;
  complaint_text: string;
  complaint_language: string;
  category_id: string;
  category: string | null;
  subcategory: string | null;
  department_id: string | null;
  assignee: string | null;
  status: string;
  priority: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  priority_score: number | null;
  taluka: string | null;
  locality: string | null;
  citizen_name: string | null;
  citizen_phone: string | null;
  identity_masked: boolean;
  sla_days: number;
  sla_due_at: string | null;
  hours_remaining: number | null;
  overdue: boolean;
  reopened_count: number;
  created_at: string | null;
  ai_summary: AiLabelled<string> | null;
  ai_sentiment: AiLabelled<Sentiment> | null;
  policy: CasePolicy;
  gate: CaseGate | null;
  incident_id: number | null;
  incident: {
    incident_ref: string;
    similarity: number | null;
    confirmed_by: string | null;
    member_count: number;
  } | null;
  sla_alerts: SlaAlert[];
};

export type Incident = {
  id: number;
  incident_ref: string;
  category_id: string;
  taluka: string | null;
  locality: string | null;
  window_start: string;
  window_end: string;
  similarity: number | null;
  confirmed_by: string | null;
  member_count: number;
  members: {
    reference_no: string;
    status: string;
    priority: string;
    sla_due_at: string | null;
  }[];
  note: string;
};

export type SlaForecast = {
  reference_no: string;
  risk: string;
  hours_remaining: number;
  due_at: string;
  sla_days: number;
  recurrence_count: number;
  reason: string;
  stats: {
    basis: string;
    sample_size: number;
    p50_days: number | null;
    p80_days: number | null;
    breach_rate: number | null;
    sla_days: number;
    usable: boolean;
    min_samples: number;
  };
};

export type Queue = {
  generated_at: string;
  count: number;
  counts: { awaiting_review: number; sensitive: number; overdue: number };
  rows: QueueRow[];
};

export type Explanation = {
  reference_no: string;
  status: string;
  policy: {
    category_id: string;
    sensitive: boolean;
    identity_hiding: boolean;
    auto_resolution_allowed: boolean;
    sla_days: number;
    policy_note: string;
  };
  decision: {
    gate_outcome: string;
    policy_rule_applied: string;
    policy_reason: string;
    confidence: number;
    confidence_threshold: number;
    model: string;
    trace_url: string | null;
    rationale: AiLabelled<string>;
  } | null;
  retrieved_cases: {
    grievance_id: string;
    complaint_text: string | null;
    status: string | null;
    resolution_days: number | null;
    citizen_feedback: string | null;
  }[];
  evidence_note: string;
};

export type AuditEntry = {
  id: number;
  actor: string;
  actor_id: string | null;
  model: string | null;
  confidence: number | null;
  timestamp: string;
  action: string;
  target: string;
  reasoning: string;
  rule_applied: string | null;
};

export type IntakeTurn = {
  role: "citizen" | "system";
  text: string;
  source?: string;
  language?: string;
  at: string;
};

export type IntakeReply = {
  session_key: string;
  language: string;
  reply: string;
  draft: Record<string, unknown>;
  missing_details: string[];
  ready_to_confirm: boolean;
  confidence: number | null;
  model: string;
  transcript: IntakeTurn[];
  translation_available: boolean;
};

export type TrackedCase = {
  reference_no: string;
  status: string;
  priority: string;
  category_id: string;
  department_id: string | null;
  sla_due_at: string | null;
  reopened_count: number;
  ai_summary: AiLabelled<string> | null;
  decision: { outcome: string; policy_reason: string } | null;
  awaiting_feedback: boolean;
  timeline: { at: string; by: string; action: string; detail: string }[];
};

export type IntakeCapabilities = {
  languages: { code: string; name: string }[];
  voice_available: boolean;
  translation_available: boolean;
  stt_model: string | null;
  /** Spoken replies for the simulated phone call. */
  tts_available?: boolean;
  speech_provider?: "sarvam" | "openai" | null;
};

/** Where a citizen turn came from. "whatsapp" and "call" are simulated. */
export type IntakeSource = "text" | "voice" | "whatsapp" | "call";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly rule?: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    cache: "no-store",
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });

  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    let rule: string | undefined;
    try {
      const body = await response.json();
      const detail = body?.detail;
      if (typeof detail === "string") message = detail;
      else if (detail?.error) {
        message = detail.error;
        rule = detail.rule;
      }
    } catch {
      /* keep the status-line message */
    }
    throw new ApiError(message, response.status, rule);
  }
  return response.json() as Promise<T>;
}

export const api = {
  queue: (params: Record<string, string | undefined> = {}) => {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value) query.set(key, value);
    }
    const suffix = query.toString() ? `?${query}` : "";
    return request<Queue>(`/api/officer/queue${suffix}`);
  },

  case: (reference: string) =>
    request<QueueRow>(`/api/officer/grievances/${reference}`),

  explain: (reference: string) =>
    request<Explanation>(`/api/grievances/${reference}/explain`),

  capabilities: () => request<IntakeCapabilities>(`/api/intake/languages`),

  sendMessage: (body: {
    text: string;
    language: string;
    session_key?: string;
    source?: IntakeSource;
  }) =>
    request<IntakeReply>(`/api/intake/message`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  confirmDraft: (
    sessionKey: string,
    body: { citizen_name?: string; citizen_phone?: string },
  ) =>
    request<{ reference_no: string | null; filed: boolean; gate: CaseGate }>(
      `/api/intake/${sessionKey}/confirm`,
      { method: "POST", body: JSON.stringify(body) },
    ),

  transcribe: async (blob: Blob, language: string) => {
    const form = new FormData();
    form.append("audio", blob, "speech.webm");
    form.append("language", language);
    const response = await fetch(`${API_BASE}/api/intake/transcribe`, {
      method: "POST",
      body: form,
    });
    if (!response.ok) {
      let message = `${response.status}`;
      try {
        const body = await response.json();
        if (typeof body?.detail === "string") message = body.detail;
      } catch {
        /* keep the status */
      }
      throw new ApiError(message, response.status);
    }
    return (await response.json()) as { text: string; model: string };
  },

  /**
   * Speak a reply aloud (simulated phone call). Returns WAV audio, or throws
   * ApiError(503) when no speech provider is configured - the caller then
   * shows the reply as a caption instead.
   */
  speak: async (text: string, language: string): Promise<Blob> => {
    const response = await fetch(`${API_BASE}/api/intake/speak`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, language }),
    });
    if (!response.ok) {
      throw new ApiError(`speech ${response.status}`, response.status);
    }
    return response.blob();
  },

  track: (reference: string) => request<TrackedCase>(`/api/track/${reference}`),

  feedback: (reference: string, body: { satisfied: boolean; note: string }) =>
    request<{ status: string; reopened: boolean; reopened_count?: number }>(
      `/api/track/${reference}/feedback`,
      { method: "POST", body: JSON.stringify(body) },
    ),

  incidents: () => request<Incident[]>(`/api/incidents`),

  groupDuplicates: () =>
    request<{ incidents: unknown[] }>(`/api/incidents/group`, { method: "POST" }),

  confirmIncident: (id: number, body: { officer_id: string; note: string }) =>
    request<{ incident_ref: string }>(`/api/incidents/${id}/confirm`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  forecast: (reference: string) =>
    request<SlaForecast>(`/api/sla/forecast/${reference}`),

  audit: (reference: string) =>
    request<AuditEntry[]>(`/api/audit-logs?target=${reference}`),

  approve: (reference: string, body: { officer_id: string; note: string; status?: string }) =>
    request<QueueRow>(`/api/officer/grievances/${reference}/approve`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  override: (
    reference: string,
    body: {
      officer_id: string;
      note: string;
      status?: string;
      department_id?: string;
      assignee?: string;
      priority?: string;
    },
  ) =>
    request<QueueRow>(`/api/officer/grievances/${reference}/override`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
};

/** Human-readable rule names. The raw constant is always shown alongside. */
export const RULE_LABELS: Record<string, string> = {
  RULE_1_SENSITIVE_NEVER_AUTO_CLOSED: "Sensitive — human review required",
  RULE_2_AI_NEVER_REJECTS_OR_RULES_ON_LIABILITY: "Automated rejection refused",
  RULE_5_DECISION_BELOW_CONFIDENCE_THRESHOLD: "Below confidence threshold",
  CATEGORY_AUTO_RESOLUTION_NOT_ALLOWED: "Category forbids automated resolution",
  CATEGORY_AUTO_RESOLUTION_ALLOWED_AND_CONFIDENT: "Automation permitted",
  CATEGORY_UNDETERMINED_REQUIRES_HUMAN_REVIEW: "Category undetermined",
  CATEGORY_NOT_IN_MASTER_REQUIRES_HUMAN_REVIEW: "Category not in master",
};

export function ruleLabel(rule: string | undefined | null): string {
  if (!rule) return "No decision recorded";
  return RULE_LABELS[rule] ?? rule.replaceAll("_", " ").toLowerCase();
}

export function formatHours(hours: number | null): string {
  if (hours === null) return "—";
  const abs = Math.abs(hours);
  const text =
    abs < 24 ? `${abs.toFixed(0)}h` : `${(abs / 24).toFixed(abs < 72 ? 1 : 0)}d`;
  return hours < 0 ? `${text} over` : text;
}
