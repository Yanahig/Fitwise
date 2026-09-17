import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import { installDiagnostics } from './api/telemetry';
import './styles/tokens.css';
import './styles/base.css';
import './styles/layout.css';
import './styles/components.css';
import './styles/responsive.css';
import './styles/workspace.css';

const container = document.getElementById('root');
if (!container) {
  throw new Error('未找到 #root 容器');
}

// 诊断钩子要在渲染之前装好：启动信息、前端崩了、页面切换都要能记上
installDiagnostics();

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
