import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../api/endpoints';
import type {
  AgentCitation,
  AgentMessage,
  AgentNextStep,
  Job,
  Material,
  Match,
  Project,
} from '../../api/types';
import { MODULE_LABELS } from './ProjectContextBar';
import type { ModuleKey } from './ProjectContextBar';
import { FileDropOverlay, useFileDrop } from '../FileDrop';
import {
  MATERIAL_TYPE_LABEL,
  isMaterialPending,
  isSupportedFile,
  materialType,
} from '../../domain/materials';
import { useToast } from '../Toast';
import { HelpTip } from '../HelpTip';
import {
  IconAlert,
  IconArrowRight,
  IconCheck,
  IconClose,
  IconEvidence,
  IconRefresh,
  IconSpark,
} from '../icons';

interface ChatMessage {
  /** key 用字符串：本地新消息与落库消息不会撞号 */
  id: string;
  /**
   * material：材料回执卡。它只存 material id，状态从 project.materials 实时读，
   * 这样卡片和材料行永远说的是同一件事，不会出现两套进度。
   */
  role: 'user' | 'agent' | 'material';
  text: string;
  materialId?: number;
  /** 上传没成功：这张卡没有 material id，只留文件名与原因 */
  uploadError?: string;
  /** 上传失败时留着原文件，点「重试」不用让用户重新选一遍 */
  file?: File;
  /** 工具回执卡：Agent 提议并执行的动作（材料卡是它的另一个 kind） */
  tool?: {
    name: string;
    label: string;
    status: 'running' | 'done' | 'failed';
    summary?: string;
    jobId?: string;
    /** 落库那条消息的 id：动作结束时要更新它 */
    messageId?: number;
  };
  /** 待批准的动作（L2）：确认需求这类事必须人点头 */
  approval?: {
    messageId?: number;
    tool: string;
    label: string;
    detail: string;
    ids?: number[];
    decision?: 'approved' | 'declined';
    by?: string;
    at?: string;
  };
  /** Agent 回答引用的来源，可点击跳到对应页面 */
  refs?: { label: string; href?: string; materialId?: number | null; page?: number | null }[];
}

function citationRefs(citations: AgentCitation[]): ChatMessage['refs'] {
  return citations.map((item) => ({
    label: item.page ? `${item.document_name} · 第 ${item.page} 页` : item.document_name,
    materialId: item.material_id,
    page: item.page,
  }));
}

/** 工具名 → 人话。界面上的动作卡与计划都读这一份。 */
const TOOL_LABELS: Record<string, string> = {
  run_full_analysis: '重新跑一遍分析',
  run_extraction: '整理需求',
  run_matching: '能力判断',
  compose_solution: '生成售前建议',
};

/** 落库消息 → 界面消息。读不出来的（比如材料已删）就丢掉，不硬渲染。 */
function toChatMessage(item: AgentMessage): ChatMessage | null {
  const data = item.data ?? {};
  if (item.role === 'tool' && item.kind === 'material') {
    const materialId = Number(data.material_id);
    return materialId > 0
      ? { id: `srv-${item.id}`, role: 'material', text: item.text, materialId }
      : null;
  }
  if (item.role === 'tool' && item.kind === 'approval') {
    const approval = (data.approval ?? {}) as Record<string, unknown>;
    const decision = String(approval.decision ?? '');
    const payload = (approval.payload ?? {}) as Record<string, unknown>;
    return {
      id: `srv-${item.id}`,
      role: 'agent',
      text: item.text,
      approval: {
        messageId: item.id,
        tool: String(approval.tool ?? 'confirm_requirements'),
        label: String(approval.label ?? '待批准'),
        detail: String(approval.detail ?? ''),
        ids: Array.isArray(payload.ids) ? (payload.ids as number[]) : undefined,
        decision: decision === 'approved' || decision === 'declined' ? decision : undefined,
        by: typeof approval.by === 'string' ? approval.by : undefined,
        at: typeof approval.at === 'string' ? approval.at : undefined,
      },
    };
  }
  if (item.role === 'tool') {
    const status = String(data.status ?? 'done');
    return {
      id: `srv-${item.id}`,
      role: 'agent',
      text: item.text,
      tool: {
        name: String(data.tool ?? ''),
        label: String(data.label ?? item.text ?? '动作'),
        status: status === 'running' || status === 'failed' ? status : 'done',
        summary: typeof data.summary === 'string' ? data.summary : undefined,
        jobId: typeof data.job_id === 'string' ? data.job_id : undefined,
        messageId: item.id,
      },
    };
  }
  if (item.role === 'user') return { id: `srv-${item.id}`, role: 'user', text: item.text };
  // 动作与待批准都由卡片代表（卡片里有同样的话），不再单独渲染一条气泡，
  // 否则刷新之后会出现"气泡 + 卡片"两份同样的话
  if (data.tool || data.approval) return null;
  const citations = Array.isArray(data.citations) ? (data.citations as AgentCitation[]) : [];
  return { id: `srv-${item.id}`, role: 'agent', text: item.text, refs: citationRefs(citations) };
}

