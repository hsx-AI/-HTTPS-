const fs = require('fs');
const path = require('path');
const { request } = require('./send_sms_code');

/** 从环境变量或现有云接码项目加载配置，复用项目取码密钥，不复制秘密。 */
function relaySettings(config) {
  const configPath = process.env.CODE_RELAY_CONFIG || config.smsRelayConfigPath
    || path.resolve(__dirname, '..', '..', 'sms_relay_config.json');
  const stored = fs.existsSync(configPath)
    ? JSON.parse(fs.readFileSync(configPath, 'utf8').replace(/^\uFEFF/, '')) : {};
  let token = process.env.CODE_RELAY_TOKEN || stored.token;
  if (!token) {
    const credentialsPath = stored.credentialsFile
      ? stored.credentialsFile.replace(/^~/, (process.env.USERPROFILE || process.env.HOME))
      : path.join(process.env.USERPROFILE || process.env.HOME, '.local', 'share', 'sms-code-relay', 'credentials.json');
    if (fs.existsSync(credentialsPath)) {
      token = JSON.parse(fs.readFileSync(credentialsPath, 'utf8')).clients?.[stored.clientName || 'default'];
    }
  }
  if (!token) throw new Error(`未配置云接码项目密钥，请检查 ${configPath} 或 CODE_RELAY_TOKEN`);
  const url = new URL(process.env.CODE_RELAY_URL || config.smsRelayUrl
    || stored.baseUrl || 'https://www.hec-hsx.top');
  if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash) {
    throw new Error('云接码地址必须使用不含凭据、查询串及片段的 HTTPS 地址');
  }
  const timeoutSeconds = config.smsTimeoutSeconds ?? 120;
  if (!Number.isInteger(timeoutSeconds) || timeoutSeconds < 1 || timeoutSeconds > 300) {
    throw new Error('smsTimeoutSeconds 必须为 1 到 300 的整数');
  }
  const interval = Number(stored.pollIntervalSeconds ?? 2);
  if (!Number.isFinite(interval)) throw new Error('接码轮询间隔必须为有效数字');
  return {
    apiUrl: url.href.replace(/\/$/, ''), token: String(token), timeoutSeconds,
    pollIntervalMs: Math.min(10000, Math.max(500, interval * 1000)),
    sender: process.env.CODE_RELAY_SENDER || config.smsSender || '',
    senderContains: (config.smsSenderContains || '').trim().toLowerCase(),
  };
}

/** 云接码请求不携带站点 Cookie、不跟随跳转、不记录 Token 或返回的验证码。 */
async function relayRequest(settings, endpoint, timeoutMs = 10000, authenticated = true) {
  const response = await request({
    url: `${settings.apiUrl}${endpoint}`, timeoutMs, followRedirects: false,
    headers: {
      'Cache-Control': 'no-store',
      ...(authenticated ? { Authorization: `Bearer ${settings.token}` } : {}),
    },
  });
  if (response.statusCode === 204) return null;
  if (response.statusCode !== 200) {
    throw new Error(`云接码接口失败，HTTP ${response.statusCode}（401 检查项目密钥，403 检查发送方权限）`);
  }
  try { return JSON.parse(response.body); } catch {
    throw new Error('云接码接口返回非 JSON 内容');
  }
}

/** 校验只读记录列表结构；云服务仅返回当前项目有权读取且未过期的验证码。 */
async function recentCodes(settings, timeoutMs = 10000) {
  const result = await relayRequest(settings, '/v1/codes/recent?limit=50', timeoutMs);
  if (!Array.isArray(result?.items)) throw new Error('云接码列表缺少 items 数组');
  if (result.items.some((item) => !Number.isSafeInteger(item.id) || item.id < 0)) {
    throw new Error('云接码列表包含无效游标');
  }
  return result.items;
}

/**
 * 发送短信前检查服务及项目鉴权，并记录最大 ID，避免复用已有验证码。
 * 已知精确发送方时使用 latest/next 长轮询；未指定时复用参考客户端的 recent 轮询。
 */
