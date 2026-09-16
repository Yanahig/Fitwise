import { useState } from 'react';
import type { Match, Priority, Requirement } from '../../api/types';
import type { ProjectTabProps } from '../../pages/ProjectWorkspacePage';
import { api, pollJob } from '../../api/endpoints';
import { summarizeOpenQuestion, summarizeOpenQuestions } from '../../domain/openQuestions';
import { PRIORITY_TAG } from '../../domain/status';
import { SummaryBar } from './SummaryBar';
import { useToast } from '../Toast';
import { HelpTip } from '../HelpTip';
import {
  IconEvidence,
  IconPlus,
  IconSpark,
} from '../icons';

const CATEGORIES = ['部署', '产品能力', '技术', '合规', '规模', '服务'];

/**
 * 需求确认：把客户要什么变成一份可核对的清单。
 *
 * 页面只有一条主线：核心需求 / 隐含需求两张清单，确认、编辑、删除都挂在条目上。
 * 信息缺口在这里只报总数，完整清单在售前建议页 —— 同一批问题不列两遍。
 */
export function RequirementsModule({
  project,
  matches,
  refresh,
  runTask,
  busy,
}: ProjectTabProps & { matches: Match[] }) {
  const [editingId, setEditingId] = useState<number | null>(null);
  const [draft, setDraft] = useState<Partial<Requirement>>({});
  const [showAdd, setShowAdd] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [newRequirement, setNewRequirement] = useState<{
    title: string;
    detail: string;
    category: string;
    priority: Priority;
  }>({ title: '', detail: '', category: '产品能力', priority: 'medium' });
  const toast = useToast();

  const requirements = project.requirements ?? [];
  const confirmed = requirements.filter((item) => item.status === 'confirmed');
  const inferred = requirements.filter((item) => item.created_by_ai && item.status !== 'confirmed');
  const materials = project.materials ?? [];
  const parsedMaterials = materials.filter((item) => item.status === 'parsed');
  const questions = project.open_questions ?? [];
  /** 待澄清的问题分两种：问客户的、内部先确认的 —— 概括行里要分得清 */
  const customerQuestions = questions.filter((item) => (item.owner || '客户') !== '内部').length;
  const internalQuestions = questions.length - customerQuestions;
  const matchByRequirement = new Map(matches.map((item) => [item.requirement_id, item]));
  /** 只有一份材料时不需要在每条需求上重复文件名，页码才是要找的东西 */
  const showSourceDocName = materials.length > 1;
  const impactCount = summarizeOpenQuestions(questions).filter((item) => item.affectsJudgement).length;
  const highPriority = requirements.filter((item) => item.priority === 'high').length;
  /** 草稿在前、基线在后：未确认的先处理，确认过的原地变成基线，不再跨分区搬家 */
  const orderedRequirements = [
    ...requirements.filter((item) => item.status !== 'confirmed'),
    ...requirements.filter((item) => item.status === 'confirmed'),
  ];
  /** 三块内容是一条链：需求确认完，下一步就是去看能不能做与下一步怎么办 */
  const openJudgement = () => {
    window.location.hash = `/projects/${project.id}/judgement`;
  };
  const canSeeAdvice = requirements.length > 0;

  const confirmOne = async (id: number) => {
    await api.updateRequirement(id, { status: 'confirmed' });
    await refresh();
    toast.push('已确认，将进入能力判断', 'success');
  };

  const confirmAll = async () => {
    setConfirming(true);
    try {
      const result = await api.confirmRequirements(project.id);
      await refresh();
      if (result.job_id) {
        toast.push(`已确认 ${result.confirmed} 条，正在判断`, 'success');
        await pollJob(result.job_id);
        await refresh();
        toast.push('判断完成，可去看售前建议', 'success');
      } else {
        toast.push(`已确认 ${result.confirmed} 条需求`, 'success');
      }
    } catch (error) {
      toast.push(error instanceof Error ? error.message : '确认失败', 'error');
    } finally {
      setConfirming(false);
    }
  };

  const removeRequirement = async (id: number) => {
    await api.deleteRequirement(id);
    await refresh();
    toast.push('已移除');
  };

  const saveEdit = async () => {
    if (editingId === null) return;
    await api.updateRequirement(editingId, draft);
    setEditingId(null);
    setDraft({});
    await refresh();
    toast.push('已更新', 'success');
  };

  const addRequirement = async () => {
    await api.createRequirement(project.id, newRequirement);
    setNewRequirement({ title: '', detail: '', category: '产品能力', priority: 'medium' });
    setShowAdd(false);
    await refresh();
    toast.push('已添加', 'success');
  };

  const renderRequirement = (item: Requirement, tone: 'confirmed' | 'draft', anchorId?: string) => {
    const match = matchByRequirement.get(item.id);
    const evidenceCount = (match?.capability_doc_ids.length ?? 0) + 1;

    if (editingId === item.id) {
      return (
        <li key={item.id} id={anchorId} className="req-item req-item--editing">
          <div className="edit-stack">
            <input
              className="textarea"
              value={draft.title ?? item.title}
              onChange={(event) => setDraft({ ...draft, title: event.target.value })}
            />
            <textarea
              className="textarea"
              rows={2}
              value={draft.detail ?? item.detail}
              onChange={(event) => setDraft({ ...draft, detail: event.target.value })}
            />
            <div className="create-form__grid">
              <select
                className="textarea"
                value={draft.category ?? item.category}
                onChange={(event) => setDraft({ ...draft, category: event.target.value })}
              >
                {CATEGORIES.map((category) => (
                  <option key={category}>{category}</option>
                ))}
              </select>
              <select
                className="textarea"
                value={draft.priority ?? item.priority}
                onChange={(event) =>
                  setDraft({ ...draft, priority: event.target.value as Requirement['priority'] })
                }
              >
                <option value="high">高优先级</option>
                <option value="medium">中优先级</option>
                <option value="low">低优先级</option>
              </select>
            </div>
            <div className="req-item__actions">
              <button type="button" className="btn btn--primary btn--sm" onClick={() => void saveEdit()}>
                保存
              </button>
              <button
                type="button"
                className="link-btn"
                onClick={() => {
                  setEditingId(null);
                  setDraft({});
                }}
              >
                取消
              </button>
            </div>
          </div>
        </li>
      );
    }

    return (
      <li
        key={item.id}
        id={anchorId}
        className={`req-item${tone === 'draft' ? ' req-item--draft' : ''}`}
      >
        <span className={`req-brief__p req-brief__p--${item.priority}`}>
          {PRIORITY_TAG[item.priority] ?? 'P1'}
        </span>
        <div className="req-brief__main">
          <span className="req-brief__title">
            {item.title}
            {/* 状态就在标题上：这份清单不再按"明说/推断"分区，只按"草稿/已进基线"区分 */}
            {tone === 'draft' ? <span className="req-brief__draft">草稿</span> : null}
          </span>
          {item.detail ? (
            <p className="req-item__detail" title={item.detail}>
              {item.detail}
            </p>
          ) : null}
          <div className="req-brief__meta">
            <span className="hint hint--inline">依据 {evidenceCount} 条</span>
            <button
              type="button"
              className="link-btn req-brief__view"
              title={[
                item.source.document_name,
                item.source.page ? `第 ${item.source.page} 页` : '',
              ]
                .filter(Boolean)
                .join(' · ')}
              onClick={() =>
                window.dispatchEvent(
                  new CustomEvent('fitwise:open-assets', {
                    detail: { materialId: item.source.material_id, page: item.source.page },
                  }),
                )
              }
            >
              <IconEvidence width={13} height={13} />
              {[
                showSourceDocName && item.source.document_name ? item.source.document_name : '',
                item.source.page ? `第 ${item.source.page} 页` : '',
              ]
                .filter(Boolean)
                .join(' · ') || '人工录入'}
            </button>
            {item.edited ? (
              <span className="hint hint--inline" title="人工改过内容：重新整理需求时这条会保留">
                已人工修改
              </span>
            ) : null}
          </div>
          <div className="req-item__actions">
            {tone === 'draft' ? (
              <button type="button" className="btn btn--primary btn--sm" onClick={() => void confirmOne(item.id)}>
                确认
              </button>
            ) : null}
            <details className="card-menu">
              <summary aria-label="更多操作">···</summary>
              <div className="card-menu__body">
                <button
                  type="button"
                  className="link-btn"
                  onClick={() => {
                    setEditingId(item.id);
                    setDraft({});
                  }}
                >
                  编辑
                </button>
                <button type="button" className="link-btn" onClick={() => void removeRequirement(item.id)}>
                  删除
                </button>
              </div>
            </details>
          </div>
        </div>
      </li>
    );
  };

  return (
    <div className="page page--stack">
      {/* 结论条：和另外两个功能页同一套骨架（一句结论 + 概括行 + 数字 + 主动作） */}
      <SummaryBar
        tone={inferred.length ? 'warn' : confirmed.length ? 'ok' : 'info'}
        verdict={
          !requirements.length
            ? '还没有整理出需求'
            : inferred.length
              ? `${confirmed.length} 条已确认，${inferred.length} 条等你确认`
              : `${requirements.length} 条需求已全部确认`
        }
        sub={`共 ${requirements.length} 项 · 已确认 ${confirmed.length} · 待确认 ${inferred.length} · 来自 ${materials.length} 份客户材料`}
        lines={[
          {
            label: '需求',
            text: `${requirements.length} 条（高优先级 ${highPriority} 条）`,
            target: 'requirements-list',
          },
          {
            label: '草稿需求',
            text: inferred.length ? `${inferred.length} 条，确认后进基线` : '全部已进基线',
            target: inferred.length ? 'requirements-draft' : 'requirements-list',
          },
          {
            label: '待澄清',
            text: questions.length
              ? `${questions.length} 处（问客户 ${customerQuestions} · 内部 ${internalQuestions}${
                  impactCount ? `，${impactCount} 处影响判断` : ''
                }）`
              : '暂时没有待澄清问题',
            target: 'pending-questions',
          },
        ]}
        action={
          inferred.length
            ? {
                label: confirming ? '确认中…' : `全部确认（${inferred.length}）`,
                onClick: () => void confirmAll(),
                disabled: confirming,
              }
            : undefined
        }
        // 左边永远是本页功能（全部确认），右边永远是「去下一段」——没有待确认时左侧就空着
        secondary={canSeeAdvice ? { label: '查看建议', onClick: openJudgement } : undefined}
      />

      {materials.length === 0 ? (
        <section className="intake-inline">
          <header className="intake-inline__head">
            <h3>还没有客户材料</h3>
            <p className="hint">
              在右侧 Agent 上传客户材料，Fitwise 会自动整理成需求清单；你只需要逐条确认。
            </p>
          </header>
          <div className="intake-inline__actions">
            <button
              type="button"
              className="btn btn--secondary btn--sm"
              onClick={() => {
                window.location.hash = `/projects/${project.id}/materials`;
              }}
            >
              去材料解析
            </button>
          </div>
        </section>
      ) : null}

      <div className="req-columns">
        {/* 一份清单，不再按「明说 / 推断」分家：草稿排前面、确认过的作为基线跟在后面 */}
        <section className="section-open" id="requirements-list">
          <header className="section-open__head">
            <div className="section-open__titleline">
              <h3>
                需求
                <span className="fact-group__count">{requirements.length}</span>
              </h3>
              <HelpTip text="客户材料里读出来的要求都在这一份清单里。带「草稿」标记的还没进基线，点确认后才算数 —— 只有进了基线的才会拿去判断能不能做。" />
            </div>
            <div className="section-open__actions">
              <button
                type="button"
                className="btn btn--ghost btn--sm"
                disabled={busy || parsedMaterials.length === 0}
                onClick={() => void runTask(() => api.extractRequirements(project.id), '需求整理')}
              >
                <IconSpark width={14} height={14} />
                {busy ? '整理中…' : '重新整理需求'}
              </button>
              <button type="button" className="link-btn" onClick={() => setShowAdd((prev) => !prev)}>
                <IconPlus width={13} height={13} />
                手动新增
              </button>
            </div>
          </header>

          {showAdd ? (
            <div className="create-form">
              <div className="create-form__grid">
                <label className="field">
                  <span className="field__label">需求标题 *</span>
                  <input
                    className="textarea"
                    value={newRequirement.title}
                    onChange={(event) => setNewRequirement({ ...newRequirement, title: event.target.value })}
                  />
                </label>
                <label className="field">
                  <span className="field__label">分类</span>
                  <select
                    className="textarea"
                    value={newRequirement.category}
                    onChange={(event) => setNewRequirement({ ...newRequirement, category: event.target.value })}
                  >
                    {CATEGORIES.map((category) => (
                      <option key={category}>{category}</option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span className="field__label">优先级</span>
                  <select
                    className="textarea"
                    value={newRequirement.priority}
                    onChange={(event) =>
                      setNewRequirement({ ...newRequirement, priority: event.target.value as Priority })
                    }
                  >
                    <option value="high">高</option>
                    <option value="medium">中</option>
                    <option value="low">低</option>
                  </select>
                </label>
              </div>
              <label className="field">
                <span className="field__label">需求描述</span>
                <textarea
                  className="textarea"
                  rows={2}
                  value={newRequirement.detail}
                  onChange={(event) => setNewRequirement({ ...newRequirement, detail: event.target.value })}
                />
              </label>
              <div className="mode-panel__actions">
                <button
                  type="button"
                  className="btn btn--primary btn--sm"
                  disabled={!newRequirement.title.trim()}
                  onClick={() => void addRequirement()}
                >
                  保存
                </button>
                <span className="hint hint--inline">手动新增的直接算作已确认。</span>
              </div>
            </div>
          ) : null}

          {requirements.length === 0 ? (
            <p className="empty-inline">
              还没有需求。把材料交给右侧 Agent 后 Fitwise 会自动整理；也可以点上面的「手动新增」先记一条。
            </p>
          ) : (
            <ul className="req-brief">
              {orderedRequirements.map((item, index) =>
                renderRequirement(
                  item,
                  item.status === 'confirmed' ? 'confirmed' : 'draft',
                  // 第一条草稿留个锚点：结论条上的「待确认」点一下就落到这里
                  index === 0 && inferred.length ? 'requirements-draft' : undefined,
                ),
              )}
            </ul>
          )}
        </section>
      </div>

      {/* 待澄清问题：原来挂在顶部「还差什么」，现在下沉成一个分区，三页骨架才一致；
          「待确认」只留给 AI 推断的需求，同一页不再一个词说两件事 */}
      <section className="section-open" id="pending-questions">
        <header className="section-open__head">
          <div className="section-open__titleline">
            <h3>
              待澄清问题
              <span className="fact-group__count">{questions.length}</span>
            </h3>
            <HelpTip text="材料没写清的点都放在这里。标「影响判断」的会直接改变能力结论，其余只影响承诺口径。前面的标签是「问谁」：客户就是问客户，内部就是自己人先确认。" />
          </div>
        </header>
        {questions.length === 0 ? (
          <p className="empty-inline">暂时没有需要澄清的问题。</p>
        ) : (
          <ul className="gap-lines">
            {questions.map((item) => {
              const insight = summarizeOpenQuestion(item);
              return (
                <li key={item.question}>
                  <span className="gap-lines__tag">{item.owner || '客户'}</span>
                  <span className="gap-lines__text">{item.question}</span>
                  {/* 标出这条到底影响什么：影响判断的会改结论，影响承诺的只改口径 */}
                  <span
                    className={`gap-lines__impact${
                      insight.affectsJudgement ? ' gap-lines__impact--judge' : ''
                    }`}
                    title={
                      insight.affectsJudgement
                        ? '这条不确认，能力结论就不成立'
                        : '这条不确认，只影响承诺与交付口径'
                    }
                  >
                    {insight.affectsJudgement ? '影响判断' : '影响承诺'}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
