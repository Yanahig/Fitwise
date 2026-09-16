import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
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

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
