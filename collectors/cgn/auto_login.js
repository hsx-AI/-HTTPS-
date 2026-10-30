const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');
const { relaySettings, prepareRelay, waitForCode } = require('./sms_relay_client');
const {
  loadConfig, CookieJar, request, encryptPassword, initSession, sendSmsCode,
} = require('./send_sms_code');

/** 根据官网行为截取完整嵌套 OAuth 查询串，不能用 searchParams.get 丢失后续参数。 */
function oauthUrl(loginPageUrl) {
  const marker = 'jit_pnx_oauth=';
  const offset = loginPageUrl.indexOf(marker);
  if (offset < 0) throw new Error('登录地址缺少 jit_pnx_oauth 授权参数');
  let value = loginPageUrl.slice(offset + marker.length);
  if (!value.startsWith('/') && !/^https?:\/\//.test(value)) value = decodeURIComponent(value);
  return new URL(value, loginPageUrl).toString();
}

/** 提交一次短信登录 POST，保留原登录页查询串，不使用抓包中的旧码或旧 Cookie。 */
async function submitLogin(config, session, jar, smsCode) {
  const page = new URL(config.loginPageUrl);
  jar.addFromSetCookie([`language=${session.language}; Path=/; Secure`], page.href);
  const response = await request({
    url: `${page.origin}/authcenter/userLogin${page.search}`,
    method: 'POST',
    cookieJar: jar,
    timeoutMs: config.timeoutMs,
    followRedirects: false,
    headers: {
      Accept: 'application/json, text/javascript, */*; q=0.01',
      'Accept-Language': config.acceptLanguage,
      'Content-Type': 'application/json',
      Origin: page.origin,
      Referer: page.href,
      'User-Agent': config.userAgent,
      'X-Requested-With': 'XMLHttpRequest',
    },
    body: JSON.stringify({
      ids: session.ids,
      username: config.username.trim().toLowerCase(),
      password: encryptPassword(config.username, config.password),
      smsCode, encryption: 'true', appCode: session.appCode,
    }),
  });
  let result;
  try { result = JSON.parse(response.body); } catch {
    throw new Error(`登录接口返回非 JSON，HTTP ${response.statusCode}`);
  }
  if (response.statusCode !== 200 || !['0', '302'].includes(String(result.code))) {
    throw new Error(`登录被拒绝，HTTP ${response.statusCode}，code=${result.code}，${result.message || ''}`);
  }
  if (String(result.code) === '0' && result.data) {
    if (result.data.username) jar.addFromSetCookie([
      `uap_userName=${encodeURIComponent(encodeURIComponent(result.data.username))}; Path=/; Secure`,
    ], page.href);
    if (result.data.logintime) jar.addFromSetCookie([
      `uap_loginTime=${result.data.logintime}; Path=/; Secure`,
    ], page.href);
  }
  return result;
}

/** 完成授权码跳转，仅访问登录中心和目标应用；应用会话的进一步验证由调用者执行。 */
async function authorizeApplication(config, jar, loginResult) {
  const authorization = oauthUrl(config.loginPageUrl);
  const callback = new URL(authorization).searchParams.get('redirect_uri');
  if (!callback) throw new Error('OAuth 授权地址缺少 redirect_uri');
  const allowedOrigins = [new URL(config.loginPageUrl).origin, new URL(callback).origin];
  const next = String(loginResult.code) === '302'
    ? new URL(loginResult.message, config.loginPageUrl).href : authorization;
  return request({
    url: next, cookieJar: jar, timeoutMs: config.timeoutMs,
    headers: { 'User-Agent': config.userAgent, 'Accept-Language': config.acceptLanguage },
    allowedOrigins,
  });
}

/** 使用官网当前用户接口验证应用会话，要求成功码及账号身份均匹配。 */
async function verifyApplication(config, jar) {
  const callback = new URL(oauthUrl(config.loginPageUrl)).searchParams.get('redirect_uri');
  const origin = new URL(callback).origin;
  const response = await request({
    url: `${origin}/imsqs-server/user/getCurrentUser?lang=zh`,
    method: 'POST', body: '{}', cookieJar: jar,
    timeoutMs: config.timeoutMs, followRedirects: false,
    headers: {
      'Content-Type': 'application/json',
      'X-Requested-With': 'XMLHttpRequest',
      'User-Agent': config.userAgent, Origin: origin, Referer: `${origin}/`,
    },
  });
  let result;
  try { result = JSON.parse(response.body); } catch {
    throw new Error(`应用会话验证返回非 JSON，HTTP ${response.statusCode}`);
  }
  const user = typeof result.data === 'string' ? result.data : '';
  const account = user.match(/^\[([^\]]+)\]/)?.[1];
  if (response.statusCode !== 200 || String(result.code) !== '0'
    || account?.toLowerCase() !== config.username.trim().toLowerCase()) {
    throw new Error(`应用会话验证失败，HTTP ${response.statusCode}，code=${result.code}；当前用户未匹配`);
  }
  return user;
}

