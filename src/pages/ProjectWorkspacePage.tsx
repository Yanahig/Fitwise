import { useCallback, useEffect, useState } from 'react';
import { api, pollJob } from '../api/endpoints';
import { track } from '../api/telemetry';
import type { Job, Match, Project } from '../api/types';
import { PipelineProgress, jobLabel } from '../components/PipelineProgress';
import { SkeletonCard } from '../components/Skeleton';
import { useToast } from '../components/Toast';
import { AgentPanel } from '../components/project/AgentPanel';
import { ProjectContextBar } from '../components/project/ProjectContextBar';
import type { ModuleKey } from '../components/project/ProjectContextBar';
import { MaterialsModule } from '../components/project/MaterialsModule';
import { RequirementsModule } from '../components/project/RequirementsModule';
import { JudgementPage } from './JudgementPage';

export interface ProjectTabProps {
  project: Project;
  refresh: () => Promise<void>;
  runTask: (starter: () => Promise<{ job_id: string }>, label: string) => Promise<Job | null>;
  job: Job | null;
  busy: boolean;
}

/** 产品结构就是这三个功能：材料解析（含确认）→ 能力匹配 → 售前建议，没有中间步骤 */
const MODULE_TABS: ModuleKey[] = ['materials', 'requirements', 'judgement'];

function isModuleTab(value: string): value is ModuleKey {
  return (MODULE_TABS as string[]).includes(value);
}

