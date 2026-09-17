import { useCallback, useEffect, useState } from 'react';
import { api } from '../api/endpoints';
import type { DashboardData, Project } from '../api/types';
import { EmptyState } from '../components/EmptyState';
import { FileDropOverlay, useFileDrop } from '../components/FileDrop';
import { SkeletonRows } from '../components/Skeleton';
import { useToast } from '../components/Toast';
import { IconCheck, IconCompass, IconFile } from '../components/icons';
import { pollJob } from '../api/endpoints';

const INTAKE_STEPS = [
  '已读取客户材料',
  '已整理出客户需求',
  '已给出售前建议',
];

/** 留空时的占位名：后端看到占位名，就用材料里识别出来的真名替换（人工填过的不覆盖） */
const PENDING_CUSTOMER = '待识别客户';
const PENDING_PROJECT = '待识别项目';

/** 三个核心功能同时也是上手路径：每一步都给出「点这里能做什么」 */
const GUIDE_STEPS = [
  {
    key: 'materials',
    to: 'materials',
    title: '材料解析',
    hint: '材料丢进来，自动读完并按页存档；摘出的要点与需求都带原文那一句，逐条确认后进入能力匹配',
  },
  {
    key: 'requirements',
    to: 'requirements',
    title: '能力匹配',
    hint: '已确认的需求在这里出结论：完全支持 / 部分支持 / 暂不支持 / 待补依据，以及风险',
  },
  {
    key: 'judgement',
    to: 'judgement',
    title: '售前建议',
    hint: '风险、要问谁，以及不可承诺的边界',
  },
];

/** 项目在三个功能上的完成度（0–3），列表里用它画进度条。 */
function stepProgress(project: Project): number {
  const counts = project.counts;
  if (!counts) return 0;
  if (counts.matches > 0) return 3;
  if (counts.requirements_confirmed > 0) return 2;
  if (counts.materials_parsed > 0) return 1;
  return 0;
}

