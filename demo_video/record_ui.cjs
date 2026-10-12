// LIVE smoke UI driver. No mocked routes/responses; every request hits Flask.
const { chromium } = require('../full_app/production_frontend/node_modules/playwright');
const fs = require('fs');
const path = require('path');
const OUT = '/srv/demo_out/demo01';
const BASE = 'http://127.0.0.1:8011';
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
    fs.writeFileSync(OUT+'/analysis.json',JSON.stringify(data,null,2));
    // Keep a concise editorial selection from the real analysis; preserve evidence.
    const good = data.clips.filter(c=>c.source==='whole_video' || c.source==='signals+vlm');
    const selected = (good.length>=4?good:data.clips).slice(0,5).map(c=>({...c,keep:true}));
    const response = await context.request.patch(BASE+'/api/jobs/'+jobId+'/clips',{data:{clips:selected}});
    if(!response.ok()) throw new Error(await response.text());
    await wait(6500);
    await scene('Real interest curve and why-this-clip evidence',async()=>{
      await page.getByRole('region',{name:'Review timeline'}).scrollIntoViewIfNeeded().catch(()=>page.locator('.timeline').scrollIntoViewIfNeeded());
    });
    await scene('Trim and reorder before export',async()=>{
      const slider = page.getByLabel('Trim start 1',{exact:true});
      await slider.scrollIntoViewIfNeeded();await slider.focus();await slider.press('ArrowRight');
      await page.getByRole('button',{name:'Move clip 1 down',exact:true}).click();
      await page.getByRole('button',{name:'Save edits',exact:true}).click();
    });
    await scene('Landscape export',async()=>{
      await page.getByLabel('Export preset',{exact:true}).selectOption('landscape');
      await page.getByRole('button',{name:/Render reel/}).click();
    });
    data = await idle();
    fs.writeFileSync(OUT+'/landscape.json',JSON.stringify(data,null,2));
    fs.copyFileSync(OUT+'/jobs/'+jobId+'/output.mp4',OUT+'/montage_landscape.mp4');
    fs.cpSync(OUT+'/jobs/'+jobId+'/share',OUT+'/share_landscape',{recursive:true});
    await scene('Share kit / covers / posting copy',async()=>{
      await page.getByRole('region',{name:'Share kit',exact:true}).scrollIntoViewIfNeeded();
    });
    await scene('Play the real rendered montage',async()=>{
      await page.locator('.output').scrollIntoViewIfNeeded();
      await page.locator('.output video').evaluate(v=>v.play());await wait(7000);
      await page.locator('.output video').evaluate(v=>v.pause());
    });
    await scene('Vertical Short export',async()=>{
      await page.getByLabel('Export preset',{exact:true}).selectOption('vertical');
      await page.getByRole('button',{name:/Render reel/}).click();
    });
    data = await idle();
    fs.writeFileSync(OUT+'/vertical.json',JSON.stringify(data,null,2));
    fs.copyFileSync(OUT+'/jobs/'+jobId+'/output.mp4',OUT+'/montage_vertical.mp4');
    fs.cpSync(OUT+'/jobs/'+jobId+'/share',OUT+'/share_vertical',{recursive:true});
    await page.screenshot({path:OUT+'/frontend.png',fullPage:true});
  } finally {
    fs.writeFileSync(OUT+'/ui_scenes.json',JSON.stringify(scenes,null,2));
    const video=page.video(); await context.close();
    await video.saveAs(OUT+'/ui_raw.webm'); await browser.close();
  }
}
main().catch(e=>{console.error(e.message);process.exitCode=1});