export function ProjectWorkspacePage({
  projectId,
  tab,
  navigate,
}: {
  projectId: number;
  tab: string;
  navigate: (to: string) => void;
}) {
  const [project, setProject] = useState<Project | null>(null);
  const [matches, setMatches] = useState<Match[]>([]);
  const [job, setJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const toast = useToast();

  const refresh = useCallback(async () => {
    const [detail, matchList] = await Promise.all([api.project(projectId), api.matches(projectId)]);
    setProject(detail);
    setMatches(matchList);
    // 读到数据就说明连接正常 —— 清掉上一次的瞬时失败提示，别让它常驻
    setError(null);
  }, [projectId]);

  useEffect(() => {
    window.localStorage.setItem('fitwise.lastProject', String(projectId));
    refresh().catch((loadError) =>
      setError(loadError instanceof Error ? loadError.message : '加载项目失败'),
    );
  }, [refresh]);

  /**
   * 旧路由（概览 / 方案 / 行动 / 复盘）已经并入三个核心功能，
   * 一律立刻回落到第 1 个功能「材料解析」。
   */
  const moduleTab: ModuleKey = isModuleTab(tab) ? tab : 'materials';
  useEffect(() => {
    if (!isModuleTab(tab)) navigate(`/projects/${projectId}/materials`);
  }, [tab, projectId, navigate]);

  /**
   * 跨功能跳转：售前建议里点「看这条需求」、判断详情里点「去看全部」，都会切页并滚到锚点。
   * 用事件而不是层层传回调 —— 页面之间只认"去哪个 tab、滚到哪个锚点"。
   */
  useEffect(() => {
    const handler = (event: Event) => {
      const detail = (event as CustomEvent<{ tab?: string; anchor?: string }>).detail ?? {};
      if (!detail.tab) return;
      navigate(`/projects/${projectId}/${detail.tab}`);
      if (!detail.anchor) return;
      // 目标页要等渲染完才有锚点，给它几次机会，找不到就算了（不弹错）
      let tries = 0;
      const timer = window.setInterval(() => {
        const target = document.getElementById(String(detail.anchor));
        if (target || ++tries > 8) {
          target?.scrollIntoView({ behavior: 'smooth', block: 'start' });
          window.clearInterval(timer);
        }
      }, 200);
      window.setTimeout(() => window.clearInterval(timer), 3000);
    };
    window.addEventListener('fitwise:open-project-tab', handler);
    return () => window.removeEventListener('fitwise:open-project-tab', handler);
  }, [navigate, projectId]);

  const runTask = useCallback(
    async (starter: () => Promise<{ job_id: string }>, label: string) => {
      const startedAt = Date.now();
      setBusy(true);
      setError(null);
      try {
        const { job_id } = await starter();
        const finished = await pollJob(job_id, setJob);
        if (finished.status === 'failed') {
          // 失败也留痕：定位问题时"哪一步、哪个 job、跑了多久"比错误文案更有用
          track('action_finished', {
            label,
            job: job_id,
            status: 'failed',
            ms: Date.now() - startedAt,
            message: String(finished.error ?? '').slice(0, 120),
          });
          setError(`${label}失败：${finished.error}`);
          return finished;
        }
        await refresh();
        track('action_finished', {
          label,
          job: job_id,
          status: 'ok',
          ms: Date.now() - startedAt,
        });
        toast.push(`${label}完成`, 'success');
        return finished;
      } catch (taskError) {
        const message = taskError instanceof Error ? taskError.message : `${label}失败`;
        track('action_finished', {
          label,
          status: 'error',
          ms: Date.now() - startedAt,
          message: message.slice(0, 120),
        });
        setError(message);
        toast.push(message, 'error');
        return null;
      } finally {
        setJob(null);
        setBusy(false);
      }
    },
    [refresh, toast],
  );

  /** Fitwise 的完整分析链：提炼需求 → 能力匹配。用户只需要点一次（上传后也会自动跑） */
  const runFullAnalysis = () =>
    runTask(async () => {
      const extract = await api.extractRequirements(project?.id ?? projectId);
      await pollJob(extract.job_id, setJob);
      return api.runMatching(project?.id ?? projectId);
    }, 'Fitwise 分析');

  if (!project) {
    return (
      <div className="page page--stack">
        {error ? <p className="inline-error">{error}</p> : <SkeletonCard rows={4} />}
      </div>
    );
  }

  return (
    <div className="page page--stack page--module">
      <ProjectContextBar
        project={project}
        matches={matches}
        active={moduleTab}
        onSwitch={(key) => navigate(`/projects/${projectId}/${key}`)}
        onRenamed={refresh}
      />

      {job ? (
        <section className="panel">
          <PipelineProgress
            stages={[
              {
                id: 'running',
                label: jobLabel(job.kind).title,
                detail: job.current ? `正在处理：${job.current}` : jobLabel(job.kind).detail,
              },
              { id: 'done', label: '整理结果', detail: `已完成 ${job.done}/${job.total}` },
            ]}
            currentIndex={job.total > 0 && job.done >= job.total ? 1 : 0}
            title={jobLabel(job.kind).title}
          />
        </section>
      ) : null}

      {error ? <p className="inline-error">{error}</p> : null}

      {moduleTab === 'materials' ? (
        <div className="workspace-grid">
          <div className="workspace-grid__main">
            <MaterialsModule
              project={project}
              refresh={refresh}
              runTask={runTask}
              job={job}
              busy={busy}
            />
          </div>
          <AgentPanel
            project={project}
            matches={matches}
            module="materials"
            busy={busy}
            onRunAnalysis={runFullAnalysis}
            runTask={runTask}
            refresh={refresh}
          />
        </div>
      ) : null}

      {moduleTab === 'requirements' ? (
        <div className="workspace-grid">
          <div className="workspace-grid__main">
            <RequirementsModule
              project={project}
              matches={matches}
              refresh={refresh}
              runTask={runTask}
              job={job}
              busy={busy}
            />
          </div>
          <AgentPanel
            project={project}
            matches={matches}
            module="requirements"
            busy={busy}
            onRunAnalysis={runFullAnalysis}
            runTask={runTask}
            refresh={refresh}
          />
        </div>
      ) : null}

      {moduleTab === 'judgement' ? (
        <div className="workspace-grid">
          <div className="workspace-grid__main">
            {/* 逐条结论在能力匹配页；这一页负责风险与「要问谁」 */}
            <JudgementPage
              key={project.id}
              project={project}
              matches={matches}
              busy={busy}
              onGenerate={() => void runTask(() => api.generateSolution(project.id, ''), '售前建议')}
            />
          </div>
          <AgentPanel
            project={project}
            matches={matches}
            module="judgement"
            busy={busy}
            onRunAnalysis={runFullAnalysis}
            runTask={runTask}
            refresh={refresh}
          />
        </div>
      ) : null}
    </div>
  );
}