async function prepareRelay(settings) {
  const health = await relayRequest(settings, '/healthz', 10000, false);
  if (health?.ok !== true) throw new Error('云接码服务健康检查失败');
  let cursor;
  if (settings.sender) {
    const result = await relayRequest(settings,
      `/v1/codes/latest?sender=${encodeURIComponent(settings.sender)}`);
    cursor = result?.id;
  } else {
    cursor = Math.max(0, ...(await recentCodes(settings)).map((item) => item.id));
  }
  if (!Number.isSafeInteger(cursor) || cursor < 0) throw new Error('云接码服务返回无效游标');
  return cursor;
}

/** 返回记录被拒绝的原因，不包含验证码内容；null 表示符合本次登录的取码条件。 */
function rejectionReason(settings, item, cursor, after) {
  if (!Number.isSafeInteger(item?.id) || item.id <= cursor) return '不是发送前游标之后的新记录';
  if (settings.sender && item.sender !== settings.sender) return '发送方与精确号码不匹配';
  if (settings.senderContains
    && !String(item.sender).toLowerCase().includes(settings.senderContains)) return '发送方不符合号码过滤';
  if (!/^\d{6}$/.test(String(item.code))) return '验证码不是六位数字';
  if (!Number.isFinite(item.received_at) || item.received_at < Math.floor(after / 1000)) {
    return '短信接收时间早于本次发送或时间字段无效';
  }
  if (item.received_at > Date.now() / 1000 + 60) return '短信时间超前，请检查手机时钟';
  if (!Number.isFinite(item.expires_at) || item.expires_at <= Date.now() / 1000) return '验证码已过期或有效期无效';
  return null;
}

/** 按云端协议检查发送方、六位数字、游标和时间，不放宽旧码及过期检查。 */
function matchingCode(settings, item, cursor, after) {
  return rejectionReason(settings, item, cursor, after) === null;
}

/** 在轮询之间等待固定的有界间隔，收到新记录后立即返回。 */
function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * 等待游标之后且接收时间不早于发送动作的新码，不删除云端记录。
 * 已指定发送方时使用最长 25 秒长轮询；否则按配置间隔查询 recent，超时不重复发短信。
 */
async function waitForCode(settings, cursor, after) {
  const deadline = Date.now() + settings.timeoutSeconds * 1000;
  const reported = new Set();
  let nextProgress = Date.now() + 15000;
  while (Date.now() < deadline) {
    const remaining = deadline - Date.now();
    let items;
    if (settings.sender) {
      const wait = Math.max(0, Math.min(25, Math.floor(remaining / 1000)));
      const result = await relayRequest(settings,
        `/v1/codes/next?sender=${encodeURIComponent(settings.sender)}&after=${cursor}&wait=${wait}`,
        Math.min(remaining + 1000, wait * 1000 + 5000));
      items = result ? [result] : [];
    } else {
      items = await recentCodes(settings, Math.min(remaining, 10000));
    }
    const candidates = items.filter((item) => matchingCode(settings, item, cursor, after))
      .sort((a, b) => a.id - b.id);
    if (candidates.length) return String(candidates[0].code);
    for (const item of items) {
      if (item?.id > cursor && !reported.has(item.id)) {
        reported.add(item.id);
        console.log(`云端新记录 id=${item.id}，发送方=${item.sender}，已跳过：${rejectionReason(settings, item, cursor, after)}`);
      }
      if (Number.isSafeInteger(item?.id)) cursor = Math.max(cursor, item.id);
    }
    if (Date.now() >= nextProgress) {
      console.log(`等待匹配的新验证码，剩余 ${Math.max(0, Math.ceil((deadline - Date.now()) / 1000))} 秒...`);
      nextProgress = Date.now() + 15000;
    }
    const pause = Math.min(settings.pollIntervalMs, deadline - Date.now());
    if (pause > 0) await delay(pause);
  }
  throw new Error(`${settings.timeoutSeconds} 秒内未读取到匹配的新验证码，请检查发送方过滤、手机上传和时间`);
}

module.exports = { relaySettings, relayRequest, recentCodes, prepareRelay, rejectionReason, matchingCode, waitForCode };
