async (page) => {
  const context = page.context();
  const probe = context.__siqProbe = { responses: [], secrets: [], consoles: [], wire: [], pending: new Set() };
  const attach = async (tab) => {
    const cdp = await context.newCDPSession(tab);
    const requests = new Map();
    const get = id => { if (!requests.has(id)) { const r={request_id:id}; requests.set(id,r); probe.wire.push(r); } return requests.get(id); };
    cdp.on('Network.requestWillBeSent', e => {
      const u=new URL(e.request.url); Object.assign(get(e.requestId),{path:u.pathname,probe:u.searchParams.get('probe'),method:e.request.method});
    });
    cdp.on('Network.requestWillBeSentExtraInfo', e => {
      const h=Object.fromEntries(Object.entries(e.headers).map(([k,v])=>[k.toLowerCase(),v]));
      Object.assign(get(e.requestId),{origin:h.origin||null,fetch_site:h['sec-fetch-site']||null,cookie_present:Boolean(h.cookie),authorization_present:Boolean(h.authorization)});
    });
    cdp.on('Network.responseReceivedExtraInfo', e => { get(e.requestId).status=e.statusCode; });
    await cdp.send('Network.enable');
    tab.on('console', (message) => {
      probe.consoles.push({ type: message.type(), credential_reflection: probe.secrets.some(s => message.text().includes(s)) });
    });
    tab.on('response', (response) => {
      const request = response.request();
      const url = new URL(response.url());
      if (!url.pathname.startsWith('/v1/') && url.pathname !== '/ui-config.json') return;
      const work = (async () => {
        const bounded = promise => Promise.race([promise, new Promise(resolve => setTimeout(()=>resolve(null),2000))]);
        const headers = await bounded(request.allHeaders()) || request.headers();
        let body;
        try { body = await bounded(response.json()); if(body === null) body={body_capture_timeout:true}; } catch { body = { body_unavailable: true }; }
        if (body && typeof body.session === 'string') { probe.secrets.push(body.session); probe.access=body.session; }
        if (body && typeof body.code === 'string') probe.secrets.push(body.code);
        const issued = url.pathname === '/v1/pair' || url.pathname === '/v1/session/restore';
        let text = JSON.stringify(body);
        const reflected = !issued && probe.secrets.some(s => text.includes(s));
        for (const secret of probe.secrets) text = text.split(secret).join('[REDACTED]');
        probe.responses.push({ path: url.pathname, probe: url.searchParams.get('probe'), method: request.method(),
          status: response.status(), origin: headers.origin || null, fetch_site: headers['sec-fetch-site'] || null,
          cookie_present: Boolean(headers.cookie), authorization_present: Boolean(headers.authorization),
          body: JSON.parse(text), unexpected_credential_reflection: reflected });
      })();
      probe.pending.add(work);
      work.finally(() => probe.pending.delete(work));
    });
  };
  await Promise.all(context.pages().map(attach));
  context.on('page', attach);
  return { instrumentation: 'real browser response metadata; credentials redacted in memory' };
}
