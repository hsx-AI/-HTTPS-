const fs = require('fs');
const path = require('path');
const { loadConfig, CookieJar, request } = require('./send_sms_code');
const { oauthUrl, verifyApplication } = require('./auto_login');

const QUERY_TEMPLATE = path.join(__dirname, 'query.json');
const EXPORT_TEMPLATE = path.join(__dirname, 'export.json');

/** 只读取查询条件 JSON，不读取或执行抓包命令。 */
function readPayload(file) {
  const payload = JSON.parse(fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, ''));
  if (!payload || Array.isArray(payload) || typeof payload !== 'object') throw new Error('查询配置必须为 JSON 对象');
  return payload;
}

/** 加载自动登录保存的 Cookie，不使用请求说明中的旧 Token 或旧会话。 */
function loadSession() {
  const file = path.join(__dirname, '.local', 'session.json');
  if (!fs.existsSync(file)) throw new Error('尚无登录会话，请先运行 node auto_login.js');
  const saved = JSON.parse(fs.readFileSync(file, 'utf8'));
  if (!Array.isArray(saved.cookies)) throw new Error('会话文件缺少 Cookie，请重新登录');
  const jar = new CookieJar();
  for (const cookie of saved.cookies) {
    jar.cookies.set(`${cookie.domain}|${cookie.path}|${cookie.name}`, cookie);
  }
  return jar;
}

/** 生成应用 JSON 请求头；菜单标识与官网导出页面一致，不携带抓包中的 Bearer Token。 */
function applicationHeaders(config, origin) {
  return {
    Accept: 'application/json, text/plain, */*',
    'Accept-Language': config.acceptLanguage,
    'Content-Type': 'application/json;charset=UTF-8',
    'X-Requested-With': 'XMLHttpRequest',
    'User-Agent': config.userAgent,
    menuCode: 'manufacturing_quality_program',
    Origin: origin, Referer: `${origin}/`,
  };
}

/** 查询第一页获得实时总数；校验业务成功码及分页结构，禁止把旧的 total 当导出数量。 */
async function queryQualityPlans(config, jar, origin, template) {
  const payload = { ...template, pageIndex: 1, currentPage: 1, pageSize: 10, total: 0 };
  const response = await request({
    url: `${origin}/imsqs-server/qualityPlanSuperviseInfo/getQualityPlanInfoByPage?lang=zh`,
    method: 'POST', headers: applicationHeaders(config, origin),
    body: JSON.stringify(payload), cookieJar: jar,
    timeoutMs: Math.max(config.timeoutMs, 30000), followRedirects: false,
  });
  let result;
  try { result = JSON.parse(response.body); } catch {
    throw new Error(`质量计划查询返回非 JSON，HTTP ${response.statusCode}`);
  }
  if (response.statusCode !== 200 || String(result.code) !== '0') {
    throw new Error(`查询失败，HTTP ${response.statusCode}，code=${result.code}，${result.msg || ''}`);
  }
  if (!Number.isSafeInteger(result.data?.total) || result.data.total < 0
    || !Array.isArray(result.data.records)) throw new Error('查询返回的分页结构无效');
  return result.data;
}

/** 使用同一查询条件导出全部结果，去除分页字段，并将结束行设置为实时总数。 */
function exportPayload(query, template, total) {
  const filters = { ...query };
  for (const key of ['pageIndex', 'pageSize', 'total', 'currentPage']) delete filters[key];
  return { ...template, ...filters, start: '1', end: String(total), choiceType: 'all' };
}

/** 根据文件内容识别 Excel 格式，拒绝将 JSON 错误响应或登录页面保存为表格。 */
function excelExtension(buffer) {
  if (!Buffer.isBuffer(buffer) || !buffer.length) throw new Error('导出接口返回空文件');
  if (buffer.subarray(0, 8).equals(Buffer.from('d0cf11e0a1b11ae1', 'hex'))) return '.xls';
  if (buffer.subarray(0, 4).equals(Buffer.from('504b0304', 'hex'))
    && buffer.includes(Buffer.from('[Content_Types].xml'))
    && buffer.includes(Buffer.from('xl/'))) return '.xlsx';
  const text = buffer.subarray(0, 4096).toString('utf8').replace(/^\uFEFF/, '').trim();
  if (/urn:schemas-microsoft-com:office:spreadsheet/.test(text)) return '.xls';
  throw new Error('导出结果不是可识别的 Excel 文件，请检查登录状态和导出接口响应');
}

