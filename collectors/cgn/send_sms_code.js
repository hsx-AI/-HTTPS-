const fs = require('fs');
const path = require('path');
const http = require('http');
const https = require('https');
const crypto = require('crypto');

const CONFIG_PATH = process.env.CGN_CONFIG_PATH || path.join(__dirname, 'config.json');

/** 读取账号配置并补齐请求默认值；必填项无效时在发送短信前终止。 */
function loadConfig() {
  if (!fs.existsSync(CONFIG_PATH)) {
    throw new Error('缺少 config.json，请先填写配置文件。');
  }

  const config = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8').replace(/^\uFEFF/, ''));
  const requiredFields = ['loginPageUrl', 'username', 'password'];
  const missing = requiredFields.filter((key) => !config[key] || String(config[key]).includes('请填写'));

  if (missing.length > 0) {
    throw new Error(`请先在 config.json 中填写这些字段: ${missing.join(', ')}`);
  }

  return {
    acceptLanguage: 'zh-CN,zh;q=0.9',
    userAgent:
      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36',
    timeoutMs: 15000,
    ...config,
  };
}

class CookieJar {
  /** 按域名、路径和名称存储 Cookie，避免跨系统泄露会话凭据。 */
  constructor() {
    this.cookies = new Map();
  }

  /** 解析服务器 Cookie 属性，仅接受来源域允许的 Cookie，并处理过期删除。 */
  addFromSetCookie(setCookieHeaders = [], url) {
    const source = new URL(url);
    for (const header of setCookieHeaders) {
      const firstPart = header.split(';', 1)[0];
      const separatorIndex = firstPart.indexOf('=');
      if (separatorIndex <= 0) {
        continue;
      }
      const name = firstPart.slice(0, separatorIndex).trim();
      const value = firstPart.slice(separatorIndex + 1).trim();
      const attributes = Object.fromEntries(header.split(';').slice(1).map((part) => {
        const [key, ...parts] = part.trim().split('=');
        return [key.toLowerCase(), parts.join('=')];
      }));
      const domain = (attributes.domain || source.hostname).replace(/^\./, '').toLowerCase();
      if (source.hostname !== domain && !source.hostname.endsWith(`.${domain}`)) continue;
      const defaultPath = source.pathname.slice(0, source.pathname.lastIndexOf('/')) || '/';
      const cookiePath = attributes.path?.startsWith('/') ? attributes.path : defaultPath;
      const expiry = /^-?\d+$/.test(attributes['max-age'] ?? '')
        ? Date.now() + Number(attributes['max-age']) * 1000
        : attributes.expires ? Date.parse(attributes.expires) : null;
      const expires = Number.isFinite(expiry) ? expiry : null;
      const key = `${domain}|${cookiePath}|${name}`;
      if (expires !== null && expires <= Date.now()) {
        this.cookies.delete(key);
      } else {
        this.cookies.set(key, {
          name, value, domain, path: cookiePath, expires,
          hostOnly: !attributes.domain,
          secure: Object.hasOwn(attributes, 'secure'),
        });
      }
    }
  }

  /** 只返回目标地址可使用且未过期的 Cookie，长路径优先。 */
  toHeader(url) {
    const target = new URL(url);
    return Array.from(this.cookies.values())
      .filter((cookie) => (cookie.hostOnly ? target.hostname === cookie.domain
        : target.hostname === cookie.domain || target.hostname.endsWith(`.${cookie.domain}`))
        && (target.pathname === cookie.path || target.pathname.startsWith(
          cookie.path.endsWith('/') ? cookie.path : `${cookie.path}/`))
        && (!cookie.secure || target.protocol === 'https:')
        && (cookie.expires === null || cookie.expires > Date.now()))
      .sort((a, b) => b.path.length - a.path.length)
      .map(({ name, value }) => `${name}=${value}`)
      .join('; ');
  }
}

/**
 * 发送原生 HTTP/HTTPS 请求并维护 Cookie；重定向遵循浏览器方法转换规则。
 * 可禁用跳转或限制跳转来源；跨来源时删除鉴权头，307/308 不跨来源重发请求体。
 * responseType 为 buffer 时保留原始二进制，用于下载 Excel 等文件。
 */
