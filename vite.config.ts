import path from 'path';
import { defineConfig } from 'vitest/config';
import { loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
    const env = loadEnv(mode, '.', '');
    return {
      server: {
        port: 3000,
        host: '0.0.0.0',
      },
      plugins: [react(), {
        name: 'log-to-terminal',
        configureServer(server) {
          server.middlewares.use('/__log-to-terminal', (req, res, next) => {
            if (req.method === 'POST') {
              let body = '';
              req.on('data', chunk => { body += chunk.toString(); });
              req.on('end', () => {
                try {
                  const data = JSON.parse(body);
                  const { type, message, payload, timestamp } = data;
                  const color = type === 'error' ? '\x1b[31m' : type === 'warn' ? '\x1b[33m' : type === 'success' ? '\x1b[32m' : '\x1b[36m';
                  console.log(`${color}[${timestamp}] [${type?.toUpperCase()}] ${message}\x1b[0m`);
                  if (payload && Object.keys(payload).length > 0) {
                    console.dir(payload, { depth: null, colors: true });
                  }
                } catch (e) {
                  console.error('Failed to parse log from client');
                }
                res.statusCode = 200;
                res.end();
              });
            } else {
              next();
            }
          });
        }
      }],
      define: {
        'process.env.API_KEY': JSON.stringify(env.GEMINI_API_KEY),
        'process.env.GEMINI_API_KEY': JSON.stringify(env.GEMINI_API_KEY)
      },
      resolve: {
        alias: {
          '@': path.resolve(__dirname, '.'),
        }
      },
      test: {
        environment: 'jsdom',
        setupFiles: ['./tests/setup.ts'],
        globals: true,
        css: true,
        exclude: ['node_modules/**', 'dist/**', 'backend/**']
      }
    };
});