export function DashboardPage({ navigate }: { navigate: (to: string) => void }) {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [showGuide, setShowGuide] = useState(false);
  const [intake, setIntake] = useState<{ customerName: string; projectName: string; files: File[] }>({
    customerName: '',
    projectName: '',
    files: [],
  });
  /** 进度条只在分析进行中出现；每一步的文案由 INTAKE_STEPS 统一给出 */
  const [intakeRunning, setIntakeRunning] = useState(false);
  const [intakeIndex, setIntakeIndex] = useState(0);
  const [intakeBusy, setIntakeBusy] = useState(false);

  /**
   * 拖到页面任何位置都算"选材料"：追加到表单里（同名文件不重复加），
   * 并把表单滚进视野 —— 否则用户松手后看不到东西，以为没成功。
   */
  const addDroppedFiles = useCallback((files: File[]) => {
    setIntake((prev) => {
      const names = new Set(prev.files.map((file) => file.name));
      return { ...prev, files: [...prev.files, ...files.filter((file) => !names.has(file.name))] };
    });
    document.getElementById('fitwise-intake')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, []);
  const dragging = useFileDrop(addDroppedFiles);

  /** 交给 Fitwise：建客户 → 建项目 → 上传材料 → 自动跑完整分析链，用户只点这一次 */
  const submitIntake = async () => {
    setIntakeBusy(true);
    setIntakeRunning(true);
    setIntakeIndex(0);
    try {
      const customer = await api.createCustomer({ name: intake.customerName.trim() || PENDING_CUSTOMER });
      const project = await api.createProject({
        customer_id: customer.id,
        name: intake.projectName.trim() || PENDING_PROJECT,
      });
      window.localStorage.setItem('fitwise.lastProject', String(project.id));

      if (intake.files.length) {
        for (const file of intake.files) {
          await api.uploadMaterial(project.id, file);
        }
        setIntakeIndex(1);
        // 等待材料读取完成（后端读完会自动提炼需求）
        for (let attempt = 0; attempt < 40; attempt += 1) {
          await new Promise((resolve) => setTimeout(resolve, 3000));
          const materials = await api.materials(project.id);
          if (materials.length && materials.every((item) => item.status === 'parsed' || item.status === 'failed')) {
            break;
          }
        }
      }

      setIntakeIndex(1);
      const extract = await api.extractRequirements(project.id);
      await pollJob(extract.job_id);
      setIntakeIndex(2);

      // 名字留空的话，这会儿已经被材料里的真名替换了 —— 告诉用户它认出了什么
      const refreshed = await api.project(project.id);
      const recognized = refreshed.name !== PENDING_PROJECT || refreshed.customer_name !== PENDING_CUSTOMER;
      if (recognized) {
        toast.push(`已从材料识别：${refreshed.customer_name} · ${refreshed.name}`, 'success');
      }

      const matching = await api.runMatching(project.id);
      await pollJob(matching.job_id);
      setIntakeIndex(3);

      toast.push('分析完成，正在打开售前建议', 'success');
      navigate(`/projects/${project.id}/judgement`);
    } catch (error) {
      toast.push(error instanceof Error ? error.message : '分析失败，请重试', 'error');
    } finally {
      setIntakeRunning(false);
      setIntakeBusy(false);
    }
  };
  const toast = useToast();

  useEffect(() => {
    api
      .dashboard()
      .then(setData)
      .catch((error) => toast.push(error instanceof Error ? error.message : '加载工作台失败', 'error'))
      .finally(() => setLoading(false));
  }, [toast]);

  if (loading) {
    return (
      <div className="page page--stack">
        <SkeletonRows count={3} />
      </div>
    );
  }

  if (!data) {
    return (
      <div className="page page--stack">
        <EmptyState
          icon={<IconCompass width={26} height={26} />}
          title="数据暂时没加载出来"
          description="刷新页面重试；仍失败请联系管理员。"
        />
      </div>
    );
  }

  const firstProject = data.projects[0];
  const focusIntake = () =>
    document.getElementById('fitwise-intake')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  const goFor = (key: string) => {
    const step = GUIDE_STEPS.find((item) => item.key === key);
    if (!step || !firstProject) return focusIntake();
    return navigate(`/projects/${firstProject.id}/${step.to}`);
  };
  const currentStep = firstProject ? stepProgress(firstProject) : 0;
  const currentStepIndex = Math.min(currentStep, GUIDE_STEPS.length - 1);

  return (
    <div className="page page--stack page-enter">
      {/* 新建分析：和「项目管理」同一套骨架（标题在左、动作在右、一行一件事） */}
      {/* 拖拽时给表单描一圈虚线，明确"松手会落到这里" */}
      <section className={`section-open${dragging ? ' section-open--drop' : ''}`} id="fitwise-intake">
        <header className="section-open__head">
          <div>
            <h3>新建分析</h3>
            <p className="hint">把客户材料交给 Fitwise：它读完、整理需求、给出判断与下一步。</p>
          </div>
          <div className="section-open__actions">
            <button type="button" className="link-btn" onClick={() => setShowGuide((prev) => !prev)}>
              {showGuide ? '收起' : '第一次用？看这三个功能'}
            </button>
            <button
              type="button"
              className="btn btn--primary btn--sm"
              // 名称可以留空（由材料识别），但至少要有一样：名称或材料
              disabled={
                intakeBusy ||
                (!intake.files.length && (!intake.customerName.trim() || !intake.projectName.trim()))
              }
              onClick={submitIntake}
            >
              {intakeBusy ? '分析中…' : '开始分析'}
            </button>
          </div>
        </header>

        <div className="list-shell">
          <label className="list-row list-row--form" htmlFor="intake-customer">
            <span className="list-row__title">客户名称</span>
            <input
              id="intake-customer"
              className="textarea"
              value={intake.customerName}
              placeholder="留空 = 从材料里识别（例如：XX 市档案馆）"
              onChange={(event) => setIntake({ ...intake, customerName: event.target.value })}
            />
          </label>

          <label className="list-row list-row--form" htmlFor="intake-project">
            <span className="list-row__title">项目名称</span>
            <input
              id="intake-project"
              className="textarea"
              value={intake.projectName}
              placeholder="留空 = 从材料里识别（例如：档案数字化与智能处理平台）"
              onChange={(event) => setIntake({ ...intake, projectName: event.target.value })}
            />
          </label>

          <div className="list-row list-row--form">
            <span className="list-row__title">客户材料</span>
            <span className="list-row__sub">
              {intake.files.length
                ? `已选择 ${intake.files.length} 份：${intake.files.map((file) => file.name).join('、')}`
                : 'PDF / Word / Excel / PPT / 图片；名称留空时至少要给一份材料，也可以把文件拖到页面任意位置'}
            </span>
            <label className="btn btn--secondary btn--sm">
              <IconFile width={13} height={13} />
              选择文件
              <input
                type="file"
                multiple
                className="visually-hidden"
                accept=".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.png,.jpg,.jpeg,.txt,.ofd,.csv,.md"
                onChange={(event) => setIntake({ ...intake, files: Array.from(event.target.files ?? []) })}
              />
            </label>
          </div>

          {intakeRunning ? (
            <div className="list-row list-row--form">
              <span className="list-row__title">分析进度</span>
              <span className="list-row__sub">
                {intakeIndex >= INTAKE_STEPS.length ? (
                  <>
                    <IconCheck width={11} height={11} /> 已完成，正在打开售前建议
                  </>
                ) : (
                  `${INTAKE_STEPS[Math.min(intakeIndex, INTAKE_STEPS.length - 1)]}…`
                )}
              </span>
              <div className="list-row__metrics">
                <div className="list-row__metric">
                  <dt>进度</dt>
                  <dd>
                    {Math.min(intakeIndex, INTAKE_STEPS.length)}/{INTAKE_STEPS.length}
                  </dd>
                </div>
              </div>
            </div>
          ) : null}
        </div>

        {showGuide ? (
          <ol className="guide-line">
            {GUIDE_STEPS.map((step, index) => (
              <li key={step.key}>
                <button
                  type="button"
                  className={`guide-line__item${index === currentStepIndex ? ' guide-line__item--active' : ''}`}
                  onClick={() => goFor(step.key)}
                >
                  <span className="guide-line__index">{index + 1}</span>
                  {step.title}
                </button>
              </li>
            ))}
          </ol>
        ) : null}
      </section>

      {dragging ? (
        <FileDropOverlay hint="松手加入客户材料 —— 填好客户与项目名，点「开始分析」就行" />
      ) : null}
    </div>
  );
}
