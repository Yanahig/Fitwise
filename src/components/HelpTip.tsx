import { useEffect, useRef, useState } from 'react';

/**
 * 信息按需展示：页面上默认只留结论，长的解释收在「?」里，点了才出现。
 *
 * 判断标准：这句话如果只是「解释我们为什么这么设计」，就不该常驻在页面上；
 * 如果它会改变用户的下一步动作，才值得直接写在页面上。
 */
export function HelpTip({ text, label = '这条信息怎么理解' }: { text: string; label?: string }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (!box.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', close);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  return (
    <span className="help-tip" ref={box}>
      <button
        type="button"
        className="help-tip__dot"
        aria-label={label}
        aria-expanded={open}
        onClick={() => setOpen((prev) => !prev)}
      >
        ?
      </button>
      {open ? (
        <span className="help-tip__body" role="note">
          {text}
        </span>
      ) : null}
    </span>
  );
}
