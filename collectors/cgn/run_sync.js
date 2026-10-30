// Downloads with a verified saved session; one full login is allowed only before exporting.
const fs = require('fs');
const path = require('path');
const login = require('./auto_login');
const exporter = require('./export_quality_plan');
const {loadConfig} = require('./send_sms_code');
async function main() {
  const resultFile = process.argv[2];
  if (!resultFile) throw new Error('缺少结果文件参数');
  const config = loadConfig();
  let jar;
  try { jar = exporter.loadSession(); await login.verifyApplication(config, jar); }
  catch { console.log('保存的广核登录已失效，执行一次短信登录…'); await login.main(); }
  // No retry after an export failure: avoid duplicate SMS requests on network errors.
  const result = await exporter.main();
  fs.writeFileSync(resultFile, JSON.stringify(result || {empty: true}), {mode: 0o600});
}
if (require.main === module) main().catch(error => { console.error(`广核采集失败：${error.message}`); process.exitCode = 1; });
module.exports = {main};
