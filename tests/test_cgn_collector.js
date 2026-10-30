const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const exporter = require('../collectors/cgn/export_quality_plan');
const login = require('../collectors/cgn/auto_login');
const configModule = require('../collectors/cgn/send_sms_code');

test('export uses the current total and removes pagination', () => {
  const query = {pageIndex:9, pageSize:10, total:999,currentPage:9,projectCodes:['TEST']};
  const payload = exporter.exportPayload(query,{end:'999',start:'1'},23);
  assert.equal(payload.end,'23'); assert.equal(payload.choiceType,'all');
  assert.equal(payload.pageIndex,undefined); assert.equal(payload.total,undefined);
  assert.deepEqual(payload.projectCodes,['TEST']);
  const defaults=exporter.readPayload(path.join(__dirname,'../collectors/cgn/query.json'));
  assert(Array.isArray(defaults.projectCodes)); assert.equal(defaults.total,undefined);
});

test('saved session reuse and one login fallback do not retry SMS after export failure', async () => {
  const temp=fs.mkdtempSync(path.join(os.tmpdir(),'cgn-test-'));
  const result=path.join(temp,'result.json'); const previousArg=process.argv[2];
  const originals=[configModule.loadConfig,exporter.loadSession,login.verifyApplication,login.main,exporter.main];
  try {
    configModule.loadConfig=()=>({}); exporter.loadSession=()=>({});
    let logins=0; login.main=async()=>{logins++};
    login.verifyApplication=async()=>{};
    exporter.main=async()=>({file:'example.xlsx',total:2});
    process.argv[2]=result;
    delete require.cache[require.resolve('../collectors/cgn/run_sync')];
    const runner=require('../collectors/cgn/run_sync');
    await runner.main(); assert.equal(logins,0); assert.equal(JSON.parse(fs.readFileSync(result)).total,2);
    login.verifyApplication=async()=>{throw new Error('expired')};
    await runner.main(); assert.equal(logins,1);
    login.verifyApplication=async()=>{};
    exporter.main=async()=>{throw new Error('export network failure')};
    await assert.rejects(runner.main(),/export network failure/);
    assert.equal(logins,1);
  } finally {
    [configModule.loadConfig,exporter.loadSession,login.verifyApplication,login.main,exporter.main]=originals;
    process.argv[2]=previousArg; fs.rmSync(temp,{recursive:true,force:true});
  }
});
