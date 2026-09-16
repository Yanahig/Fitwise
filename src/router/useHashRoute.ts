import { useCallback, useEffect, useState } from 'react';

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
  return { path, segments, navigate };
}
