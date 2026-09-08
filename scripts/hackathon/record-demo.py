#!/usr/bin/env python3
"""Record real browser interactions; provider switches and controls stay labeled."""

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--real-state', type=Path, required=True)
    parser.add_argument('--fixture-state', type=Path, required=True)
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--source-sha', required=True)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=False)
    states = [json.loads((path/'service.json').read_text()) for path in (args.real_state, args.fixture_state)]
    if [s['mode'] for s in states] != ['demo', 'test']:
        raise ValueError('real inference and explicit fixture services are required')
    events, errors = [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width':1440,'height':1000},
                                      record_video_dir=str(args.out_dir), record_video_size={'width':1440,'height':1000})
        def pair(state):
            response = context.request.post(state['endpoint']+'/hackathon/v1/pairing/renew', data={},
                headers={'Authorization':'Bearer '+state['token'],'X-SIQ-Demo':'1'})
            if response.status != 200:
                raise ValueError('operator pairing renewal failed')
            code = response.json()['pairing_code']
            paired = context.request.post(state['endpoint']+'/hackathon/v1/pair', data={'code':code}, headers={'X-SIQ-Demo':'1'})
            if paired.status != 200:
                raise ValueError('operator pairing failed')
            snapshot = context.request.get(state['endpoint']+'/hackathon/v1/tasks').json()
            if snapshot['source_sha'] != args.source_sha or snapshot['source_dirty'] is not False:
                raise ValueError('video requires the exact clean candidate identity')
            return snapshot
        pair(states[0])
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(states[0]['endpoint']+'/demo')
        page.get_by_label('场景', exact=True).wait_for()
        started = time.monotonic()
        def caption(title, subtitle):
            # Captions add explanatory metadata; they never modify application
            # decisions, task states, effects, provider names or rendered results.
            page.evaluate('''([title, subtitle]) => {
              let box = document.getElementById('recording-caption');
              if (!box) { box = document.createElement('aside'); box.id='recording-caption'; document.body.appendChild(box);
                Object.assign(box.style,{position:'fixed',bottom:'12px',left:'24px',right:'24px',padding:'14px 20px',
                  background:'#102f3f',color:'white',zIndex:'999',borderRadius:'8px',fontFamily:'sans-serif',fontSize:'17px'}); }
              box.replaceChildren(); const strong=document.createElement('strong'); strong.textContent=title;
              const note=document.createElement('div'); note.textContent=subtitle; note.style.fontSize='13px';
              box.append(strong,note);
            }''', [title, subtitle+' · Source '+args.source_sha])
        def until(seconds):
            while time.monotonic()-started < seconds:
                page.wait_for_timeout(min(1000,int((seconds-(time.monotonic()-started))*1000)+1))
        def run(state, scenario, expected):
            page.get_by_label('场景', exact=True).select_option(scenario)
            with page.expect_response(lambda response: response.request.method == 'POST'
                                      and response.url == state['endpoint']+'/hackathon/v1/tasks') as submitted:
                page.get_by_role('button', name='开始任务', exact=True).click()
            identity=submitted.value.json()['id']
            # Adjacent scenarios may have the same status. Wait for this exact
            # submitted task so a previous blocked task cannot satisfy the gate.
            page.wait_for_function('''([identity, expected]) => {
              const select = document.querySelector('select[aria-label="查看任务"]');
              return select?.value === identity && select.selectedOptions[0]?.textContent.includes(' · '+expected+' · ');
            }''',arg=[identity,expected],timeout=90000)
            current=context.request.get(state['endpoint']+'/hackathon/v1/tasks/'+identity).json()
            events.append({'scenario':scenario,'task_id':current['id'],'provider':current['provider'],
                           'task_status':current['task']['status'],'selected_skills':current['task']['selected_skills'],
                           'model_calls':current.get('model_calls',[]),'at_seconds':round(time.monotonic()-started,2)})
        caption('Skills give agents capabilities. Who authorizes the consequences?',
                'Real runtime demonstration · Waiting time is shown · No synthetic decision edits')
        until(15)
        caption('StepFun plans. DGX Spark analyzes locally. SIQ authorizes.', 'Actual StepFun planning + Ornith local inference')
        run(states[0],'research-only','researched')
        page.locator('[aria-label="Selected Skills"]').scroll_into_view_if_needed()
        until(40)
        caption('Normal task: review a repository, save a report, deliver to Alice.', 'Actual model inference · Controlled source and message receiver')
        run(states[0],'normal','verified')
        page.get_by_text('实际完成了什么',exact=True).scroll_into_view_if_needed()
        until(80)
        pair(states[1])
        page.goto(states[1]['endpoint']+'/demo')
        page.get_by_label('场景',exact=True).wait_for()
        caption('Controlled attack proposals · FixtureProvider, real SIQ and tools', 'The fixture label is explicit; no StepFun attack-success claim')
        # This actual control supplies the trusted-directory ALLOW comparison.
        run(states[1],'normal','verified')
        caption('MCP proposes attacker@evil.example. SIQ denies the untrusted origin.', 'FixtureProvider attack proposal · Actual runtime DENY')
        run(states[1],'mcp-attack','blocked')
        page.locator('[data-provenance="MCP"]').scroll_into_view_if_needed()
        until(110)
        caption('Same value, different provenance.', 'Actual trusted-directory ALLOW versus MCP DENY')
        run(states[1],'same-value','blocked')
        page.locator('[data-comparison="same-value"]').scroll_into_view_if_needed()
        until(135)
        caption('A tool can report success. It cannot prove the real effect.', 'Controlled fake-success tool · Actual missing receiver event')
        run(states[1],'fake-success','incomplete')
        page.locator('.demo-effect-summary').scroll_into_view_if_needed()
        until(155)
        caption('The model proposes. SIQ authorizes. Evidence determines completion.',
                'Small samples · Same-UID is not OS isolation · Scoped file/HTTP effect verification')
        until(170)
        duration=time.monotonic()-started
        video=page.video
        context.close()
        path=Path(video.path())
        final=args.out_dir/'siq-v4-demo.webm'
        path.rename(final)
        browser.close()
    record={'schema_version':'hackathon-video/v1','recorded_at':datetime.now(timezone.utc).isoformat(),
            'source_sha':args.source_sha,'duration_seconds':round(duration,2),'file':str(final),
            'sha256':hashlib.sha256(final.read_bytes()).hexdigest(),'events':events,'page_errors':errors,
            'captions_only':True,'audio':'none','speed_adjustment':False,'cuts':False,
            'provider_disclosure':'Real StepFun/Ornith for research/normal; explicitly labeled FixtureProvider for deterministic attacks.',
            'uploaded':False,'passed':not errors and 120 <= duration <= 180}
    (args.out_dir/'video-record.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({'file':str(final),'duration_seconds':record['duration_seconds'],'passed':record['passed']}))
    return 0 if record['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
