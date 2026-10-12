// LIVE smoke UI driver. No mocked routes/responses; every request hits Flask.
const { chromium } = require('../full_app/production_frontend/node_modules/playwright');
const fs = require('fs');
const path = require('path');
const OUT = '/srv/demo_out/demo01';
const BASE = 'http://127.0.0.1:8011';
const REPLAY = process.env.DEMO_UI_REPLAY === '1';
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
async function main() {
  const browser = await chromium.launch({headless:true, args:['--no-sandbox']});
  const context = await browser.newContext({viewport:{width:1920,height:1080}, recordVideo:{dir:OUT+'/recordings',size:{width:1920,height:1080}}});
  const page = await context.newPage();
  page.setDefaultTimeout(30000);
  const begin = Date.now();
  const scenes = [];
  let jobId;
  page.on('response', async response => {
    if (response.url() === BASE+'/api/jobs' && response.request().method() === 'POST' && response.ok()) {
      jobId = (await response.json()).job_id;
      fs.writeFileSync(OUT+'/job_id.txt', jobId);
    }
  });
  const stamp = () => (Date.now()-begin)/1000;
  async function scene(label, action) {
    const start = stamp();
    await action(); await wait(2200);
    scenes.push({label,start,end:stamp()});
    fs.writeFileSync(OUT+'/ui_scenes.json',JSON.stringify(scenes,null,2));
    console.log('SCENE', label);
  }
  async function job() { return (await context.request.get(BASE+'/api/jobs/'+jobId)).json(); }
  async function idle() {
    let last = '';
    for (let i=0;i<10800;i++) {
      const data = await job();
      const stage = data.pipeline_stage || data.status;
      if (stage !== last) {console.log('STAGE',stage);last=stage;}
      if (data.status === 'error') {fs.writeFileSync(OUT+'/error.json',JSON.stringify(data,null,2));throw new Error(data.error);}
      if (!['queued','analyzing','planning','rendering'].includes(data.status)) return data;
      await wait(1000);
    }
    throw new Error('Job timed out');
  }
  try {
    await page.goto(BASE);
    await scene('Upload real Valorant gameplay',async()=>{
      await page.locator('input[type=file]').first().setInputFiles('/srv/demo_in/valorant_phoenix_44k.mp4');
    });
    while(!jobId) await wait(500);
    await page.getByRole('button',{name:/Find my moments/}).waitFor();
    await scene('Auto game / signals / Gemini / privacy / team reactions',async()=>{
      for(const label of ['Gemini window scoring','Story planner v2','Meme reactions','Share kit'])
        await page.getByRole('checkbox',{name:label,exact:false}).check();
      await page.getByRole('checkbox',{name:'Captions',exact:false}).uncheck();
      await page.locator('.feature-toggles').scrollIntoViewIfNeeded();
    });
    await scene('Live pipeline progress',async()=>{
      await page.getByRole('button',{name:/Find my moments/}).click();
      await page.locator('.review').scrollIntoViewIfNeeded();
      await wait(4500);
    });
    let data = await idle();
    if(!REPLAY) fs.writeFileSync(OUT+'/analysis.json',JSON.stringify(data,null,2));
    // Keep a concise editorial selection from the real analysis; preserve evidence.
    const editorial = JSON.parse(fs.readFileSync(path.join(__dirname,'editorial_selection.json')));
    const selected = editorial.nice.map(edit=>{
      const c=data.clips.find(c=>c.start_seconds===edit.original_start && c.end_seconds===edit.original_end);
      if(!c) throw new Error('Editorial selection no longer matches analyzed source ranges');
      return {...c,keep:true,start_seconds:edit.start,end_seconds:edit.end,
        type:edit.type,caption:edit.caption,description:edit.caption,editorial_review:true};
    });
    fs.writeFileSync(OUT+'/editorial_selection.json',JSON.stringify(editorial,null,2));
    const response = await context.request.patch(BASE+'/api/jobs/'+jobId+'/clips',{data:{clips:selected}});
    if(!response.ok()) throw new Error(await response.text());
    await wait(6500);
    await scene('Interest curve from real candidate scores',async()=>{
      await page.getByRole('region',{name:'Review timeline'}).scrollIntoViewIfNeeded().catch(()=>page.locator('.timeline').scrollIntoViewIfNeeded());
    });
    await scene('Why this clip: real audio evidence',async()=>{
      await page.locator('.clip-card').nth(1).scrollIntoViewIfNeeded();
    });
    await scene('Trim and reorder before export',async()=>{
      const slider = page.getByLabel('Trim start 1',{exact:true});
      await slider.scrollIntoViewIfNeeded();await slider.focus();await slider.press('ArrowRight');
      await page.getByRole('button',{name:'Move clip 1 down',exact:true}).click();
      await page.getByRole('button',{name:'Save edits',exact:true}).click();
    });
    await scene('Landscape export',async()=>{
      await page.locator('.export select').selectOption('landscape');
      await page.getByRole('button',{name:/Render reel/}).click();
    });
    data = await idle();
    if(!REPLAY) {
      fs.writeFileSync(OUT+'/landscape.json',JSON.stringify(data,null,2));
      fs.copyFileSync(OUT+'/jobs/'+jobId+'/output.mp4',OUT+'/montage_landscape.mp4');
      fs.cpSync(OUT+'/jobs/'+jobId+'/share',OUT+'/share_landscape',{recursive:true});
    }
    await scene('Share kit / covers / posting copy',async()=>{
      await page.getByRole('region',{name:'Share kit',exact:true}).scrollIntoViewIfNeeded();
    });
    await scene('Play the real rendered montage',async()=>{
      await page.locator('.output').scrollIntoViewIfNeeded();
      await page.locator('.output video').evaluate(v=>v.play());await wait(7000);
      await page.locator('.output video').evaluate(v=>v.pause());
    });
    await scene('Vertical Short export',async()=>{
      await page.locator('.export select').selectOption('vertical');
      await page.getByRole('button',{name:/Render reel/}).click();
    });
    data = await idle();
    if(!REPLAY) {
      fs.writeFileSync(OUT+'/vertical.json',JSON.stringify(data,null,2));
      fs.copyFileSync(OUT+'/jobs/'+jobId+'/output.mp4',OUT+'/montage_vertical.mp4');
      fs.cpSync(OUT+'/jobs/'+jobId+'/share',OUT+'/share_vertical',{recursive:true});
    } else fs.writeFileSync(OUT+'/ui_replay.json',JSON.stringify(data,null,2));
    await page.screenshot({path:OUT+'/frontend.png',fullPage:true});
  } finally {
    fs.writeFileSync(OUT+'/ui_scenes.json',JSON.stringify(scenes,null,2));
    const video=page.video(); await context.close();
    await video.saveAs(OUT+'/ui_raw.webm'); await browser.close();
  }
}
main().catch(e=>{console.error(e.message);process.exitCode=1});
