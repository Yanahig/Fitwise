import { useEffect, useState } from 'react';
import { IconFile } from './icons';

/** 这次拖拽里有没有文件（拖选中的文字、拖链接都不算） */
function hasFiles(event: DragEvent): boolean {
  return Array.from(event.dataTransfer?.types ?? []).includes('Files');
}

/**
 * 整页接收文件拖拽：返回 dragging，用来画投放提示。
 *
 * 三个阶段（dragenter / dragover / drop）都必须 preventDefault —— 浏览器默认行为是
 * "打开这个文件"，不拦下来拖进去的 PDF 会把整个页面顶掉。
 *
 * 用 depth 计数是因为 dragenter / dragleave 会在子元素之间反复触发，
 * 只看 dragleave 会让提示层一闪一闪。
 */
export function useFileDrop(onFiles: (files: File[]) => void): boolean {
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    let depth = 0;
    const onEnter = (event: DragEvent) => {
      if (!hasFiles(event)) return;
      event.preventDefault();
      depth += 1;
      setDragging(true);
    };
    const onOver = (event: DragEvent) => {
      if (!hasFiles(event)) return;
      event.preventDefault();
      if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy';
    };
    const onLeave = (event: DragEvent) => {
      if (!hasFiles(event)) return;
      depth = Math.max(0, depth - 1);
      if (!depth) setDragging(false);
    };
    const onDrop = (event: DragEvent) => {
      if (!hasFiles(event)) return;
      event.preventDefault();
      depth = 0;
      setDragging(false);
      const files = Array.from(event.dataTransfer?.files ?? []);
      if (files.length) onFiles(files);
    };
    window.addEventListener('dragenter', onEnter);
    window.addEventListener('dragover', onOver);
    window.addEventListener('dragleave', onLeave);
    window.addEventListener('drop', onDrop);
    return () => {
      window.removeEventListener('dragenter', onEnter);
      window.removeEventListener('dragover', onOver);
      window.removeEventListener('dragleave', onLeave);
      window.removeEventListener('drop', onDrop);
    };
  }, [onFiles]);

  return dragging;
}

/** 拖拽时的整页投放提示：一句话说清"松手之后会发生什么" */
export function FileDropOverlay({ hint }: { hint: string }) {
  return (
    <div className="file-drop">
      <div className="file-drop__inner">
        <IconFile width={18} height={18} />
        {hint}
      </div>
    </div>
  );
}
