// Real production UI and stock API. No response mocks or editorial clip adapter.
const {chromium} = require('../full_app/production_frontend/node_modules/playwright');
const fs = require('fs');
const {execFileSync}=require('child_process');
const OUT='/srv/demo_out/demo02', BASE='http://127.0.0.1:8012';
const wait=ms=>new Promise(r=>setTimeout(r,ms));
async function main(){
 const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 const context=await browser.newContext({viewport:{width:1920,height:1080},recordVideo:{dir:OUT+'/recordings',size:{width:1920,height:1080}}});
 const page=await context.newPage(); page.setDefaultTimeout(30000);
 const begin=Date.now(), scenes=[];
 let id=fs.existsSync(OUT+'/job-id.txt')?fs.readFileSync(OUT+'/job-id.txt','utf8').trim():null;
 async function scene(label,action){const start=(Date.now()-begin)/1000;await action();await wait(2400);scenes.push({label,start,end:(Date.now()-begin)/1000});console.log('SCENE',label);}
 async function snapshot(){const r=await context.request.get(BASE+'/api/jobs/'+id);if(!r.ok())throw Error(await r.text());return r.json();}
 async function post(action,data){const r=await context.request.post(BASE+'/api/jobs/'+id+'/'+action,{data});if(!r.ok())throw Error(await r.text());}
 async function idle(){let last='';for(let i=0;i<7200;i++){let d=await snapshot();if(d.status==='error'){fs.writeFileSync(OUT+'/error.json',JSON.stringify(d,null,2));throw Error(d.error)}const stage=d.pipeline_stage||d.status;if(stage!==last){console.log('STAGE',stage);last=stage;}if(!['queued','analyzing','planning','rendering'].includes(d.status))return d;await wait(1000);}throw Error('deadline');}
 try{
  await page.goto(BASE);
  if(!id){
   const uploaded=page.waitForResponse(r=>r.url()===BASE+'/api/jobs'&&r.request().method()==='POST'&&r.ok());
   await scene('Upload the full 31-minute Valorant source',async()=>{await page.locator('input[type=file]').first().setInputFiles('/srv/demo_in/valorant_phoenix_44k.mp4');});
   id=(await (await uploaded).json()).id;fs.writeFileSync(OUT+'/job-id.txt',id);
   await scene('Enable stock signals, window scoring, planner and reactions',async()=>{
    for(const label of ['Gemini window scoring','Story planner v2','Meme reactions','Share kit'])await page.getByRole('checkbox',{name:label,exact:false}).check();
    await page.getByRole('checkbox',{name:'Captions',exact:false}).uncheck();
   });
  }
  let d=await snapshot();
  if(!d.completed.includes('analyze')){
   await scene('Analyze full match: local candidates then 40 Gemini windows',async()=>{
    await post('analyze',{game:'auto',planner_v2:true,window_scoring:true,use_signals:true,privacy_blur:true,share_kit:true,mode:'nice',style:'hype_montage',max_duration:60,captions:false,reactions:true});await wait(4000);
   });
   d=await idle();
  }
  const calls=()=>Number(execFileSync('../.venv/bin/python',['-c',"import sqlite3,sys; print(sqlite3.connect(sys.argv[1]).execute('SELECT used FROM budget WHERE id=1').fetchone()[0])",OUT+'/jobs/'+id+'/gemini-budget.sqlite3'],{encoding:'utf8'}).trim());
  const before=calls();
  fs.writeFileSync(OUT+'/analysis.json',JSON.stringify({...d,analysis_calls:before},null,2));
  // A resumed run preserves the original UI capture; no second upload or analysis.
  if(await page.locator('.clip-card').count()){
   await scene('Review fused candidate evidence and the full-match interest curve',async()=>{await page.locator('.review').scrollIntoViewIfNeeded();});
   await scene('Inspect real clip scores and trims',async()=>{await page.locator('.clip-card').first().scrollIntoViewIfNeeded();});
  }
  for(const [name,mode,preset,target] of [['landscape','nice','landscape',60],['vertical','nice','vertical',30],['mean_vertical','mean','vertical',20]]){
   if(fs.existsSync(OUT+'/montage_'+name+'.mp4'))continue;
   await scene('Render '+name+' / '+target+' seconds / same saved analysis',async()=>{await post('render',{mode,preset,max_duration:target});});
   d=await idle();
   if(calls()!==before)throw Error('Render unexpectedly consumed paid attempts');
   fs.writeFileSync(OUT+'/'+name+'.json',JSON.stringify(d,null,2));
   fs.copyFileSync(OUT+'/jobs/'+id+'/output.mp4',OUT+'/montage_'+name+'.mp4');
   if(fs.existsSync(OUT+'/jobs/'+id+'/share'))fs.cpSync(OUT+'/jobs/'+id+'/share',OUT+'/share_'+name,{recursive:true});
   if(await page.locator('.output video').count())await scene('Play '+name+' with team reactions',async()=>{await page.locator('.output').scrollIntoViewIfNeeded();await page.locator('.output video').evaluate(v=>v.play());await wait(4500);await page.locator('.output video').evaluate(v=>v.pause());});
  }
  await page.screenshot({path:OUT+'/frontend.png',fullPage:true});
 }finally{
  const video=page.video();await context.close();await video.saveAs(OUT+'/ui_raw_latest.webm');await browser.close();
  if(!fs.existsSync(OUT+'/ui_raw.webm')||scenes.length>6){fs.copyFileSync(OUT+'/ui_raw_latest.webm',OUT+'/ui_raw.webm');fs.writeFileSync(OUT+'/ui_scenes.json',JSON.stringify(scenes,null,2));}
 }
}
main().catch(e=>{console.error(e.message);process.exitCode=1;});
