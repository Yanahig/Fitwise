import { useState } from 'react';
import type { Activity } from '../api/types';
import {
  IconAlert,
  IconCase,
  IconCheck,
  IconCompass,
  IconDocSearch,
  IconEvidence,
  IconFile,
  IconNote,
  IconSpark,
} from './icons';

type Tone = 'blue' | 'violet' | 'green' | 'amber' | 'red' | 'gray';

interface ActivityMeta {
  label: string;
  tone: Tone;
  Icon: (props: { width?: number; height?: number }) => JSX.Element;
}

/** 活动类型 → 图标与配色，让时间线一眼能分出「材料/需求/判断/方案」 */
const ACTIVITY_META: Record<string, ActivityMeta> = {
  customer_created: { label: '客户', tone: 'blue', Icon: IconDocSearch },
  customer_updated: { label: '客户', tone: 'blue', Icon: IconDocSearch },
  project_created: { label: '项目', tone: 'blue', Icon: IconCompass },
  project_updated: { label: '项目', tone: 'blue', Icon: IconCompass },
  note: { label: '沟通记录', tone: 'gray', Icon: IconNote },
  material_uploaded: { label: '材料', tone: 'gray', Icon: IconFile },
  material_parsed: { label: '材料已读完', tone: 'green', Icon: IconCheck },
  material_parse_failed: { label: '材料', tone: 'red', Icon: IconAlert },
  requirements_extracted: { label: '需求整理', tone: 'violet', Icon: IconSpark },
  requirements_confirmed: { label: '需求确认', tone: 'green', Icon: IconCheck },
  requirement_created: { label: '需求', tone: 'violet', Icon: IconSpark },
  requirement_updated: { label: '需求', tone: 'violet', Icon: IconSpark },
  matches_completed: { label: '能力判断', tone: 'blue', Icon: IconEvidence },
  match_reviewed: { label: '人工修正', tone: 'amber', Icon: IconAlert },
  solution_generated: { label: '解决路径', tone: 'blue', Icon: IconCompass },
};

const FALLBACK_META: ActivityMeta = { label: '记录', tone: 'gray', Icon: IconCase };

function dayKey(iso: string): string {
  return iso.slice(0, 10);
}

function dayLabel(iso: string): string {
  const date = new Date(iso);
  const today = new Date();
  const yesterday = new Date(today.getTime() - 86_400_000);
  const sameDay = (a: Date, b: Date) => a.toDateString() === b.toDateString();
  if (sameDay(date, today)) return '今天';
  if (sameDay(date, yesterday)) return '昨天';
  return date.toLocaleDateString('zh-CN', { month: 'long', day: 'numeric' });
}

function timeLabel(iso: string): string {
  return new Date(iso).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
}

interface Group {
  key: string;
  label: string;
  items: Activity[];
}

function groupByDay(activities: Activity[]): Group[] {
  const groups: Group[] = [];
  for (const activity of activities) {
    const key = dayKey(activity.created_at);
    const last = groups[groups.length - 1];
    if (last && last.key === key) {
      last.items.push(activity);
    } else {
      groups.push({ key, label: dayLabel(activity.created_at), items: [activity] });
    }
  }
  return groups;
}

/** 客户档案与项目里统一使用的时间线：按天分组、按类型着色、可展开长文本 */
export function ActivityTimeline({
  activities,
  onOpenProject,
  emptyText = '还没有记录',
}: {
  activities: Activity[];
  onOpenProject?: (projectId: number) => void;
  emptyText?: string;
}) {
  const [expanded, setExpanded] = useState<string[]>([]);

  if (activities.length === 0) {
    return <p className="empty-inline">{emptyText}</p>;
  }

  const toggle = (key: string) =>
    setExpanded((prev) => (prev.includes(key) ? prev.filter((item) => item !== key) : [...prev, key]));

  return (
    <div className="timeline-v2">
      {groupByDay(activities).map((group) => (
        <section key={group.key} className="timeline-v2__group">
          <h4 className="timeline-v2__date">
            {group.label}
            <span className="timeline-v2__count">{group.items.length} 条</span>
          </h4>
          <ol className="timeline-v2__list">
            {group.items.map((activity) => {
              const meta = ACTIVITY_META[activity.type] ?? FALLBACK_META;
              const key = String(activity.id);
              const isLong = activity.summary.length > 110;
              const isOpen = expanded.includes(key);
              const text = isLong && !isOpen ? `${activity.summary.slice(0, 110)}…` : activity.summary;
              const { Icon } = meta;
              return (
                <li key={key} className="timeline-v2__item">
                  <span className={`timeline-v2__marker timeline-v2__marker--${meta.tone}`} aria-hidden="true">
                    <Icon width={12} height={12} />
                  </span>
                  <div className="timeline-v2__body">
                    <div className="timeline-v2__head">
                      <span className={`timeline-v2__tag timeline-v2__tag--${meta.tone}`}>{meta.label}</span>
                      <span className="timeline-v2__time">{timeLabel(activity.created_at)}</span>
                      <span className="timeline-v2__actor">{activity.actor || '系统'}</span>
                      {activity.project_id && onOpenProject ? (
                        <button
                          type="button"
                          className="link-btn timeline-v2__open"
                          onClick={() => onOpenProject(activity.project_id as number)}
                        >
                          进入项目
                        </button>
                      ) : null}
                    </div>
                    <p className="timeline-v2__text">
                      {text}
                      {isLong ? (
                        <button type="button" className="link-btn timeline-v2__toggle" onClick={() => toggle(key)}>
                          {isOpen ? '收起' : '展开'}
                        </button>
                      ) : null}
                    </p>
                  </div>
                </li>
              );
            })}
          </ol>
        </section>
      ))}
    </div>
  );
}
