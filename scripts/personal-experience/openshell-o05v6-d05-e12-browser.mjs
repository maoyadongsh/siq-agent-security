/**
 * D05 / E12 — the real browser journey through the served product UI.
 *
 * The taskbook asks for one navigation that does 预览 -> 确认 -> 运行 -> 结果
 * through the actual UI, plus 取消、失联、旧响应、移动端、键盘. This driver
 * uses a real headless Chromium against the real daemon that leg_e12 started
 * from the D05 candidate binary; nothing here is a mock or an HTTP contract
 * test standing in for the product surface.
 *
 * One boundary has to be stated plainly, because it is a design property and
 * not a gap this driver can close: the console is deliberately READ-ONLY for
 * task execution. It has no 运行 button (the run comes from the agent-side
 * executor, POST /v1/openshell/task-executions, which needs the decision
 * credential) and no 停止 or 重新执行 button (the reservation is single-use).
 * So the browser performs 预览 -> 确认 and then READS the backend-tracked result;
 * the 运行 step is issued by the executor credential this driver holds, and the
 * browser is the only thing that renders the outcome. That is what the product
 * does; the evidence says so rather than dressing it up.
 *
 * Written output: <O05V6_OUT>/e12-browser-result.json (dir is 0700) and a
 * single JSON line on stdout prefixed __O05V6_E12__ for the Python driver.
 */
import fs from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';

const ENDPOINT = process.env.O05V6_ENDPOINT;
const TOKEN = process.env.O05V6_TOKEN;
const PAIR_CODE = process.env.O05V6_PAIR_CODE;
const EXEC_BODY_PATH = process.env.O05V6_EXEC_BODY;
const ACTION_ID = process.env.O05V6_ACTION_ID;
const CANCEL_ACTION_ID = process.env.O05V6_CANCEL_ACTION_ID;
const CANCEL_DIGEST = process.env.O05V6_CANCEL_DIGEST || '';
const OUT = process.env.O05V6_OUT;

const steps = [];
const consoleErrors = [];

function step(id, title, status, fields = {}) {
  steps.push({ id, title, status, ...fields });
  const line = `[${status}] ${id}: ${title}`;
  console.log(line);
  if (fields.detail) console.log(`        ${String(fields.detail).slice(0, 300)}`);
}

