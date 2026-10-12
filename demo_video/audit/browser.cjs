/* Browser evidence against the real server, no inference calls.
 * Only POST /api/jobs is intercepted to attach the already-completed audit job:
 * the app has no resume-by-ID UI. Status, source, exports and shares stay real.
 */
const fs=require('node:fs');
const path=require('node:path');
const {createRequire}=require('node:module');
const {spawn}=require('node:child_process');
const root=path.resolve(__dirname,'../..');
const out=path.join(__dirname,'out');
const front=path.join(root,'full_app/production_frontend');
const {chromium}=createRequire(path.join(front,'package.json'))('@playwright/test');
async function main(){
  const log=fs.openSync(path.join(out,'vite.log'),'a');
  const vite=spawn('npm',['run','dev','--','--host','127.0.0.1','--port','5178'],{cwd:front,stdio:['ignore',log,log],detached:true});
  vite.unref();
  fs.writeFileSync(path.join(out,'vite_pid.json'),JSON.stringify({pid:vite.pid}));
  const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  const errors=[];
  page.on('pageerror',e=>errors.push(String(e)));
  await page.goto('http://127.0.0.1:8000');
  await page.screenshot({path:path.join(out,'ui_stock_legacy.png'),fullPage:true});
  for(let i=0;i<30;i++){
    try{await page.goto('http://127.0.0.1:5178');break;}catch{await new Promise(r=>setTimeout(r,1000));}
  }
  await page.getByRole('button',{name:'Full experience',exact:true}).waitFor();
  await page.waitForTimeout(1500);
  await page.screenshot({path:path.join(out,'ui_settings_defaults.png'),fullPage:true});
  await page.getByRole('button',{name:'Full experience',exact:true}).click();
  await page.screenshot({path:path.join(out,'ui_settings_full.png'),fullPage:true});
  const controls=await page.locator('input,select,textarea,button').evaluateAll(nodes=>nodes.map(n=>({
    tag:n.tagName,type:n.type,text:n.closest('label')?.innerText||n.getAttribute('aria-label')||n.innerText,
    value:n.value,checked:n.checked,disabled:n.disabled
  })));
  fs.writeFileSync(path.join(out,'ui_controls.json'),JSON.stringify(controls,null,2));
  const uploaded=JSON.parse(fs.readFileSync(path.join(out,'upload.json')));
  await page.route('**/api/jobs',async route=>{
    if(route.request().method()!=='POST')return route.continue();
    const real=await page.request.get('http://127.0.0.1:8000/api/jobs/'+uploaded.id);
    await route.fulfill({status:201,contentType:'application/json',body:await real.text()});
  });
  await page.locator('input[type=file]').first().setInputFiles({name:'audit-existing-job.mp4',mimeType:'video/mp4',buffer:Buffer.from('audit-session-attachment')});
  await page.waitForTimeout(4000);
  await page.screenshot({path:path.join(out,'ui_review_full.png'),fullPage:true});
  const director=page.getByText('Director',{exact:true}).first();
  if(await director.count()){
    await director.scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(out,'ui_director.png')});
  }
  const exports=page.getByRole('button',{name:/render/i});
  if(await exports.count()){
    await exports.last().scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(out,'ui_export.png')});
  }
  fs.writeFileSync(path.join(out,'ui_result.json'),JSON.stringify({errors,
    reroll_controls:await page.getByRole('button',{name:/reroll/i}).count(),
    chaos_controls:await page.getByLabel(/chaos/i).count(),
    director_count:await director.count(),
    text:await page.locator('body').innerText(),
    session_attachment:'Only POST /api/jobs was mapped to the existing real job. No fake analysis/render/status/media; no new inference.'},null,2));
  await browser.close();
}
main().catch(e=>{console.error(e);process.exit(1)});