function request({ url, method = 'GET', headers = {}, body, cookieJar, timeoutMs = 15000,
  maxRedirects = 10, followRedirects = true, allowedOrigins, responseType = 'text' }) {
  return new Promise((resolve, reject) => {
    const currentUrl = new URL(url);
    const requestHeaders = { ...headers };
    if (!['http:', 'https:'].includes(currentUrl.protocol)) {
      reject(new Error('只支持 HTTP/HTTPS 地址'));
      return;
    }
    if (allowedOrigins && !allowedOrigins.includes(currentUrl.origin)) {
      reject(new Error(`拒绝跳转到未授权来源: ${currentUrl.origin}`));
      return;
    }
    const cookieHeader = cookieJar?.toHeader(url);

    if (cookieHeader) {
      requestHeaders.Cookie = cookieHeader;
    }

    const req = (currentUrl.protocol === 'https:' ? https : http).request(
      {
        protocol: currentUrl.protocol,
        hostname: currentUrl.hostname.replace(/^\[|\]$/g, ''),
        port: currentUrl.port || (currentUrl.protocol === 'https:' ? 443 : 80),
        path: `${currentUrl.pathname}${currentUrl.search}`,
        method,
        headers: requestHeaders,
      },
      (res) => {
        const chunks = [];

        res.on('data', (chunk) => chunks.push(chunk));
        res.on('end', async () => {
          const rawBody = Buffer.concat(chunks);
          const responseBody = responseType === 'buffer' ? rawBody : rawBody.toString('utf8');
          const setCookieHeaders = Array.isArray(res.headers['set-cookie']) ? res.headers['set-cookie'] : [];
          cookieJar?.addFromSetCookie(setCookieHeaders, url);

          const isRedirect = [301, 302, 303, 307, 308].includes(res.statusCode);
          if (followRedirects && isRedirect && res.headers.location) {
            if (maxRedirects <= 0) {
              reject(new Error(`重定向次数过多: ${currentUrl.origin}${currentUrl.pathname}`));
              return;
            }

            const redirectUrl = new URL(res.headers.location, currentUrl).toString();
            const switchToGet = res.statusCode === 303 || ([301, 302].includes(res.statusCode) && method === 'POST');
            const redirectHeaders = { ...headers };
            const crossOrigin = new URL(redirectUrl).origin !== currentUrl.origin;
            if (crossOrigin && body && !switchToGet) {
              reject(new Error('拒绝跨来源重发请求体'));
              return;
            }
            for (const key of Object.keys(redirectHeaders)) {
              if (key.toLowerCase() === 'cookie'
                || (crossOrigin && ['authorization', 'origin', 'referer'].includes(key.toLowerCase()))
                || (switchToGet && ['content-length', 'content-type'].includes(key.toLowerCase()))) {
                delete redirectHeaders[key];
              }
            }
            try {
              const redirected = await request({
                url: redirectUrl,
                method: switchToGet ? 'GET' : method,
                headers: redirectHeaders,
                body: switchToGet ? undefined : body,
                cookieJar,
                timeoutMs,
                maxRedirects: maxRedirects - 1,
                followRedirects,
                allowedOrigins,
                responseType,
              });
              resolve(redirected);
            } catch (error) {
              reject(error);
            }
            return;
          }

          resolve({
            statusCode: res.statusCode,
            headers: res.headers,
            body: responseBody,
            url: currentUrl.toString(),
          });
        });
        res.on('error', reject);
      }
    );

    req.setTimeout(timeoutMs, () => {
      req.destroy(new Error(`请求超时: ${currentUrl.origin}${currentUrl.pathname}`));
    });

    req.on('error', reject);

    if (body) {
      req.write(body);
    }

    req.end();
  });
}

/** 提取隐藏输入框值；页面未直接提供认证方式时由调用者选择短信模式。 */
function extractValue(html, inputId) {
  const regex = new RegExp(`<input[^>]+id=["']${inputId}["'][^>]*value=["']([^"']*)["']`, 'i');
  return html.match(regex)?.[1] ?? null;
}

