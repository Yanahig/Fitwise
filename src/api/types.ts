/** 与后端 API 对应的类型定义（字段名与 server/app/serializers.py 保持一致）。 */

export type MatchStatus = 'full' | 'partial' | 'none' | 'unknown';
export type Priority = 'high' | 'medium' | 'low';
export type RequirementStatus = 'draft' | 'confirmed' | 'dropped';

export interface User {
  id: number;
  email: string;
  name: string;
  role: 'admin' | 'presales' | 'engineer' | 'viewer' | string;
}

export interface Customer {
  id: number;
  name: string;
  industry: string;
  scale: string;
  region: string;
  tier: string;
  owner_name: string;
  source: string;
  health: string;
  notes: string;
  created_at: string;
  updated_at: string;
  projects?: Project[];
  activities?: Activity[];
}

export interface ProjectCounts {
  materials: number;
  materials_parsed: number;
  requirements: number;
  requirements_confirmed: number;
  matches: number;
  matches_full: number;
  matches_partial: number;
  matches_none: number;
  matches_unknown: number;
  has_solution: boolean;
}

export interface Project {
  id: number;
  customer_id: number;
  customer_name: string;
  name: string;
  code: string;
  stage: string;
  status: string;
  owner_name: string;
  summary: string;
  created_at: string;
  updated_at: string;
  counts?: ProjectCounts;
  customer?: Customer;
  materials?: Material[];
  requirements?: Requirement[];
  open_questions?: OpenQuestion[];
  solution?: Solution | null;
  activities?: Activity[];
  matches?: Match[];
  /** 项目要点：从材料里摘出的客观事实，每条带来源页码 */
  highlights?: ProjectHighlight[];
}

export interface ProjectHighlight {
  label: string;
  value: string;
  source_material_name?: string;
  source_page?: number | null;
  /** 人工改过的事实，重新整理时保留 */
  edited?: boolean;
  /** 人工忽略的事实，不再展示 */
  ignored?: boolean;
}

export interface Material {
  id: number;
  project_id: number;
  filename: string;
  file_type: string;
  material_type: string;
  size_bytes: number;
  status: 'uploaded' | 'parsing' | 'parsed' | 'failed';
  parse_engine: string;
  page_count: number;
  parse_error: string;
  /** 这份材料整体写了什么：Agent 抽取时顺带产出一句 */
  summary: string;
  version: number;
  uploaded_by: string;
  created_at: string;
  parsed_at: string | null;
}

export interface RequirementSource {
  material_id: number | null;
  document_name: string;
  page: number | null;
  heading: string;
  excerpt: string;
}

export interface Requirement {
  id: number;
  project_id: number;
  title: string;
  detail: string;
  category: string;
  priority: Priority;
  status: RequirementStatus;
  source: RequirementSource;
  tags: string[];
  constraints: string[];
  created_by_ai: boolean;
  /** 人工改过内容：重新整理需求时这条会被保留，不会被 AI 结果覆盖 */
  edited?: boolean;
  confirmed_by: string;
  confirmed_at: string | null;
  created_at: string;
  match?: { id: number; status: MatchStatus; headline: string };
}

export interface OpenQuestion {
  question: string;
  why?: string;
  owner?: string;
}

export interface Evidence {
  id: number;
  source_type: 'customer' | 'capability' | 'case';
  document_name: string;
  page: number | null;
  heading: string;
  excerpt: string;
}

export interface CapabilitySignal {
  id: number;
  kind: 'support' | 'limit' | 'gap' | 'uncertain';
  text: string;
  page: number;
  heading: string;
  excerpt: string;
  tags: string[];
}

export interface CapabilityDoc {
  id: number;
  product: string;
  title: string;
  doc_type: string;
  version: string;
  owner: string;
  status: string;
  effective_at: string;
  description: string;
  tags: string[];
  supported_scope: string[];
  limitations: string[];
  deployment: string[];
  api_capabilities: string[];
  updated_at: string;
  signals?: CapabilitySignal[];
}

export interface CaseStudy {
  id: number;
  name: string;
  industry: string;
  scale: string;
  duration: string;
  background: string;
  needs: string[];
  products: string[];
  solution: string;
  results: string[];
  lessons: string[];
  tags: string[];
  evidence: { document_name: string; page: number; excerpt: string };
}

/** 一条判断的取证轨迹（检索 → 判断 → 自检 → 决策），由后端写入 */
export interface MatchTraceStep {
  step: string;
  detail: string;
  rule_cap?: string;
  fallback_used?: boolean;
  flagged?: boolean;
  codes?: string[];
  caps?: string[];
}

export interface MatchSelfCheckReason {
  code: string;
  severity: 'block' | 'warn';
  detail: string;
}

/** 自检裁决：guardrail 只标记，降级由后端按上限执行 */
export interface MatchSelfCheck {
  flagged?: boolean;
  reasons?: MatchSelfCheckReason[];
  metrics?: {
    support?: number;
    unique_support?: number;
    constraints?: number;
    cases?: number;
    status?: string;
  };
}

export interface Match {
  id: number;
  project_id: number;
  requirement_id: number;
  requirement: Requirement | null;
  status: MatchStatus;
  headline: string;
  condition: string;
  rationale: string;
  confidence: number;
  judgment_source: 'ai' | 'human';
  reviewed_by: string;
  reviewed_at: string | null;
  review_note: string;
  gaps: string[];
  confirmations: string[];
  capability_doc_ids: number[];
  case_ids: number[];
  trace?: MatchTraceStep[];
  self_check?: MatchSelfCheck;
  created_at: string;
  evidences?: Evidence[];
  capability_docs?: CapabilityDoc[];
  cases?: CaseStudy[];
}

