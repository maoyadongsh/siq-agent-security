// Browser check for the final embedded Linux console. The caller owns an
// isolated daemon, pairing code and Playwright package path.
const endpoint = process.env.SIQ_SCOPE_ENDPOINT;
const pairCode = process.env.SIQ_SCOPE_PAIR;
const playwrightModule = process.env.SIQ_SCOPE_PLAYWRIGHT_MODULE;
if (!endpoint || !pairCode || !playwrightModule) throw new Error('scope browser environment is incomplete');
const { chromium } = await import(playwrightModule);
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 }, locale: 'zh-CN' });
  await page.goto(`${endpoint}/`, { waitUntil: 'domcontentloaded' });
  const input = page.locator('input[autocomplete="one-time-code"]');
  await input.waitFor({ state: 'visible', timeout: 30000 });
  await input.fill(pairCode);
  await page.getByRole('button', { name: '建立管理会话' }).click();
  await page.locator('aside[aria-label="siq-agent-security 本地导航"]')
    .waitFor({ state: 'visible', timeout: 30000 });
  for (const route of ['/settings', '/bindings']) {
    await page.goto(`${endpoint}${route}`, { waitUntil: 'domcontentloaded' });
    if (await page.getByRole('row').filter({ hasText: 'CodeBuddy' }).count()) {
      throw new Error(`${route} still exposes a retired platform`);
    }
    for (const platform of ['WorkBuddy']) {
      const row = page.getByRole('row').filter({ hasText: platform }).first();
      await row.waitFor({ state: 'visible', timeout: 30000 });
      const content = await row.innerText();
      if (!content.includes('不支持') || !content.includes('当前范围不支持新接入')) {
        throw new Error(`${route} does not disclose ${platform} product scope: ${content.slice(0, 300)}`);
      }
      if (await row.getByRole('button', { name: /安装/ }).count()) {
        throw new Error(`${route} offers ${platform} installation`);
      }
    }
  }
  console.log(JSON.stringify({ settings: true, bindings: true, platforms: ['WorkBuddy'], install_buttons: 0 }));
} finally {
  await browser.close();
}
