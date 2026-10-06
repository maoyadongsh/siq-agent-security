"""CLI-first real embedded UI journey; no application API interception or mock."""
import json
import os
import re
import secrets
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from common import sha256, write_json

WRAPPER = '/home/maoyd/.codex/skills/playwright/scripts/playwright_cli.sh'
CHROME = '/home/maoyd/.cache/ms-playwright/chromium-1246/chrome-linux-arm64/chrome'


def ref(snapshot, label, after=None):
    if after is not None:
        if after not in snapshot:
            raise ValueError('fresh snapshot lacks expected instance')
        snapshot = snapshot.split(after, 1)[1]
    for line in snapshot.splitlines():
        if label in line:
            match = re.search(r'\[ref=((?:f\d+)?e\d+)\]', line)
            if match:
                return match[1]
    raise ValueError('fresh snapshot lacks expected control: ' + label)


def run(h, out):
    root = out / 'output/playwright'
    root.mkdir(parents=True)
    session = 'personalcheck' + secrets.token_hex(6)
    config = root / 'cli.config.json'
    write_json(config, {'browser': {'launchOptions': {'headless': True, 'executablePath': CHROME, 'chromiumSandbox': False},
                                    'contextOptions': {'viewport': {'width': 1440, 'height': 1000}, 'locale': 'zh-CN'}}})
    # Only the pairing code is transferred. No recovery/provider secret is exposed to the browser.
    paired = h.command([str(h.binary), 'pair', '--port', str(urlparse(h.endpoint).port)], timeout=10)
    code = re.search(r'\b[0-9a-f]{4}(?:-[0-9a-f]{4}){3}\b', paired)
    if not code:
        raise ValueError('browser pairing unavailable')
    pairing = {'code': code.group()}
    known_secrets = [code.group(), h.admin]
    observations = {'stages': {}, 'actions': [], 'cleanup': {}, 'scope': 'real candidate embedded UI, real Hermes product selfcheck, author captured DOM/API'}

    class Input(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            good = self.path == '/pairing-input' and not self.headers.get('Origin') and 'code' in pairing
            raw = json.dumps({'code': pairing.pop('code')} if good else {}).encode()
            self.send_response(200 if good else 410)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Input)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    input_url = f'http://127.0.0.1:{server.server_port}/pairing-input'
    env = {k: v for k, v in os.environ.items() if k in ('PATH', 'HOME', 'TMPDIR', 'LANG', 'LC_ALL')}
    env.update(CI='1', NO_UPDATE_NOTIFIER='1', npm_config_offline='true')
    index = 0

    def cli(*args):
        nonlocal index
        index += 1
        response = subprocess.run(['bash', WRAPPER, '--session=' + session, *args], cwd=root, env=env,
                                  capture_output=True, text=True, timeout=45, check=False)
        text = response.stdout + response.stderr
        for secret in known_secrets:
            if secret:
                text = text.replace(secret, '[REDACTED]')
        (root / f'command-{index:03d}.txt').write_text(text)
        observations['actions'].append({'sequence': index, 'command': args[0], 'exit_code': response.returncode})
        if response.returncode or '### Error' in text:
            raise ValueError('browser command failed; sanitized log retained')
        return text

    def evaluate(code):
        output = cli('run-code', code)
        return json.loads(output.split('### Result', 1)[1].split('###', 1)[0].strip())

    def snapshot(name, required=None, timeout=20):
        deadline = time.monotonic() + timeout
        while True:
            output = cli('snapshot')
            inline = re.search(r'```yaml\n(.*?)\n```', output, re.DOTALL)
            link = re.search(r'\[Snapshot\]\(([^)]+)\)', output)
            text = inline[1] if inline else (root / link[1]).read_text() if link else ''
            for secret in known_secrets:
                if secret:
                    text = text.replace(secret, '[REDACTED]')
            (root / (name + '.yaml')).write_text(text)
            if required is None or required in text:
                return text
            if time.monotonic() > deadline:
                raise TimeoutError('expected page state not observed: ' + name)
            time.sleep(0.1)

    def checkpoint():
        observations['browser'] = evaluate("async page => {const p=page.context().__siqProbe; await Promise.race([Promise.allSettled([...p.pending]),new Promise(r=>setTimeout(r,4000))]); return {responses:p.responses,consoles:p.consoles,pending:p.pending.size};}")
        write_json(out / 'browser-observations.json', observations, exclusive=False)

    def stage(name, required, *, timeout=20, screenshot=True):
        text = snapshot(name, required, timeout)
        row = evaluate("async page => ({url:page.url(),text:await page.locator('main').innerText(),dialog:await page.locator('[role=dialog]').count()?await page.locator('[role=dialog]').innerText():null,check:await page.locator('[data-runtime-check-id]').count()?await page.locator('[data-runtime-check-id]').evaluate(el=>({id:el.dataset.runtimeCheckId,status:el.dataset.runtimeCheckStatus})):null})")
        observations['stages'][name] = row
        if screenshot:
            cli('screenshot', '--filename=' + name + '.png')
        checkpoint()
        return text

    profile = Path(h.env['HERMES_HOME'])
    host_config = profile / 'config.yaml'
    installed = None
    try:
        cli('open', h.endpoint + '/overview', '--config', str(config))
        cli('run-code', '--filename', str(Path(__file__).with_name('browser_management_probe.js')))
        evaluate("async page=>{page.on('pageerror',()=>page.context().__siqProbe.consoles.push({type:'pageerror'}));return {page_errors_observed:true};}")
        snap = snapshot('unpaired', '手动配对')
        cli('click', ref(snap, '手动配对 / 旧版本连接'))
        snap = snapshot('manual-pairing', 'textbox "配对码"')
        field = ref(snap, 'textbox "配对码"')
        evaluate('async page => {const r=await fetch(' + json.dumps(input_url) + ');const v=await r.json();page.context().__siqProbe.secrets.push(v.code);await page.locator(' + json.dumps('aria-ref=' + field) + ').fill(v.code);return {filled:true};}')
        cli('click', ref(snap, 'button "建立管理会话"'))
        snap = snapshot('paired', '管理已发现实例的接入')
        cli('click', ref(snap, 'generic "管理已发现实例的接入"'))
        snap = snapshot('instances-expanded', 'Hermes · work')
        cli('click', ref(snap, 'button "接入此实例"', after='Hermes · work'))
        snap = snapshot('install-preview', 'combobox "接入方式"')
        cli('select', ref(snap, 'combobox "接入方式"'), 'connection')
        snap = snapshot('install-connection', 'button "确认应用"')
        cli('click', ref(snap, 'button "确认应用"'))
        stage('installed', '验证刚接入的实例')
        observations['installed_instances'] = h.api('/v1/adapter/instances?platform=hermes')
        observations['grants_installed'] = h.api('/v1/grants')
        active = next(i for i in observations['installed_instances']['instances'] if i['active'])
        observations['instance_id'] = active['instance_id']
        installed = host_config.read_bytes()
        observations['config_installed_sha256'] = sha256(host_config)
        snap = snapshot('before-selfcheck', '验证刚接入的实例')
        cli('click', ref(snap, 'button "验证刚接入的实例"'))
        stage('selfcheck-preview', '将执行的检查')
        observations['grants_preview'] = h.api('/v1/grants')
        snap = snapshot('before-confirm', 'textbox "确认人"')
        cli('fill', ref(snap, 'textbox "确认人"'), 'evaluation-browser-operator')
        snap = snapshot('before-start', 'button "确认并开始自检"')
        cli('click', ref(snap, 'button "确认并开始自检"'))
        snap = snapshot('running', '关闭（后台继续）')
        observations['running_check'] = evaluate("async page=>await page.locator('[data-runtime-check-id]').evaluate(el=>({id:el.dataset.runtimeCheckId,status:el.dataset.runtimeCheckStatus}))")
        cli('click', ref(snap, 'button "关闭（后台继续）"'))
        cli('reload')
        snap = snapshot('reloaded-collapsed', '管理已发现实例的接入')
        cli('click', ref(snap, 'generic "管理已发现实例的接入"'))
        snap = snapshot('reloaded', 'button "验证连接"')
        cli('click', ref(snap, 'button "验证连接"'))
        stage('selfcheck-passed', '本次自检通过', timeout=145)
        check_id = observations['stages']['selfcheck-passed']['check']['id']
        observations['passed'] = h.api('/v1/runtime-checks/' + check_id)
        observations['grants_passed'] = h.api('/v1/grants')
        observations['config_passed_sha256'] = sha256(host_config)
        observations['activity_reference'] = h.api('/v1/runtime-checks/' + check_id + '/activity')
        snap = snapshot('before-activity', '查看本次运行记录')
        cli('click', ref(snap, 'button "查看本次运行记录"'))
        stage('activity-detail', '未设置结果核验')
        reference = observations['activity_reference']
        observations['activity_detail'] = h.api('/v1/task-activities/' + reference['activity']['activity_id'] + '?snapshot=' + reference['snapshot'])
        observations['security_view'] = h.api('/v1/task-activities/' + reference['activity']['activity_id'] + '/security-view?snapshot=' + reference['snapshot'])
        cli('reload')
        snap = snapshot('detail-reloaded', '返回运行记录')
        cli('click', ref(snap, 'link "返回运行记录"'))
        stage('activity-list', '查看活动记录')
        observations['filters'] = evaluate("async page=>({task:await page.getByLabel('任务',{exact:true}).inputValue(),agent:await page.getByLabel('智能体',{exact:true}).inputValue(),session:await page.getByLabel('会话',{exact:true}).inputValue(),links:await page.getByRole('link',{name:'查看活动记录',exact:true}).count()})")
        cli('reload')
        stage('activity-list-reloaded', '查看活动记录')
        cli('resize', '390', '844')
        stage('mobile-activity', '查看活动记录')
        observations['mobile'] = evaluate("async page=>await page.getByRole('form',{name:'筛选任务活动'}).evaluate(el=>({fits:el.scrollWidth<=el.clientWidth+1&&el.getBoundingClientRect().right<=innerWidth,width:innerWidth}))")
        cli('resize', '1440', '1000')
        cli('goto', h.endpoint + '/overview')
        snap = snapshot('overview-collapsed', '管理已发现实例的接入')
        cli('click', ref(snap, 'generic "管理已发现实例的接入"'))
        snap = snapshot('back-overview', 'button "验证连接"')
        cli('click', ref(snap, 'button "验证连接"'))
        snap = snapshot('before-drift', '本次自检通过')
        host_config.write_bytes(installed + b'\n# browser evaluation drift\n')
        cli('click', ref(snap, 'button "重新预览"'))
        stage('invalidated', '自检结果已失效')
        observations['invalidated'] = h.api('/v1/runtime-checks/' + check_id)
        observations['drift_start_disabled'] = evaluate("async page=>await page.getByRole('button',{name:'确认并开始自检',exact:true}).isDisabled()")
        host_config.write_bytes(installed)
        snap = snapshot('before-restored-preview', '重新预览')
        cli('click', ref(snap, 'button "重新预览"'))
        stage('restored-invalidated', '自检结果已失效')
        observations['restored'] = h.api('/v1/runtime-checks/' + check_id)
        snap = snapshot('before-second-start', 'button "确认并开始自检"')
        cli('click', ref(snap, 'button "确认并开始自检"'))
        snap = snapshot('second-running', 'button "取消自检"')
        observations['cancel_target'] = evaluate("async page=>await page.locator('[data-runtime-check-id]').getAttribute('data-runtime-check-id')")
        cli('click', ref(snap, 'button "取消自检"'))
        stage('cancelled', '自检已取消', timeout=30)
        observations['cancelled'] = h.api('/v1/runtime-checks/' + observations['cancel_target'])
        observations['grants_cancelled'] = h.api('/v1/grants')
        observations['materials_after_cancel'] = [f.name for f in (h.state / 'runtime-check-materials').iterdir()]
        snap = snapshot('before-close', 'button "关闭"')
        cli('click', ref(snap, 'button "关闭"'))
        snap = snapshot('before-uninstall', '管理此实例')
        cli('click', ref(snap, 'button "管理此实例"', after='Hermes · work'))
        snap = snapshot('manage-instance', 'combobox "操作"')
        cli('select', ref(snap, 'combobox "操作"'), 'uninstall')
        snap = snapshot('uninstall-preview', 'button "确认应用"')
        cli('click', ref(snap, 'button "确认应用"'))
        evaluate("async page=>{await page.locator('.environment-connection').filter({hasText:'Hermes · work'}).getByRole('button',{name:'接入此实例',exact:true}).waitFor({state:'visible',timeout:20000});return {active_instance_uninstalled_visible:true};}")
        stage('uninstalled', '接入此实例')
        observations['plugin_removed'] = not (profile / 'plugins/siq-agent-security').exists()
        observations['default_profile_preserved'] = (h.root / 'hermes/config.yaml').read_text() == 'fixture_default: unchanged\n'
        observations['storage'] = evaluate("async page=>{const p=page.context().__siqProbe;return await page.evaluate(secrets=>({credential_hits:[...Object.values(localStorage),...Object.values(sessionStorage)].filter(v=>secrets.some(s=>s&&v.includes(s))).length}),p.secrets);}")
    finally:
        # Restore only before uninstall; a successful uninstall's restoration is product-owned.
        if installed is not None and (profile / 'plugins/siq-agent-security').exists():
            host_config.write_bytes(installed)
        observations['records'] = {f.name: json.loads(f.read_text()) for f in sorted((h.state / 'runtime-checks').glob('*.json'))}
        observations['receipts'] = {'receipts': h.receipts(), 'public_key': h.command([str(h.binary), 'pubkey']).strip()}
        try:
            checkpoint()
        except Exception as error:  # noqa: BLE001 -- preserve partial browser state
            observations['checkpoint_error'] = type(error).__name__
        try:
            cli('close')
            observations['cleanup']['browser_closed'] = True
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            observations['cleanup']['input_server_closed'] = not thread.is_alive()
            write_json(out / 'browser-observations.json', observations, exclusive=False)
    return observations