/** 工具回执卡：动作只有"在跑 / 跑完 / 没跑完"三种状态 */
function ToolCard({ tool, projectId }: { tool: NonNullable<ChatMessage['tool']>; projectId: number }) {
  const tone = tool.status === 'done' ? 'ok' : tool.status === 'failed' ? 'bad' : 'wait';
  const fallback = tool.status === 'running' ? '正在跑…' : tool.status === 'failed' ? '没跑完' : '已完成';
  return (
    <div className={`agent-card agent-card--${tone}`}>
      <div className="agent-card__head">
        <span className="agent-card__dot" aria-hidden="true" />
        <span className="asset-tag asset-tag--customer">动作</span>
        <strong className="agent-card__name">{tool.label}</strong>
      </div>
      <p className="agent-card__state">{tool.summary ?? fallback}</p>
      {tool.status === 'running' ? <span className="agent-card__bar" aria-hidden="true" /> : null}
      {tool.status === 'done' ? (
        <div className="agent-card__actions">
          <button
            type="button"
            className="link-btn"
            onClick={() => {
              window.location.hash = `/projects/${projectId}/judgement`;
            }}
          >
            <IconArrowRight width={12} height={12} />
            去页面看结果
          </button>
        </div>
      ) : null}
    </div>
  );
}

/**
 * 待批准卡：AI 把要做的准备好，人点一下才执行。
 * 产品的分工就落在这一张卡上 —— 确认需求、对外承诺这类事，模型只能提议。
 */
function ApprovalCard({
  approval,
  busy,
  onDecide,
}: {
  approval: NonNullable<ChatMessage['approval']>;
  busy: boolean;
  onDecide: (approved: boolean) => void;
}) {
  const tone = approval.decision === 'declined' ? 'bad' : approval.decision ? 'ok' : 'wait';
  return (
    <div className={`agent-card agent-card--${tone}`}>
      <div className="agent-card__head">
        <span className="agent-card__dot" aria-hidden="true" />
        <span className="asset-tag asset-tag--customer">待批准</span>
        <strong className="agent-card__name">{approval.label}</strong>
      </div>
      <p className="agent-card__state">{approval.detail}</p>
      {approval.decision ? (
        <p className="hint">
          {approval.decision === 'approved' ? '已批准' : '已放弃'}
          {approval.by ? ` · ${approval.by}` : ''}
        </p>
      ) : (
        <div className="agent-card__actions">
          <button type="button" className="btn btn--primary btn--sm" onClick={() => onDecide(true)} disabled={busy}>
            批准并执行
          </button>
          <button type="button" className="link-btn" onClick={() => onDecide(false)} disabled={busy}>
            先不做
          </button>
        </div>
      )}
    </div>
  );
}

/** 对话里的材料回执：只讲这一份材料现在什么状态，不放原文与清单 */
function MaterialCard({
  material,
  factCount,
  requirementCount,
  draftCount,
  onOpenSource,
  onRetry,
  onWithdraw,
  onOpenRequirements,
}: {
  material: Material;
  factCount: number;
  requirementCount: number;
  draftCount: number;
  onOpenSource: () => void;
  onRetry: () => void;
  onWithdraw: () => void;
  onOpenRequirements: () => void;
}) {
  const pending = isMaterialPending(material.status);
  const tone = material.status === 'parsed' ? 'ok' : material.status === 'failed' ? 'bad' : 'wait';
  // 卡片上只留「读得怎么样」；要点数与需求候选数收进 title，避免每张卡都堆四行数字
  const detail = [
    material.page_count ? `${material.page_count} 页` : '',
    factCount ? `${factCount} 条项目要点` : '',
    requirementCount ? `${requirementCount} 条需求候选` : '',
  ]
    .filter(Boolean)
    .join(' · ');
  // 「排队中」和「正在读」是两件事：一次拖 5 份时，用户要能看出哪些还没轮到
  const state =
    material.status === 'uploaded'
      ? '已收到 · 排队中'
      : material.status === 'parsing'
        ? '正在读取…'
        : [material.page_count ? `${material.page_count} 页` : '', '已读完'].filter(Boolean).join(' · ');

  return (
    <div className={`agent-card agent-card--${tone}`}>
      <div className="agent-card__head">
        <span className="agent-card__dot" aria-hidden="true" />
        <span className="asset-tag asset-tag--customer">
          {MATERIAL_TYPE_LABEL[materialType(material)] ?? '其他材料'}
        </span>
        <strong className="agent-card__name">{material.filename}</strong>
      </div>

      <p className="agent-card__state" title={detail}>
        {state}
      </p>

      {material.status === 'failed' && material.parse_error ? (
        <p className="hint">{material.parse_error.slice(0, 60)}</p>
      ) : null}

      {pending ? <span className="agent-card__bar" aria-hidden="true" /> : null}

      <div className="agent-card__actions">
        {material.status === 'parsed' ? (
          <button type="button" className="link-btn" onClick={onOpenSource}>
            <IconEvidence width={12} height={12} />
            查看原文
          </button>
        ) : null}

        {material.status === 'parsed' && draftCount ? (
          <button type="button" className="link-btn" onClick={onOpenRequirements}>
            <IconArrowRight width={12} height={12} />
            去确认这 {draftCount} 条
          </button>
        ) : null}

        {material.status === 'failed' ? (
          <button type="button" className="link-btn" onClick={onRetry}>
            <IconRefresh width={12} height={12} />
            重新读取
          </button>
        ) : null}

        {pending ? (
          <button type="button" className="link-btn" onClick={onWithdraw}>
            <IconClose width={12} height={12} />
            撤回
          </button>
        ) : null}
      </div>
    </div>
  );
}