function check(cond, msg) {
  if (!cond) throw new Error(msg);
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Re-ask the backend and wait for the rendered text to satisfy `want`.
 *
 * `listButton` clicks the console's own "re-read the pending list" control:
 * the reservation only becomes visible on this page once the list is re-read,
 * so the console has to be told to ask again instead of the driver assuming
 * the page already knows.
 */
async function pollTaskView(page, want, timeoutMs, label, { listButton = null } = {}) {
  const started = Date.now();
  let last = '';
  while (Date.now() - started < timeoutMs) {
    if (listButton) {
      const list = page.getByRole('button', { name: listButton });
      if (await list.count()) await list.first().click({ timeout: 5000 }).catch(() => {});
    }
    const refresh = page.getByRole('button', { name: '重新读取后端状态' });
    if (await refresh.count()) {
      await refresh.first().click({ timeout: 5000 }).catch(() => {});
    }
    await sleep(1500);
    last = await page.locator('body').innerText().catch(() => '');
    if (want(last)) return { ok: true, waited_ms: Date.now() - started, text: last };
  }
  return { ok: false, waited_ms: Date.now() - started, text: last, label };
}

async function main() {
  for (const [name, value] of [
    ['O05V6_ENDPOINT', ENDPOINT],
    ['O05V6_TOKEN', TOKEN],
    ['O05V6_PAIR_CODE', PAIR_CODE],
    ['O05V6_EXEC_BODY', EXEC_BODY_PATH],
    ['O05V6_ACTION_ID', ACTION_ID],
    ['O05V6_CANCEL_ACTION_ID', CANCEL_ACTION_ID],
    ['O05V6_OUT', OUT],
  ]) {
    check(typeof value === 'string' && value.length > 0, `${name} is not set`);
  }
  const body = JSON.parse(fs.readFileSync(EXEC_BODY_PATH, 'utf8'));
  check(body.action_id === ACTION_ID, 'the exec body does not belong to O05V6_ACTION_ID');

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1280, height: 900 },
    locale: 'zh-CN',
  });
  const page = await context.newPage();
  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrors.push(msg.text());
  });
  page.on('pageerror', (err) => consoleErrors.push(String(err)));

  try {
    // ---------------------------------------------------------------- pair
    await page.goto(`${ENDPOINT}/`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    const pairingInput = page.locator('input[autocomplete="one-time-code"]');
    await pairingInput.waitFor({ state: 'visible', timeout: 30000 });
    const pairButton = page.getByRole('button', { name: '建立管理会话' });
    check(await pairButton.count() > 0, 'the pairing gate did not render its submit button');
    step('E12b1', 'the served UI gates on the one-time pairing code, not a pre-seeded session', 'pass');

    await pairingInput.fill(PAIR_CODE);
    await pairButton.click();
    await page.locator('aside[aria-label="siq-agent-security 本地导航"]')
      .waitFor({ state: 'visible', timeout: 30000 });
    step('E12b2', 'pairing a real one-time code opens the admin console', 'pass',
      { url: page.url() });

    // ------------------------------------------------- 预览 (preview) ---
    const detailUrl = `${ENDPOINT}/confirmations?request=${encodeURIComponent(ACTION_ID)}`;
    await page.goto(detailUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.getByRole('heading', { name: '命令执行详情' })
      .waitFor({ state: 'visible', timeout: 30000 });

    const preReservation = await page.getByText('此请求尚未预留执行', { exact: false }).count();
    check(preReservation > 0,
      'the panel did not say that an un-approved request has no task status');
    check(await page.getByText('本次批准的目标、动作与预期副作用', { exact: false }).count() > 0,
      'the intent/preview panel did not render');
    check(await page.getByText('原始命令与原始输出默认只以摘要保存', { exact: false }).count() > 0,
      'the redaction notice is missing from the preview');
    check(await page.getByText('批准只记录本次操作，不等于命令已执行', { exact: false }).count() > 0,
      'the preview does not separate approval from execution');
    const bodyBefore = await page.locator('body').innerText();
    check(!bodyBefore.includes('后端已记录执行完成'),
      'a not-yet-approved request already reports a completed execution');
    step('E12b3', '预览: approval is shown as an approval, execution as a separate fact', 'pass',
      { preview_only: true });

    // ------------------------------------------------- 确认 (confirm) ---
    const actor = page.locator('#confirmation-actor');
    await actor.fill('o05v6-e12-browser-admin');
    const reviewed = page.locator('label:has-text("我已核对本次操作和参数摘要") input[type=checkbox]');
    await reviewed.check();
    const approve = page.getByRole('button', { name: '批准本次请求' });
    await approve.click();

    const approveStatus = page.locator('p[role="status"]', { hasText: '已批准本次请求' });
    await approveStatus.waitFor({ state: 'visible', timeout: 30000 });
    const approveText = await approveStatus.first().innerText();
    step('E12b4', '确认: the browser approves this exact request and gets a receipt back', 'pass',
      { status_text: approveText.slice(0, 200) });

    // Approving here does not assume the change is visible: the console has to
    // re-read the list, and this step waits for that re-read.
    //
    // What the console can show after an approval is bounded by how the
    // product works, and that bound is why this step asserts this pair and not
    // a "reserved" state. The single-use reservation is created by the executor
    // call itself (POST /v1/openshell/task-executions), not by the approval, so
    // between 批准 and 运行 there is no reservation to render and no observable
    // 已预留一次执行 window. The honest post-approval observable is therefore
    // exactly: the request is no longer awaiting confirmation, the panel still
    // says no reservation exists, and the console claims no execution. The run
    // that follows is what turns it into a reservation-bearing task.
    const approved = await pollTaskView(
      page,
      (t) => t.includes('此请求尚未预留执行') && !t.includes('后端已记录执行完成'),
      60000,
      'approved-not-executed',
      { listButton: '刷新待办' });
    check(approved.ok,
      'the console claimed an execution before the executor was asked to run anything');

    // Read the state line off the confirmation card itself rather than the
    // page text, so "approved" is distinguished from the 已批准本次请求 flash
    // message that also contains those characters.
    const confirmCard = page.locator('div.card', {
      has: page.getByRole('heading', { name: /^确认操作：/ }),
    });
    let stateLine = '';
    if (await confirmCard.count()) {
      stateLine = (await confirmCard.first().locator('p').first()
        .innerText().catch(() => '')).trim();
    }
    check(stateLine.includes('已批准'),
      `the confirmation card did not report the approval: ${JSON.stringify(stateLine.slice(0, 200))}`);
    step('E12b5', '批准后仍未执行: the approval is recorded and the run is still a separate fact',
      'pass', { state_line: stateLine.slice(0, 200), reservation_visible: false });

    // --------------------------------------------------- 运行 (run) -----
    // Issued with the executor credential, not through the console. See the
    // file header: the console is read-only by design.
    const runResp = await fetch(`${ENDPOINT}/v1/openshell/task-executions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${TOKEN}` },
      body: JSON.stringify(body),
    });
    const runJson = await runResp.json().catch(() => ({}));
    fs.writeFileSync(path.join(OUT, 'E12b6.exec-response.json'),
      JSON.stringify(runJson, null, 2), { mode: 0o600 });
    // This route answers with the hold-execution-status/v1 envelope -- the
    // outcome and the reservation it created sit under those two keys. The
    // FLAT openshell-task-execution-status/v1 projection is what the console
    // reads from /task-executions/read, and that is the shape E12b7 asserts on
    // the page, not this one.
    check(runResp.status === 200,
      `executor HTTP ${runResp.status}: ${JSON.stringify(runJson).slice(0, 300)}`);
    const outcome = runJson.outcome || {};
    check(outcome.state === 'succeeded' && outcome.exit_code === 0,
      `executor did not succeed: state=${outcome.state} rc=${outcome.exit_code}`);
    step('E12b6', '运行: the agent-side executor ran the approved command in the sandbox', 'pass',
      { http: runResp.status, state: outcome.state, exit_code: outcome.exit_code,
        task_executed: outcome.task_executed,
        reservation_status: (runJson.reservation || {}).status,
        reservation_receipt_id: (runJson.reservation || {}).reservation_receipt_id });

    // ------------------------------------------------- 结果 (result) ----
    // The list has to be re-read again: the reservation the executor just
    // created is what turns this request into a readable task execution, and
    // the console only learns about it by asking the backend.
    const done = await pollTaskView(
      page, (t) => t.includes('后端已记录执行完成，远端退出码 0'), 120000, 'succeeded',
      { listButton: '刷新待办' });
    check(done.ok, 'the console never rendered the backend-recorded success');
    const text = done.text;
    for (const [needle, why] of [
      ['审批 / 预留 / 任务 / 回执关联', 'the approval/reservation/task/receipt linkage is missing'],
      ['命令 argv 摘要', 'the argv digest line is missing'],
      ['后端原因码', 'the backend reason code is missing'],
      ['策略版本 / 摘要', 'the policy revision/digest line is missing'],
      ['远端退出码', 'the remote exit code line is missing'],
    ]) {
      check(text.includes(needle), why);
    }
    step('E12b7', '结果: the console renders the backend-signed outcome, not a local guess', 'pass',
      { rendered_checks: 5 });

    // The result must survive a reload: it comes from the signed ledger, so a
    // fresh page load has to rebuild it from the backend.
    await page.reload({ waitUntil: 'domcontentloaded' });
    const afterReload = await pollTaskView(
      page, (t) => t.includes('后端已记录执行完成，远端退出码 0'), 60000, 'after-reload');
    step('E12b8', '结果 survives a full page reload (it is a ledger projection)',
      afterReload.ok ? 'pass' : 'fail', { waited_ms: afterReload.waited_ms });

    // ------------------------------------- 旧响应 / cross-request bleed ---
    if (CANCEL_ACTION_ID) {
      await page.goto(`${ENDPOINT}/confirmations?request=${encodeURIComponent(CANCEL_ACTION_ID)}`,
        { waitUntil: 'domcontentloaded' });
      await page.getByRole('heading', { name: '命令执行详情' })
        .waitFor({ state: 'visible', timeout: 30000 });
      await sleep(2000);
      const otherText = await page.locator('body').innerText();
      step('E12b9', '旧响应: another request never renders the previous request\'s result',
        otherText.includes('后端已记录执行完成') ? 'fail' : 'pass',
        { note: 'navigating between requests must not leave a stale backend response on screen' });

      // ------------------------------------------------ 取消 (cancel) ----
      const actor2 = page.locator('#confirmation-actor');
      await actor2.fill('o05v6-e12-browser-admin');
      const reviewed2 = page.locator('label:has-text("我已核对本次操作和参数摘要") input[type=checkbox]');
      // 键盘: toggle the acknowledgement with the space bar, not the mouse.
      await reviewed2.focus();
      await page.keyboard.press(' ');
      check(await reviewed2.isChecked(), 'space bar did not toggle the acknowledgement checkbox');
      const reject = page.getByRole('button', { name: '拒绝本次请求' });
      // 键盘: activate the refusal with Enter on a focused button.
      await reject.focus();
      await page.keyboard.press('Enter');
      const rejectStatus = page.locator('p[role="status"]', { hasText: '已拒绝本次请求' });
      await rejectStatus.waitFor({ state: 'visible', timeout: 30000 });
      step('E12b10', '取消 + 键盘: the refusal is made and activated entirely from the keyboard',
        'pass', { status_text: (await rejectStatus.first().innerText()).slice(0, 200) });
    }

    // ------------------------------------------------------ 移动端 -------
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${ENDPOINT}/overview`, { waitUntil: 'domcontentloaded' });
    const hamburger = page.getByRole('button', { name: '打开导航' });
    await hamburger.waitFor({ state: 'visible', timeout: 20000 });
    // The drawer is `visibility: hidden` until React commits the `open` class
    // (index.css @media max-width:767.98px). A one-shot isVisible() right after
    // click() samples the DOM in the same tick as the click and reads the
    // pre-commit tree; wait for the commit instead. This is still a hard
    // assertion -- if the drawer never opens, the wait times out and the leg
    // fails exactly as before.
    const drawer = page.locator('aside[aria-label="siq-agent-security 本地导航"]');
    await hamburger.click();
    let navVisible = true;
    try {
      await drawer.waitFor({ state: 'visible', timeout: 10000 });
    } catch {
      navVisible = false;
    }
    check(navVisible, 'the mobile navigation did not open');
    // Back to a desktop viewport with a fresh navigation, so the drawer that
    // was opened above is gone and the top bar is clickable again.
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto(`${ENDPOINT}/overview`, { waitUntil: 'domcontentloaded' });
    await page.locator('aside[aria-label="siq-agent-security 本地导航"]')
      .waitFor({ state: 'visible', timeout: 20000 });
    step('E12b11', '移动端: the console is usable at a phone viewport', 'pass',
      { viewport: '390x844' });

    // ------------------------------------------------------ 失联 ---------
    // 退出管理 invalidates the admin session server-side; the console must
    // fall back to the pairing gate instead of showing stale data.
    const signOut = page.getByRole('button', { name: '退出管理' });
    if (await signOut.count()) {
      await signOut.first().click();
    } else {
      await page.getByRole('button', { name: '打开导航' }).click();
      await page.getByRole('button', { name: '退出管理' }).click();
    }
    await pairingInput.waitFor({ state: 'visible', timeout: 30000 });
    const lostText = await page.locator('body').innerText();
    step('E12b12', '失联: losing the admin session returns to the pairing gate', 'pass',
      { mentions_invalid_session: lostText.includes('管理会话已失效') });
  } catch (err) {
    step('E12bX', 'browser journey aborted', 'fail', { detail: String(err && err.message || err) });
    await page.screenshot({ path: path.join(OUT, 'E12bX.failure.png') }).catch(() => {});
    throw err;
  } finally {
    await browser.close();
  }
}

let fatal = null;
try {
  await main();
} catch (err) {
  fatal = String((err && err.message) || err);
}

const failed = steps.filter((s) => s.status === 'fail');
const result = {
  endpoint: ENDPOINT,
  action_id: ACTION_ID,
  steps,
  console_errors: consoleErrors.slice(0, 20),
  failed_steps: failed.map((s) => s.id),
  fatal,
  ok: !fatal && failed.length === 0,
};
fs.mkdirSync(OUT, { recursive: true });
fs.writeFileSync(path.join(OUT, 'e12-browser-result.json'), JSON.stringify(result, null, 2),
  { mode: 0o600 });
console.log('__O05V6_E12__' + JSON.stringify(result));
process.exit(result.ok ? 0 : 1);
