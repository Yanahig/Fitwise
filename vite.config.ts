import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

/**
 * 构建标识：部署脚本传 `VITE_BUILD_ID=<git 短哈希>`，本地开发就是 `local`；
 * 后面再拼上构建时间戳 —— 排查"你看到的是哪一版"最省事的一条（client_boot 事件会上报它）。
 *
 * 不用 node:child_process 去读 git：那需要 @types/node，为一个版本号加依赖不划算。
 */
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', 'VITE_');
  const buildId = `${env.VITE_BUILD_ID || 'local'}@${new Date().toISOString()}`;
  return {
    plugins: [react()],
    define: {
      __BUILD_ID__: JSON.stringify(buildId),
    },
    server: {
      port: 5173,
      strictPort: true,
      host: '127.0.0.1',
    },
    preview: {
      port: 4173,
      strictPort: true,
      host: '127.0.0.1',
    },
  };
});
