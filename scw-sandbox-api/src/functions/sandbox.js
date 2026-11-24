const { app } = require('@azure/functions');

const TAG = 'showcase-sandbox';
const MAX_LIFETIME_MIN = 10;

function getScwConfig() {
  const zone = process.env.SCW_ZONE || 'fr-par-1';
  return {
    baseUrl: `https://api.scaleway.com/instance/v1/zones/${zone}`,
    headers: {
      'X-Auth-Token': process.env.SCW_SECRET_KEY,
      'Content-Type': 'application/json'
    },
    projectId: process.env.SCW_PROJECT_ID,
    imageId: process.env.SCW_IMAGE_ID,
    fipId: process.env.SCW_FIP_ID,
    commercialType: process.env.SCW_COMMERCIAL_TYPE || 'DEV1-S'
  };
}

function buildCloudInit() {
  return `#cloud-config
write_files:
  - path: /opt/showcase/.env
    permissions: '0600'
    owner: root:root
    content: |
      DB_PASS=${process.env.DB_PASS}
      DB_ROOT_PASS=${process.env.DB_ROOT_PASS}
      APP_KEY=${process.env.APP_KEY}
      AZURE_CLIENT_ID=${process.env.AZURE_CLIENT_ID}
      AZURE_CLIENT_SECRET=${process.env.AZURE_CLIENT_SECRET}
      AZURE_TENANT_ID=${process.env.AZURE_TENANT_ID}

runcmd:
  - [ bash, -c, "cd /opt/showcase && docker compose up -d" ]
`;
}

async function listSandboxServers(cfg) {
  const res = await fetch(`${cfg.baseUrl}/servers?tags=${TAG}`, { headers: cfg.headers });
  if (!res.ok) throw new Error(`Scaleway list error: ${res.status} ${await res.text()}`);
  const data = await res.json();
  return data.servers || [];
}

// 1. HTTP TRIGGER: StartSandbox (POST /api/StartSandbox)
app.http('StartSandbox', {
  methods: ['POST'],
  authLevel: 'anonymous',
  handler: async (request, context) => {
    try {
      const cfg = getScwConfig();
      const existing = await listSandboxServers(cfg);

      if (existing.length > 0) {
        return {
          status: 200,
          jsonBody: { status: 'already_running', serverId: existing[0].id, state: existing[0].state }
        };
      }

      // A) Vytvoření VM ze Golden Image s připojením Flexible IP
      const createRes = await fetch(`${cfg.baseUrl}/servers`, {
        method: 'POST',
        headers: cfg.headers,
        body: JSON.stringify({
          name: `bookstack-demo-${Date.now()}`,
          commercial_type: cfg.commercialType,
          image: cfg.imageId,
          project: cfg.projectId,
          public_ips: [cfg.fipId],
          dynamic_ip_required: false,
          tags: [TAG]
        })
      });
      if (!createRes.ok) throw new Error(`Create failed: ${await createRes.text()}`);
      const { server } = await createRes.json();

      // B) Injekce .env přes cloud-init user_data
      const cloudInitRes = await fetch(`${cfg.baseUrl}/servers/${server.id}/user_data/cloud-init`, {
        method: 'PATCH',
        headers: {
          'X-Auth-Token': process.env.SCW_SECRET_KEY,
          'Content-Type': 'text/plain'
        },
        body: buildCloudInit()
      });
      if (!cloudInitRes.ok) throw new Error(`Cloud-init failed: ${await cloudInitRes.text()}`);

      // C) Spuštění instance (poweron)
      const powerRes = await fetch(`${cfg.baseUrl}/servers/${server.id}/action`, {
        method: 'POST',
        headers: cfg.headers,
        body: JSON.stringify({ action: 'poweron' })
      });
      if (!powerRes.ok) throw new Error(`Poweron failed: ${await powerRes.text()}`);

      context.log(`Started sandbox VM: ${server.id}`);
      return { status: 202, jsonBody: { status: 'starting', serverId: server.id } };
    } catch (err) {
      context.error(err);
      return { status: 500, jsonBody: { error: err.message } };
    }
  }
});

// 2. HTTP TRIGGER: StatusCheck (GET /api/StatusCheck)
app.http('StatusCheck', {
  methods: ['GET'],
  authLevel: 'anonymous',
  handler: async (request, context) => {
    try {
      const cfg = getScwConfig();
      const servers = await listSandboxServers(cfg);

      if (servers.length === 0) {
        return { status: 200, jsonBody: { active: false, state: 'stopped' } };
      }

      const srv = servers[0];
      const ageSec = Math.floor((Date.now() - new Date(srv.creation_date).getTime()) / 1000);
      const remainingSec = Math.max(0, MAX_LIFETIME_MIN * 60 - ageSec);

      return {
        status: 200,
        jsonBody: {
          active: true,
          serverId: srv.id,
          state: srv.state,
          remainingSeconds: remainingSec
        }
      };
    } catch (err) {
      context.error(err);
      return { status: 500, jsonBody: { error: err.message } };
    }
  }
});

// 3. TIMER TRIGGER: BudgetGuard (běží každé 2 minuty)
app.timer('BudgetGuard', {
  schedule: '0 */2 * * * *',
  handler: async (myTimer, context) => {
    const cfg = getScwConfig();
    const servers = await listSandboxServers(cfg);

    for (const srv of servers) {
      const ageMin = (Date.now() - new Date(srv.creation_date).getTime()) / 60000;
      if (ageMin >= MAX_LIFETIME_MIN) {
        context.log(`BudgetGuard: Terminating ${srv.id} (age: ${ageMin.toFixed(1)} min)`);
        const termRes = await fetch(`${cfg.baseUrl}/servers/${srv.id}/action`, {
          method: 'POST',
          headers: cfg.headers,
          body: JSON.stringify({ action: 'terminate' })
        });
        if (!termRes.ok) {
          context.error(`Failed to terminate ${srv.id}: ${await termRes.text()}`);
        }
      }
    }
  }
});