/** 解析服务器文件名，仅保留 Windows 安全的名称；扩展名以实际 Excel 格式为准。 */
function downloadFilename(disposition, extension) {
  const header = disposition || '';
  const encoded = header.match(/filename\*\s*=\s*(?:UTF-8'[^']*')?([^;]+)/i)?.[1];
  const plain = header.match(/filename\s*=\s*(?:"([^"]+)"|([^;]+))/i);
  let name = encoded || plain?.[1] || plain?.[2] || '质量计划';
  name = name.trim().replace(/^"|"$/g, '');
  try { name = decodeURIComponent(name); } catch { /* 未编码的服务器文件名保持原值。 */ }
  if (!encoded && /[^\x00-\x7f]/.test(name)
    && Array.from(name).every((character) => character.charCodeAt(0) <= 255)) {
    try {
      name = new TextDecoder('utf-8', { fatal: true }).decode(Buffer.from(name, 'latin1'));
    } catch { /* 仅修复有效 UTF-8 字节被 HTTP 头按 Latin-1 解码的情况。 */ }
  }
  name = name.split(/[\\/]/).at(-1).replace(/[<>:"|?*\x00-\x1f]/g, '_').replace(/[. ]+$/, '');
  let stem = path.parse(name).name.slice(0, 100) || '质量计划';
  if (/^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$/i.test(stem)) stem = `_${stem}`;
  const timestamp = new Date().toISOString().replace(/[-:]/g, '').replace(/\.\d+Z$/, 'Z');
  return `${stem}_${timestamp}${extension}`;
}

/** 调用导出 POST 并以二进制接收；写入前检查状态码和文件签名，不覆盖已有导出。 */
async function downloadQualityPlans(config, jar, origin, payload) {
  const response = await request({
    url: `${origin}/imsqs-server/qualityPlanSuperviseInfo/exportExcel?lang=zh`,
    method: 'POST', headers: applicationHeaders(config, origin),
    body: JSON.stringify(payload), cookieJar: jar,
    timeoutMs: Math.max(config.timeoutMs, 120000),
    followRedirects: false, responseType: 'buffer',
  });
  if (response.statusCode !== 200) throw new Error(`导出失败，HTTP ${response.statusCode}`);
  const extension = excelExtension(response.body);
  const directory = path.join(__dirname, 'downloads');
  fs.mkdirSync(directory, { recursive: true });
  const file = path.join(directory, downloadFilename(response.headers['content-disposition'], extension));
  fs.writeFileSync(file, response.body, { flag: 'wx' });
  return { file, bytes: response.body.length };
}

/** 独立入口：复用已登录会话，查询实时总数后导出全部质量计划，不重新请求短信。 */
async function main() {
  const config = loadConfig();
  const jar = loadSession();
  const callback = new URL(oauthUrl(config.loginPageUrl)).searchParams.get('redirect_uri');
  const origin = new URL(callback).origin;
  const query = readPayload(QUERY_TEMPLATE);
  const template = readPayload(EXPORT_TEMPLATE);
  console.log('1/3 验证保存的登录会话...');
  await verifyApplication(config, jar);
  console.log('2/3 查询质量计划...');
  const page = await queryQualityPlans(config, jar, origin, query);
  console.log(`当前查询共 ${page.total} 条质量计划。`);
  if (!page.total) {
    console.log('查询无结果，未生成空表格。');
    return;
  }
  console.log('3/3 纯 HTTP 导出全部查询结果...');
  const result = await downloadQualityPlans(config, jar, origin, exportPayload(query, template, page.total));
  console.log(`导出成功，文件大小 ${result.bytes} 字节。`);
  console.log(`表格已保存: ${result.file}`);
  return {...result, total: page.total};
}

module.exports = {
  readPayload, loadSession, applicationHeaders, queryQualityPlans,
  exportPayload, excelExtension, downloadFilename, downloadQualityPlans, main,
};

if (require.main === module) {
  main().catch((error) => {
    console.error(`质量计划导出失败: ${error.message}`);
    process.exitCode = 1;
  });
}
