import { useCallback, useEffect, useState } from 'react';
import { trackPageView } from '../api/telemetry';

export interface Route {
  path: string;
  segments: string[];
  navigate: (to: string) => void;
}

function parse(hash: string): string {
  const path = hash.replace(/^#/, '');
  return path.startsWith('/') ? path : `/${path}`;
}

export function useHashRoute() {
  const [path, setPath] = useState<string>(() => parse(window.location.hash));

  useEffect(() => {
    const onChange = () => {
      setPath(parse(window.location.hash));
      window.scrollTo({ top: 0, behavior: 'smooth' });
    };
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, []);

  const navigate = useCallback((to: string) => {
    const target = to.startsWith('/') ? to : `/${to}`;
    if (window.location.hash === `#${target}`) {
      window.scrollTo({ top: 0, behavior: 'smooth' });
      return;
    }
    window.location.hash = target;
  }, []);

  const segments = path.split('/').filter(Boolean);

  // 每次换页记一条：去了哪、从哪来、上一页停了多久（诊断"卡在哪一步"最有用的一条）
  useEffect(() => {
    trackPageView(path);
  }, [path]);

  return { path, segments, navigate };
}