/**
 * 将会话保存到项目 .local 私有目录，兼容工具的工作区写入限制。
 * Windows 下限制目录 ACL；该目录由 Git 忽略，不保存明文密码或短信验证码。
 */
function saveSession(config, jar, response, user) {
  const directory = path.join(__dirname, '.local');
  fs.mkdirSync(directory, { recursive: true });
  if (process.platform === 'win32') {
    execFileSync('icacls', [directory, '/inheritance:r', '/grant:r',
      `${process.env.USERDOMAIN}\\${process.env.USERNAME}:(OI)(CI)(F)`], { stdio: 'ignore' });
  }
  const file = path.join(directory, 'session.json');
  fs.writeFileSync(file, JSON.stringify({
    savedAt: new Date().toISOString(), appCode: config.appCode,
    finalUrl: response.url, applicationVerified: true, user,
    cookies: Array.from(jar.cookies.values()),
  }, null, 2), { mode: 0o600 });
  return file;
}

/** 串联纯 HTTP 登录；每次只请求一条新短信，不自动重试可能导致账号锁定的登录。 */
async function main() {
  const config = loadConfig();
  const callback = new URL(oauthUrl(config.loginPageUrl)).searchParams.get('redirect_uri');
  if (!callback || new URL(callback).protocol !== 'https:') {
    throw new Error('目标应用必须配置 HTTPS OAuth 回调地址');
  }
  const settings = relaySettings(config);
  console.log('1/5 检查云接码服务及项目密钥...');
  console.log(`取码发送方过滤：${settings.sender ? `精确号码 ${settings.sender}`
    : settings.senderContains ? `号码包含 ${settings.senderContains}` : '不限制发送方'}`);
  await prepareRelay(settings);
  console.log('2/5 初始化网站登录会话...');
  const jar = new CookieJar();
  const session = await initSession(config, jar);
  console.log('3/5 请求短信验证码并等待手机转发...');
  const cursor = await prepareRelay(settings);
  const after = Date.now();
  const sms = await sendSmsCode(config, session, jar);
  if (sms.httpStatus !== 200 || String(sms.json.code) !== '0') {
    throw new Error(`发送验证码失败，code=${sms.json.code}，${sms.json.message || ''}`);
  }
  console.log(`短信请求已成功，等待游标 ${cursor} 之后的新验证码，最长 ${settings.timeoutSeconds} 秒...`);
  const code = await waitForCode(settings, cursor, after);
  console.log('4/5 已读取新验证码，提交登录（不显示验证码）...');
  const login = await submitLogin(config, session, jar, code);
  console.log('5/5 登录中心已认证，完成应用 OAuth 跳转...');
  const response = await authorizeApplication(config, jar, login);
  if (response.statusCode !== 200 || new URL(response.url).origin === new URL(config.loginPageUrl).origin) {
    throw new Error('登录中心认证成功，但应用授权尚未完成');
  }
  const user = await verifyApplication(config, jar);
  const file = saveSession(config, jar, response, user);
  console.log('自动登录成功，目标应用当前用户已验证。');
  console.log(`会话已保存: ${file}`);
}

module.exports = {
  oauthUrl,
  submitLogin, authorizeApplication, verifyApplication, saveSession, main,
};

if (require.main === module) {
  main().catch((error) => {
    console.error(`自动登录失败: ${error.message}`);
    process.exitCode = 1;
  });
}
