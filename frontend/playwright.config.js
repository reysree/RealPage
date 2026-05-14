import { defineConfig, devices } from '@playwright/test'

/** Dedicated API port for e2e so tests never hit a stale manual uvicorn on :8000. */
const E2E_API_ORIGIN = 'http://127.0.0.1:8001'

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  reporter: [
    ['list'],
    ['html', { open: 'never', outputFolder: 'playwright-report' }],
  ],
  expect: {
    timeout: 120_000,
  },
  use: {
    baseURL: 'http://127.0.0.1:5173',
    screenshot: 'on',
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: [
    {
      command: `cd .. && python -m uvicorn backend.main:app --host 127.0.0.1 --port 8001`,
      url: `${E2E_API_ORIGIN}/health`,
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: 'npm run dev -- --host 127.0.0.1',
      url: 'http://127.0.0.1:5173',
      env: {
        ...process.env,
        VITE_API_BASE_URL: E2E_API_ORIGIN,
      },
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
})