/** 复现官网加密：小写账号 MD5 中间 16 位作为 AES-128-ECB 密钥，采用 PKCS7。 */
function encryptPassword(username, password) {
  const normalizedUsername = username.trim().toLowerCase();
  const md5 = crypto.createHash('md5').update(normalizedUsername).digest('hex');
  const key = md5.slice(8, 24);
  const cipher = crypto.createCipheriv('aes-128-ecb', Buffer.from(key, 'utf8'), null);
  cipher.setAutoPadding(true);
  return cipher.update(password, 'utf8', 'base64') + cipher.final('base64');
}

/** 打开登录页建立新会话，获取页面参数，不复用抓包文件中的旧 Cookie。 */
async function initSession(config, cookieJar) {
  const initResponse = await request({
    url: config.loginPageUrl,
    method: 'GET',
    cookieJar,
    timeoutMs: config.timeoutMs,
    headers: {
      Accept:
        'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
      'Accept-Language': config.acceptLanguage,
      'User-Agent': config.userAgent,
      Connection: 'keep-alive',
      Referer: config.loginPageUrl,
    },
  });

  if (initResponse.statusCode !== 200) {
    throw new Error(`初始化登录页失败，HTTP ${initResponse.statusCode}`);
  }

  const pageHtml = initResponse.body;
  const ids = extractValue(pageHtml, 'ids') || '_4_5_';
  const language = extractValue(pageHtml, 'language') || 'Chinese';
  const loginPage = new URL(config.loginPageUrl);
  const appCode = config.appCode || loginPage.searchParams.get('bypassAppId') || 'portal';

  return {
    ids,
    language,
    appCode,
  };
}

/** 使用当前会话和加密密码请求短信；Content-Type 保持官网 jQuery 默认行为。 */
async function sendSmsCode(config, sessionInfo, cookieJar) {
  const baseUrl = new URL(config.loginPageUrl).origin;
  const payload = {
    ids: sessionInfo.ids,
    username: config.username.trim().toLowerCase(),
    password: encryptPassword(config.username, config.password),
    encryption: 'true',
    appCode: sessionInfo.appCode,
  };

  const body = JSON.stringify(payload);
  const response = await request({
    url: `${baseUrl}/authcenter/getSMSCodeByAccount`,
    method: 'POST',
    cookieJar,
    timeoutMs: config.timeoutMs,
    headers: {
      Accept: 'application/json, text/javascript, */*; q=0.01',
      'Accept-Language': config.acceptLanguage,
      'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
      Origin: baseUrl,
      Referer: config.loginPageUrl,
      'User-Agent': config.userAgent,
      'X-Requested-With': 'XMLHttpRequest',
      Connection: 'keep-alive',
      'Content-Length': Buffer.byteLength(body),
    },
    body,
  });

  let json;
  try {
    json = JSON.parse(response.body);
  } catch (error) {
    throw new Error(`验证码接口返回了非 JSON 内容，HTTP ${response.statusCode}`);
  }

  return {
    httpStatus: response.statusCode,
    json,
  };
}

/** 独立入口：仅发送短信，不消费接码服务中的验证码，也不提交登录。 */
async function main() {
  const config = loadConfig();
  const cookieJar = new CookieJar();

  console.log('1/2 初始化登录会话...');
  const sessionInfo = await initSession(config, cookieJar);
  console.log(`已获取页面参数: ids=${sessionInfo.ids}, language=${sessionInfo.language}, appCode=${sessionInfo.appCode}`);

  console.log('2/2 发送验证码请求...');
  const result = await sendSmsCode(config, sessionInfo, cookieJar);

  console.log(`HTTP 状态码: ${result.httpStatus}`);
  console.log('接口响应:');
  console.log(JSON.stringify(result.json, null, 2));

  if (result.httpStatus === 200 && String(result.json.code) === '0') {
    console.log('\n验证码已成功触发发送。');
  } else {
    console.log('\n验证码发送未成功，请根据上面的 message/code 排查。');
    process.exitCode = 1;
  }
}

module.exports = { loadConfig, CookieJar, request, encryptPassword, initSession, sendSmsCode };

if (require.main === module) {
  main().catch((error) => {
    console.error(`执行失败: ${error.message}`);
    process.exitCode = 1;
  });
}