/**
 * Fitwise Agent：上半部分主动汇报判断，下半部分是对话区。
 *
 * 对话走后端单步路由（/agent/ask）：一次调用决定「用材料回答」还是「提议一个动作」。
 * 回答里的页码引用由后端从检索命中生成；动作由本组件调用既有端点执行 —— 权限与留痕只有一条路径。
 */
export function AgentPanel({
  project,
  matches,
  module = 'judgement',
  busy,
  onRunAnalysis,
  runTask,
  refresh,
}: {
  project: Project;
  matches: Match[];
  module?: ModuleKey;
  busy: boolean;
  onRunAnalysis: () => Promise<Job | null>;
  runTask: (starter: () => Promise<{ job_id: string }>, label: string) => Promise<Job | null>;
  refresh: () => Promise<void>;
}) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState('');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [pasting, setPasting] = useState(false);
  const [thinking, setThinking] = useState(false);
  /** 状态机给的下一步：能自动跑的就显示成可点的提示 */
  const [nextStep, setNextStep] = useState<AgentNextStep | null>(null);
  /** 正在读的材料 id：面板级一个轮询，不按卡片各拉一遍 */
  const [watching, setWatching] = useState<number[]>([]);
  const nextId = useRef(1);
  const alive = useRef(true);
  const messagesRef = useRef<HTMLDivElement>(null);
  const newId = () => `local-${nextId.current++}`;

  /** StrictMode 下 effect 会先卸载再挂载，所以这里必须显式恢复存活标记 */
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const solution = project.solution;
  const gaps = matches.filter((item) => item.status === 'none');
  const unknown = matches.filter((item) => item.status === 'unknown');
  const partial = matches.filter((item) => item.status === 'partial');
  const riskCount = gaps.length + unknown.length;

  /**
   * 结论按"项目走到哪一步"说，不能一口咬定还没读过材料 ——
   * 这段现在是常驻结论，说错了整块面板都不可信。
   */
  const materials = project.materials ?? [];
  const requirements = project.requirements ?? [];
  const confirmedRequirements = requirements.filter((item) => item.status === 'confirmed');
  const verdict = !materials.length
    ? '还不了解这个项目'
    : !confirmedRequirements.length
      ? '需求还没确认，判断先不下'
      : !matches.length
        ? '需求基线已定，还没做能力判断'
        : gaps.length
          ? '这个项目暂不建议直接承诺'
          : unknown.length
            ? '可以先推进，但需要先补齐信息'
            : '这个项目建议重点推进';

  const reasons = !materials.length
    ? ['还没有客户材料', '拖一份材料进来我就能开始读']
    : !confirmedRequirements.length
      ? [`${requirements.length} 条需求等着确认`, '确认之后才进入能力判断']
      : !matches.length
        ? [`已确认 ${confirmedRequirements.length} 条需求`, '还没做能力判断']
        : [
            gaps.length ? `${gaps.length} 项核心需求存在能力缺口` : '核心需求均有能力覆盖',
            unknown.length ? `${unknown.length} 项待补依据，需向客户确认` : '',
            partial.length ? `${partial.length} 项需要补齐前提条件` : '',
          ].filter(Boolean);

  const openSource = (materialId: number, page = 1) => {
    window.dispatchEvent(new CustomEvent('fitwise:open-assets', { detail: { materialId, page } }));
  };

  /** 材料卡上的两条数字：这一份材料自己贡献了几个要点、几条需求 */
  const factCountOf = (material: Material) =>
    (project.highlights ?? []).filter(
      (item) => !item.ignored && item.source_material_name === material.filename,
    ).length;
  const requirementCountOf = (material: Material) =>
    (project.requirements ?? []).filter((item) => item.source.material_id === material.id).length;
  const draftCountOf = (material: Material) =>
    (project.requirements ?? []).filter(
      (item) => item.source.material_id === material.id && item.status === 'draft',
    ).length;

  /**
   * 材料读完是几十秒的事，读完之后后端还会接着抽需求。
   *
   * 这里是**面板级**的一个轮询：一次 api.materials + 一次 refresh 服务所有卡片。
   * 按卡片各轮一遍的话，拖 5 份文件就是每 2 秒 15 个请求、5 次 setState。
   * 状态变化时回到 2 秒，没变化就慢慢退到 5 秒；页面切到后台就停手。
   */
  useEffect(() => {
    if (watching.length === 0) return;
    let cancelled = false;
    let running = false;
    let timer = 0;
    let delay = 2000;
    const settleUntil: Record<number, number> = {};
    const seen: Record<number, string> = {};
    const startedAt = Date.now();

    const schedule = (next: number) => {
      if (cancelled) return;
      timer = window.setTimeout(() => void step(), next);
    };

    const step = async () => {
      if (cancelled || running) return;
      running = true;
      try {
        if (document.visibilityState === 'hidden') {
          schedule(5000);
          return;
        }
        let list: Material[] = [];
        try {
          list = await api.materials(project.id);
        } catch {
          schedule(5000);
          return;
        }
        if (cancelled) return;
        await refresh();
        if (cancelled || !alive.current) return;

        const now = Date.now();
        const still: number[] = [];
        let changed = false;
        for (const id of watching) {
          const item = list.find((entry) => entry.id === id);
          if (!item) continue; // 材料被删了，不再跟
          if (item.status === 'failed') continue; // 失败由卡片上的「重新读取」接手
          if (seen[id] !== item.status) changed = true;
          seen[id] = item.status;
          if (item.status === 'parsed') {
            if (!settleUntil[id]) settleUntil[id] = now + 12_000;
            if (now < settleUntil[id]) still.push(id);
            continue;
          }
          if (now - startedAt < 6 * 60 * 1000) still.push(id);
        }

        if (!still.length) {
          setWatching([]);
          return;
        }
        delay = changed ? 2000 : Math.min(delay + 1000, 5000);
        schedule(delay);
      } finally {
        running = false;
      }
    };

    schedule(delay);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [watching, project.id, refresh]);

  /** 文件与粘贴文本都从这里进：先挑格式、再判重、再逐份上传，每份在对话里留一张卡 */
  const intake = useCallback(
    async (files: File[]) => {
      if (!files.length) return;
      setOpen(true);
      const supported: File[] = [];
      const rejected: File[] = [];
      for (const file of files) {
        if (isSupportedFile(file)) supported.push(file);
        else rejected.push(file);
      }
      for (const file of rejected) {
        const suffix = file.name.split('.').pop() ?? '';
        const reason = `不支持 .${suffix} 这种格式`;
        setMessages((prev) => [
          ...prev,
          {
            id: newId(),
            role: 'material',
            text: file.name,
            uploadError: reason,
          },
        ]);
        // 失败也进历史：落成一张"没跑完"的工具卡，刷新后还看得到
        void api
          .appendAgentMessage(project.id, {
            role: 'tool',
            kind: 'job',
            text: file.name,
            data: { tool: 'upload', label: file.name, status: 'failed', summary: reason },
          })
          .catch(() => undefined);
      }
      if (!supported.length) return;

      const known = project.materials ?? [];
      const fresh = supported.filter(
        (file) => !known.some((item) => item.filename === file.name && item.size_bytes === file.size),
      );
      const repeats = supported.length - fresh.length;
      if (repeats) {
        toast.push(repeats === 1 ? '这份材料已经在项目里了' : `${repeats} 份材料已经在项目里了`);
      }
      for (const file of fresh) {
        try {
          const material = await api.uploadMaterial(project.id, file);
          setMessages((prev) => [
            ...prev,
            { id: newId(), role: 'material', text: file.name, materialId: material.id },
          ]);
          void api
            .appendAgentMessage(project.id, {
              role: 'tool',
              kind: 'material',
              text: file.name,
              data: { material_id: material.id },
            })
            .catch(() => undefined);
          setWatching((prev) => (prev.includes(material.id) ? prev : [...prev, material.id]));
        } catch (error) {
          // 上传失败也留一张卡：这份材料没进来，是用户需要知道的事，toast 滚走就没了
          const reason = error instanceof Error ? error.message : '上传失败';
          setMessages((prev) => [
            ...prev,
            {
              id: newId(),
              role: 'material',
              text: file.name,
              uploadError: reason,
              file,
            },
          ]);
          void api
            .appendAgentMessage(project.id, {
              role: 'tool',
              kind: 'job',
              text: file.name,
              data: { tool: 'upload', label: file.name, status: 'failed', summary: reason },
            })
            .catch(() => undefined);
        }
      }
      await refresh();
    },
    [project.id, project.materials, refresh, toast],
  );

  const retryMaterial = async (materialId: number) => {
    try {
      await api.reparseMaterial(materialId);
      await refresh();
      setWatching((prev) => (prev.includes(materialId) ? prev : [...prev, materialId]));
    } catch (error) {
      toast.push(error instanceof Error ? error.message : '重新读取失败', 'error');
    }
  };

  /** 刚上传就能撤回：不用等它读完再去材料行删 */
  const withdrawMaterial = async (materialId: number) => {
    try {
      await api.deleteMaterial(materialId);
      setWatching((prev) => prev.filter((id) => id !== materialId));
      await refresh();
    } catch (error) {
      toast.push(error instanceof Error ? error.message : '撤回失败', 'error');
    }
  };

  const openRequirements = () => {
    window.location.hash = `/projects/${project.id}/requirements`;
  };

  const storePasted = () => {
    const text = question.trim();
    if (!text) return;
    const stamp = new Date().toLocaleDateString('zh-CN').replace(/\//g, '-');
    setQuestion('');
    setPasting(false);
    void intake([new File([text], `聊天记录-${stamp}.txt`, { type: 'text/plain' })]);
  };

  /** 拖到页面任何位置都算交给 Agent（共用整页拖拽能力，工作台用的是同一套） */
  const dragging = useFileDrop((files) => void intake(files));

  /** 新卡片要能自己滚进视野：一次拖 5 份时，最新那张不该在屏幕外 */
  useEffect(() => {
    const element = messagesRef.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [messages.length, thinking]);

  /** 会话历史：刷新页面、换台机器回来，Agent 还认得聊过什么、做过什么 */
  useEffect(() => {
    let cancelled = false;
    api
      .agentMessages(project.id)
      .then((list) => {
        if (cancelled) return;
        setMessages(list.map(toChatMessage).filter((item): item is ChatMessage => item !== null));
      })
      .catch(() => undefined);
    api
      .agentState(project.id)
      .then((data) => {
        if (!cancelled) setNextStep(data.next_step);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [project.id]);

  /**
   * 右侧是核心交互面：内容**不随中间页变**。
   * 永远只有这三样 —— 一句结论、三个功能的进度、下一步（由状态机给），
   * 「你在看哪一页」只用一行小字说明，不改变内容。
   */
  const progress = [
    `${materials.length} 份材料`,
    requirements.length
      ? `${requirements.length} 条需求${confirmedRequirements.length ? `（确认 ${confirmedRequirements.length}）` : ''}`
      : '需求未整理',
    solution ? `建议 v${solution.version}` : matches.length ? '建议待生成' : '未做判断',
  ].join(' · ');
  const report = {
    verdict,
    reasons,
    progress,
    next: nextStep,
    watching: MODULE_LABELS[module],
  };

  /** 动作由前端执行：走的还是既有端点，所以权限、留痕、刷新只有一条路径 */
  const runTool = (tool: string, problem: string | null): Promise<Job | null> => {
    if (tool === 'run_full_analysis') return onRunAnalysis();
    if (tool === 'run_extraction') {
      return runTask(() => api.extractRequirements(project.id), '需求整理');
    }
    if (tool === 'compose_solution') {
      return runTask(() => api.generateSolution(project.id, problem ?? ''), '售前建议');
    }
    return runTask(() => api.runMatching(project.id), '能力判断');
  };

  /** 干完之后说一句结果：数字取自 job 的返回值，不猜 */
  const summarize = (finished: Job): string => {
    const counts = finished.result?.counts as Record<string, number> | undefined;
    if (counts) {
      return `判断完成：完全支持 ${counts.full ?? 0} · 部分支持 ${counts.partial ?? 0} · 暂不支持 ${
        counts.none ?? 0
      } · 待补依据 ${counts.unknown ?? 0}。`;
    }
    const requirements = finished.result?.requirements;
    if (typeof requirements === 'number') {
      return `整理出 ${requirements} 条需求，去需求确认逐条核对。`;
    }
    const version = finished.result?.version;
    if (typeof version === 'number') {
      return `售前建议 v${version} 已生成，结论、风险与下一步都在上面。`;
    }
    return '跑完了，结果已经更新到页面上。';
  };

  /** 跑一个动作并把回执卡走完：开始 → 完成/失败，全程只更新同一张卡 */
  const runToolWithCard = async (
    tool: string,
    label: string,
    opening: string,
    problem: string | null,
    options?: { existingJobId?: string },
  ) => {
    // 先落一张「正在跑」的回执卡，跑完再更新它 —— 刷新页面也看得到这一步做过
    const card = await api
      .appendAgentMessage(project.id, {
        role: 'tool',
        kind: 'job',
        text: opening,
        data: { tool, label, status: 'running' },
      })
      .catch(() => null);
    const localId = card ? `srv-${card.id}` : newId();
    setMessages((prev) => [
      ...prev,
      {
        id: localId,
        role: 'agent',
        text: opening,
        tool: { name: tool, label, status: 'running', messageId: card?.id },
      },
    ]);

    // 确认需求之后后端会自动开始能力判断，那种情况直接跟着已有的 job，不再起第二个
    const finished = options?.existingJobId
      ? await runTask(async () => ({ job_id: options.existingJobId as string }), label)
      : await runTool(tool, problem);
    const status = finished?.status === 'done' ? 'done' : 'failed';
    const summary =
      finished?.status === 'done' ? summarize(finished) : '这一步没跑完，可以再让我试一次。';
    setMessages((prev) =>
      prev.map((item) =>
        item.id === localId
          ? {
              ...item,
              tool: { name: tool, label, status, summary, jobId: finished?.id, messageId: card?.id },
            }
          : item,
      ),
    );
    if (card) {
      void api
        .patchAgentMessage(card.id, {
          text: summary,
          data: { tool, label, status, summary, job_id: finished?.id },
        })
        .catch(() => undefined);
    }
    // 动作改变了项目状态，下一步重新问状态机（唯一来源）
    void api
      .agentState(project.id)
      .then((data) => setNextStep(data.next_step))
      .catch(() => undefined);
    return finished;
  };

  const send = async () => {
    const text = question.trim();
    if (!text || thinking) return;
    setMessages((prev) => [...prev, { id: newId(), role: 'user', text }]);
    setQuestion('');
    setThinking(true);
    try {
      const reply = await api.askAgent(project.id, text);
      setNextStep(reply.next_step ?? null);

      // 一条龙：按状态机给的顺序跑，遇到人工闸门就停下来说明
      if (reply.kind === 'plan') {
        setMessages((prev) => [...prev, { id: newId(), role: 'agent', text: reply.text }]);
        for (const step of reply.steps ?? []) {
          const label = TOOL_LABELS[step] ?? step;
          await runToolWithCard(step, label, `开始${label}。`, reply.problem ?? null);
        }
        const gate = reply.gate;
        if (gate) {
          setMessages((prev) => [
            ...prev,
            {
              id: newId(),
              role: 'agent',
              text: `到这里需要你来：${gate.label}。`,
              refs: [{ label: '去这一页', href: `/projects/${project.id}/${gate.target}` }],
            },
          ]);
        }
        return;
      }

      if (reply.kind === 'action' && reply.tool) {
        const label = reply.tool_label ?? '动作';
        const opening = reply.text || `开始${label}。`;
        await runToolWithCard(reply.tool, label, opening, reply.problem);
        return;
      }

      // 需要人点头的动作：落一张待批准卡，点了才执行
      if (reply.kind === 'approval' && reply.approval) {
        const prepared = reply.approval;
        const card = await api
          .appendAgentMessage(project.id, {
            role: 'tool',
            kind: 'approval',
            text: reply.text,
            data: { approval: prepared },
          })
          .catch(() => null);
        setMessages((prev) => [
          ...prev,
          {
            id: card ? `srv-${card.id}` : newId(),
            role: 'agent',
            text: reply.text,
            approval: {
              messageId: card?.id,
              tool: prepared.tool,
              label: prepared.label,
              detail: prepared.detail,
              ids: prepared.payload?.ids,
            },
          },
        ]);
        return;
      }

      setMessages((prev) => [
        ...prev,
        {
          id: newId(),
          role: 'agent',
          text: reply.text,
          refs: citationRefs(reply.citations),
        },
      ]);
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        {
          id: newId(),
          role: 'agent',
          text: error instanceof Error ? `没能回答：${error.message}` : '没能回答这个问题。',
        },
      ]);
    } finally {
      setThinking(false);
    }
  };

  /** 界面上的「下一步」：能自动跑的点了就跑，要人做的就跳到那一页 */
  const runNextStep = async () => {
    if (!nextStep || thinking) return;
    if (!nextStep.tool) {
      window.location.hash = `/projects/${project.id}/${nextStep.target}`;
      return;
    }
    setThinking(true);
    try {
      await runToolWithCard(nextStep.tool, nextStep.label, `开始${nextStep.label}。`, null);
    } finally {
      setThinking(false);
    }
  };

  /** 批准之后才执行：先留痕（谁来批、什么时候），再调既有端点 */
  const decideApproval = async (message: ChatMessage, approved: boolean) => {
    const approval = message.approval;
    if (!approval || thinking) return;
    setThinking(true);
    const decision = approved ? 'approved' : 'declined';
    try {
      const saved = approval.messageId
        ? await api.recordApproval(project.id, { message_id: approval.messageId, decision })
        : null;
      const by = (saved?.data?.approval as Record<string, unknown> | undefined)?.by;
      setMessages((prev) =>
        prev.map((item) =>
          item.id === message.id && item.approval
            ? { ...item, approval: { ...item.approval, decision, by: typeof by === 'string' ? by : undefined } }
            : item,
        ),
      );
      if (!approved) return;

      if (approval.tool === 'confirm_requirements') {
        const result = await api.confirmRequirements(project.id, approval.ids);
        // 确认已经生效，先把状态卡刷新到最新（不用等判断跑完）
        await refresh();
        setMessages((prev) => [
          ...prev,
          { id: newId(), role: 'agent', text: `确认了 ${result.confirmed} 条需求，基线已更新。` },
        ]);
        // 确认需求之后后端会自动开始能力判断，跟着那个 job 走
        if (result.job_id) {
          await runToolWithCard('run_matching', '能力判断', '确认之后自动开始能力判断。', null, {
            existingJobId: result.job_id,
          });
        }
      }
    } catch (error) {
      toast.push(error instanceof Error ? error.message : '这一步没做成', 'error');
    } finally {
      setThinking(false);
    }
  };

  const body = (
    <div className="agent__inner">
      <header className="agent__head">
        <span className="agent__mark" aria-hidden="true">
          <IconSpark width={15} height={15} />
        </span>
        <div>
          <strong>
            Fitwise Agent
            <HelpTip
              label="Agent 能做什么"
              text="回答只基于本项目的材料与结论、都能点回原文；也可以直接说「整理需求」「做判断」「写建议」。上传材料在「客户材料」页，或把文件拖进页面。"
            />
          </strong>
          <span className="hint hint--inline">
            {project.customer_name} · {project.name}
          </span>
        </div>
        <button type="button" className="agent__close" aria-label="收起 Agent" onClick={() => setOpen(false)}>
          <IconClose width={14} height={14} />
        </button>
      </header>

      <section className="agent__report">
        <span className="agent__label">
          项目状态
          <span className="hint hint--inline">正在看：{report.watching}</span>
        </span>
        <p className="agent__verdict">{report.verdict}</p>
        {/* 空项目时只留一句话：结论 + 一条引导，不铺三行数字，第一屏才不显得重 */}
        <ul className="agent__reasons">
          {(materials.length ? [...new Set(report.reasons)] : report.reasons.slice(0, 1)).map((item) => (
            <li key={item}>
              <span className={`agent__tick${riskCount ? ' agent__tick--warn' : ''}`}>
                {riskCount ? <IconAlert width={11} height={11} /> : <IconCheck width={11} height={11} />}
              </span>
              {item}
            </li>
          ))}
        </ul>
        {materials.length ? <p className="agent__progress">{report.progress}</p> : null}
        {report.next ? (
          <div className="agent__next">
            <span className="agent__label">下一步</span>
            <p>{report.next.label}</p>
            <button
              type="button"
              className="btn btn--primary btn--sm"
              onClick={() => void runNextStep()}
              disabled={thinking || busy}
            >
              {report.next.tool ? `开始${report.next.label}` : `去${MODULE_LABELS[report.next.target]}`}
            </button>
          </div>
        ) : (
          <p className="hint hint--inline">该做的都做完了，直接看售前建议就行。</p>
        )}
      </section>

      <section className="agent__chat">
        <span className="agent__label">对话</span>
        <div className="agent__messages" aria-live="polite" ref={messagesRef}>
          {messages.length === 0 ? null : (
            messages.map((message) => {
              if (message.approval) {
                return (
                  <ApprovalCard
                    key={message.id}
                    approval={message.approval}
                    busy={thinking}
                    onDecide={(approved) => void decideApproval(message, approved)}
                  />
                );
              }
              if (message.tool) {
                return <ToolCard key={message.id} tool={message.tool} projectId={project.id} />;
              }
              if (message.role === 'material') {
                // 上传就没成功：没有 material 可查，只留文件名与原因
                if (!message.materialId) {
                  return (
                    <div key={message.id} className="agent-card agent-card--bad">
                      <div className="agent-card__head">
                        <span className="agent-card__dot" aria-hidden="true" />
                        <strong className="agent-card__name">{message.text}</strong>
                      </div>
                      <p className="agent-card__state">没有进来：{message.uploadError}</p>
                      {message.file ? (
                        <div className="agent-card__actions">
                          <button
                            type="button"
                            className="link-btn"
                            onClick={() => void intake([message.file as File])}
                          >
                            <IconRefresh width={12} height={12} />
                            重试
                          </button>
                        </div>
                      ) : null}
                    </div>
                  );
                }
                const material = materials.find((item) => item.id === message.materialId);
                return material ? (
                  <MaterialCard
                    key={message.id}
                    material={material}
                    factCount={factCountOf(material)}
                    requirementCount={requirementCountOf(material)}
                    draftCount={draftCountOf(material)}
                    onOpenSource={() => openSource(material.id)}
                    onRetry={() => void retryMaterial(material.id)}
                    onWithdraw={() => void withdrawMaterial(material.id)}
                    onOpenRequirements={openRequirements}
                  />
                ) : (
                  <p key={message.id} className="hint">
                    这份材料已删除。
                  </p>
                );
              }
              return (
                <div key={message.id} className={`bubble bubble--${message.role}`}>
                  <p>{message.text}</p>
                  {message.refs?.length ? (
                    <div className="bubble__refs">
                      {message.refs.map((ref, index) =>
                        ref.materialId || ref.page ? (
                          <button
                            key={`${ref.label}-${index}`}
                            type="button"
                            className="link-btn"
                            onClick={() => openSource(ref.materialId ?? 0, ref.page ?? 1)}
                            disabled={!ref.materialId}
                          >
                            <IconEvidence width={12} height={12} />
                            {ref.label}
                          </button>
                        ) : ref.href ? (
                          <button
                            key={`${ref.label}-${index}`}
                            type="button"
                            className="link-btn"
                            onClick={() => {
                              window.location.hash = ref.href as string;
                            }}
                          >
                            <IconArrowRight width={12} height={12} />
                            {ref.label}
                          </button>
                        ) : (
                          <span key={`${ref.label}-${index}`} className="bubble__ref">
                            <IconEvidence width={12} height={12} />
                            {ref.label}
                          </span>
                        ),
                      )}
                    </div>
                  ) : null}
                </div>
              );
            })
          )}
          {thinking ? (
            <div className="bubble bubble--agent">
              <p>正在看材料…</p>
            </div>
          ) : null}
        </div>
        <div className="agent__composer">
          <div className="agent__composer-bar">
            {/* 上传入口在「客户材料」页（拖拽到页面任意位置同样有效）；这里只保留对话。
                邮件/聊天记录这类没有文件的内容，用「粘贴为材料」送进来。 */}
            <button
              type="button"
              className="link-btn"
              onClick={() => {
                setPasting((prev) => !prev);
                setQuestion('');
              }}
            >
              {pasting ? '取消' : '粘贴为材料'}
            </button>
          </div>

          {pasting ? (
            <textarea
              className="textarea"
              rows={4}
              placeholder="粘贴客户聊天记录或邮件正文…"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
            />
          ) : (
            <input
              className="textarea"
              value={question}
              placeholder={
                module === 'materials'
                  ? '问材料里的信息，比如「工期是多久」…'
                  : module === 'requirements'
                    ? '问客户诉求，或说「整理需求」…'
                    : '问风险与下一步，比如「支持私有化吗」…'
              }
              onChange={(event) => setQuestion(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') send();
              }}
            />
          )}

          <div className="agent__composer-foot">
            {pasting ? <span className="hint hint--inline">会作为材料存档并抽取要点。</span> : null}
            {pasting ? (
              <button
                type="button"
                className="btn btn--primary btn--sm"
                onClick={storePasted}
                disabled={!question.trim()}
              >
                存入材料
              </button>
            ) : (
              <button
                type="button"
                className="btn btn--primary btn--sm"
                onClick={send}
                disabled={!question.trim()}
              >
                发送
              </button>
            )}
          </div>
        </div>
      </section>

      <footer className="agent__foot">
        <p className="hint">AI 初步判断，正式承诺需人工确认。</p>
      </footer>
    </div>
  );

  return (
    <>
      <button type="button" className="agent-fab" onClick={() => setOpen(true)}>
        <IconSpark width={15} height={15} />
        Fitwise Agent
      </button>
      <aside className={`agent${open ? ' agent--open' : ''}`}>{body}</aside>
      {dragging ? <FileDropOverlay hint="松手交给 Fitwise Agent —— 读完的材料与要点会出现在中间页" /> : null}
    </>
  );
}