export interface SolutionStep {
  title: string;
  detail: string;
  based_on?: string[];
  status: MatchStatus;
}

/** 一条风险 / 行动依据的那条判断，以及它背后的证据（客户材料 / 能力文档 / 案例） */
export interface MatchBasis {
  requirement_id: number;
  title: string;
  status: MatchStatus;
  headline: string;
  evidences: {
    source_type: 'customer' | 'capability' | 'case' | string;
    document_name: string;
    page: number | null;
    excerpt: string;
  }[];
}

/** 一条对客问题：affects 说它不确认会影响什么，covers 说它覆盖了哪几条需求的待确认项 */
export interface AskCustomerItem {
  question: string;
  affects?: 'judge' | 'promise' | '';
  covers?: number[];
}

/** 一条要同步给销售 / 商务的信息（不是待办）：说给谁听、为什么必须同步 */
export interface SyncSalesItem {
  info: string;
  to: string;
  why?: string;
  urgency: Priority;
}

export interface Solution {
  id: number;
  project_id: number;
  problem: string;
  summary: string;
  version: number;
  status: string;
  steps: SolutionStep[];
  capability_plan: {
    product: string;
    role: string;
    readiness: MatchStatus;
    status_counts?: Record<string, number>;
  }[];
  reference_cases: { case_id: number; name?: string; reason: string; hit_count?: number }[];
  /** 老数据是字符串数组；新数据是带 affects / covers 的对象 */
  ask_customer: (string | AskCustomerItem)[];
  ask_internal: { question: string; owner: string }[];
  sync_sales?: SyncSalesItem[];
  risks: {
    level: 'high' | 'medium' | 'low';
    title: string;
    detail: string;
    mitigation: string;
    /** 这条风险依据哪几条判断（后端按需求标题校验出来的） */
    requirement_ids?: number[];
    basis?: MatchBasis[];
  }[];
  next_actions: {
    action: string;
    owner: string;
    due: string;
    priority: Priority;
    requirement_ids?: number[];
    basis?: MatchBasis[];
  }[];
  generated_at: string;
}

export interface Activity {
  id: number;
  customer_id: number | null;
  project_id: number | null;
  actor: string;
  type: string;
  summary: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface Job {
  id: string;
  kind: string;
  project_id: number | null;
  status: 'running' | 'done' | 'failed';
  total: number;
  done: number;
  current: string;
  message: string;
  error: string;
  result: Record<string, unknown>;
}

export interface Meta {
  stages: { id: string; order: number; name: string; description: string }[];
  knowledge: { docs: number; cases: number };
  match_statuses: Record<string, { label: string; short: string; description: string }>;
  requirement_statuses: Record<string, string>;
  material_types: Record<string, string>;
  integrations: {
    parser: { provider: string; enabled: boolean; formats: string[] };
    llm: {
      provider: string;
      model: string;
      enabled: boolean;
      /** 模型端点域名：材料内容会发送到这里 */
      endpoint_host?: string;
      /** true = 公网模型服务（材料会出内网），false = 本地/内网模型 */
      external?: boolean;
    };
  };
}

export interface DashboardData {
  stats: {
    customers: number;
    projects_active: number;
    matches_pending_review: number;
    knowledge_docs: number;
    knowledge_cases: number;
  };
  projects: Project[];
  activities: Activity[];
  viewer: { name: string; role: string };
}

/** Agent 回答里的一条来源：点一下就能打开原文那一页 */
export interface AgentCitation {
  material_id: number | null;
  document_name: string;
  page: number | null;
  excerpt: string;
}

/** 状态机算出来的「下一步」：能自动跑的给工具，要人做的只说清楚去哪一页 */
export interface AgentNextStep {
  label: string;
  tool: 'run_extraction' | 'run_matching' | 'compose_solution' | null;
  blocked: boolean;
  target: 'materials' | 'requirements' | 'judgement';
}

/**
 * 一次对话的结果。kind=action 时只是「提议做某件事」，
 * 由前端调用既有端点执行 —— 后端这一层不改数据。
 */
export interface AgentReply {
  kind: 'answer' | 'action' | 'plan' | 'approval';
  text: string;
  citations: AgentCitation[];
  tool: 'run_full_analysis' | 'run_extraction' | 'run_matching' | 'compose_solution' | null;
  tool_label: string | null;
  problem: string | null;
  /** kind=plan 时要按顺序跑的工具 */
  steps?: string[];
  /** 计划停在哪一步（通常是需要人确认的环节） */
  gate?: AgentNextStep | null;
  next_step?: AgentNextStep | null;
  /** 落库后的消息 id（回答那条） */
  message_id?: number;
  /** kind=approval：需要人点头的动作，Agent 只准备不执行 */
  approval?: {
    tool: string;
    label: string;
    detail: string;
    payload: { ids?: number[] };
  };
}

/**
 * 会话历史里的一条消息。
 * role=tool 的工具回执卡只带 material_id / job_id，状态仍从材料与任务实时读。
 */
export interface AgentMessage {
  id: number;
  project_id: number;
  role: 'user' | 'agent' | 'tool';
  kind: 'text' | 'material' | 'job' | 'approval';
  text: string;
  data: Record<string, unknown>;
  created_at: string | null;
}
