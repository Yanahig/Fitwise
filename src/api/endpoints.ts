import { request } from './client';
import type {
  AgentMessage,
  AgentNextStep,
  AgentReply,
  CapabilityDoc,
  CaseStudy,
  Customer,
  DashboardData,
  Job,
  Match,
  Material,
  Meta,
  OpenQuestion,
  Project,
  ProjectHighlight,
  Requirement,
  Solution,
  User,
} from './types';

export const api = {
  // 鉴权
  login: (email: string, password: string) =>
    request<{ token: string; user: User }>('/api/auth/login', { body: { email, password } }),
  me: () => request<User>('/api/auth/me'),

  // 元信息 / 工作台
  meta: () => request<Meta>('/api/meta'),
  dashboard: () => request<DashboardData>('/api/dashboard'),

  // 客户：MVP 只用到「建客户」这一步，档案相关接口已随客户档案页下线
  createCustomer: (payload: Partial<Customer>) => request<Customer>('/api/customers', { body: payload }),

  // 项目
  projects: (params?: { customerId?: number; status?: string }) => {
    const search = new URLSearchParams();
    if (params?.customerId) search.set('customer_id', String(params.customerId));
    if (params?.status) search.set('status', params.status);
    const query = search.toString();
    return request<Project[]>(`/api/projects${query ? `?${query}` : ''}`);
  },
  project: (id: number) => request<Project>(`/api/projects/${id}`),
  createProject: (payload: Partial<Project>) => request<Project>('/api/projects', { body: payload }),
  updateHighlights: (id: number, highlights: ProjectHighlight[]) =>
    request<{ highlights: ProjectHighlight[] }>(`/api/projects/${id}/highlights`, {
      method: 'PATCH',
      body: { highlights },
    }),
  /** 改名：AI 从材料识别出的客户/项目名，可以在这里纠正 */
  updateProject: (id: number, payload: { name?: string; owner_name?: string; summary?: string }) =>
    request<Project>(`/api/projects/${id}`, { method: 'PATCH', body: payload }),
  /** 删项目：材料、需求、判断、建议、对话与动态一起删（不可恢复，调用前必须二次确认） */
  deleteProject: (id: number) => request<void>(`/api/projects/${id}`, { method: 'DELETE' }),
  updateCustomer: (id: number, payload: { name?: string; industry?: string; notes?: string }) =>
    request<Customer>(`/api/customers/${id}`, { method: 'PATCH', body: payload }),

  // 材料
  materials: (projectId: number) => request<Material[]>(`/api/projects/${projectId}/materials`),
  /** 对话入口：一次调用决定「用材料回答」还是「提议一个动作」 */
  askAgent: (projectId: number, message: string) =>
    request<AgentReply>(`/api/projects/${projectId}/agent/ask`, { body: { message } }),
  /** 会话历史：刷新之后 Agent 还认得这段对话 */
  agentMessages: (projectId: number, limit = 40) =>
    request<AgentMessage[]>(`/api/projects/${projectId}/agent/messages?limit=${limit}`),
  /** 项目状态与下一步：界面上的「下一步」提示只有这一个来源 */
  agentState: (projectId: number) =>
    request<{ state: Record<string, number>; next_step: AgentNextStep | null }>(
      `/api/projects/${projectId}/agent/state`,
    ),
  /** 工具回执卡：动作开始时落一条 */
  appendAgentMessage: (
    projectId: number,
    payload: {
      role: 'tool' | 'agent';
      kind: 'job' | 'material' | 'text' | 'approval';
      text: string;
      data: Record<string, unknown>;
    },
  ) =>
    request<AgentMessage>(`/api/projects/${projectId}/agent/messages`, {
      method: 'POST',
      body: payload,
    }),
  /** 动作结束时把那张卡更新成结果 */
  patchAgentMessage: (messageId: number, payload: { text?: string; data?: Record<string, unknown> }) =>
    request<AgentMessage>(`/api/agent/messages/${messageId}`, { method: 'PATCH', body: payload }),
  /** 批准留痕：谁、什么时候、批还是拒（由服务端记录） */
  recordApproval: (projectId: number, payload: { message_id: number; decision: 'approved' | 'declined' }) =>
    request<AgentMessage>(`/api/projects/${projectId}/agent/approvals`, { body: payload }),
  uploadMaterial: (projectId: number, file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return request<Material>(`/api/projects/${projectId}/materials`, { formData });
  },
  reparseMaterial: (materialId: number) =>
    request<Material>(`/api/materials/${materialId}/parse`, { method: 'POST' }),
  deleteMaterial: (materialId: number) => request<void>(`/api/materials/${materialId}`, { method: 'DELETE' }),
  materialPreview: (materialId: number, page?: number) =>
    request<{
      material: Material;
      markdown: string;
      chunks: { id: number; page: number; heading: string; text: string }[];
    }>(`/api/materials/${materialId}/preview${page ? `?page=${page}` : ''}`),

  // 需求
  requirements: (projectId: number) =>
    request<{ requirements: Requirement[]; open_questions: OpenQuestion[] }>(
      `/api/projects/${projectId}/requirements`,
    ),
  extractRequirements: (projectId: number) =>
    request<{ job_id: string }>(`/api/projects/${projectId}/requirements/extract`, { method: 'POST' }),
  createRequirement: (projectId: number, payload: Partial<Requirement>) =>
    request<Requirement>(`/api/projects/${projectId}/requirements`, { body: payload }),
  updateRequirement: (id: number, payload: Partial<Requirement> & { status?: string }) =>
    request<Requirement>(`/api/requirements/${id}`, { method: 'PATCH', body: payload }),
  confirmRequirements: (projectId: number, ids?: number[]) =>
    request<{ confirmed: number; job_id?: string }>(`/api/projects/${projectId}/requirements/confirm`, {
      body: { ids },
    }),
  deleteRequirement: (id: number) => request<void>(`/api/requirements/${id}`, { method: 'DELETE' }),

  // 匹配
  runMatching: (projectId: number, requirementIds?: number[]) => {
    const query = requirementIds?.length ? `?${requirementIds.map((id) => `requirement_ids=${id}`).join('&')}` : '';
    return request<{ job_id: string }>(`/api/projects/${projectId}/matches/run${query}`, { method: 'POST' });
  },
  matches: (projectId: number) => request<Match[]>(`/api/projects/${projectId}/matches`),
  match: (matchId: number) => request<Match>(`/api/matches/${matchId}`),
  reviewMatch: (matchId: number, payload: { status: string; note: string; headline?: string }) =>
    request<Match>(`/api/matches/${matchId}/review`, { method: 'PATCH', body: payload }),

  // 方案
  generateSolution: (projectId: number, problem: string) =>
    request<{ job_id: string }>(`/api/projects/${projectId}/solutions/generate`, { body: { problem } }),
  solutions: (projectId: number) => request<Solution[]>(`/api/projects/${projectId}/solutions`),
  // 知识库
  knowledgeDocs: (q?: string) => request<CapabilityDoc[]>(`/api/knowledge/docs${q ? `?q=${encodeURIComponent(q)}` : ''}`),
  knowledgeCases: () => request<CaseStudy[]>('/api/knowledge/cases'),

  // 后台任务
  job: (jobId: string) => request<Job>(`/api/jobs/${jobId}`),
};

/** 轮询后台任务直到完成，并把进度回调给界面。 */
export async function pollJob(
  jobId: string,
  onProgress?: (job: Job) => void,
  intervalMs = 1500,
  timeoutMs = 600_000,
): Promise<Job> {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const job = await api.job(jobId);
    onProgress?.(job);
    if (job.status === 'done' || job.status === 'failed') return job;
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  throw new Error('任务超时，请稍后在项目里查看结果');
}
