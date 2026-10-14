// Shared helpers for the three pages (home, theme, signals). Data comes from data.json, written by scripts/screen.py.
const fmt=(v,d=2)=>v==null||isNaN(v)?'–':v.toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d});
const pc=(v,d=1)=>v==null||isNaN(v)?'–':(v>0?'+':'')+v.toFixed(d)+'%';
const pts=(v,d=1)=>v==null||isNaN(v)?'–':(v>0?'+':'')+v.toFixed(d)+' pts';
const cls=v=>v==null?'':v>0?'up':v<0?'dn':'';
const arrow=v=>v==null?'':v>0?'▲ ':v<0?'▼ ':'';
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const slug=s=>s.toLowerCase().replace(/[^a-z0-9]+/g,'-');
const avg=a=>{const x=a.filter(v=>v!=null&&!isNaN(v));return x.length?x.reduce((p,c)=>p+c,0)/x.length:null};
const rangePos=r=>r.hi52>r.lo52?(r.last-r.lo52)/(r.hi52-r.lo52):null;
const rsiCls=v=>v>=70?'warn':v<=30?'cool':'';
const f2=(v,x=2)=>v==null?'n/a':v.toFixed(x);

// signal types: key -> [short label for filter chips, bullish?]
const SIGNALS={hi52:['52w high',1],lo52:['52w low',-1],x200u:['Above 200d',1],x200d:['Below 200d',-1],x50u:['Above 50d',1],x50d:['Below 50d',-1],
  golden:['Golden cross',1],death:['Death cross',-1],macdu:['MACD up',1],macdd:['MACD down',-1],rsi70:['RSI ≥ 70',-1],rsi30:['RSI ≤ 30',1],vol:['Volume surge',0]};

function spark(a){
  if(!a||a.length<2)return '';
  const mn=Math.min(...a),mx=Math.max(...a),w=70,h=20,rg=(mx-mn)||1;
  const p=a.map((v,i)=>[(i/(a.length-1))*w,h-2-((v-mn)/rg)*(h-4)].map(x=>x.toFixed(1)).join(',')).join(' ');
  return `<svg class="spark" viewBox="0 0 ${w} ${h}"><polyline fill="none" stroke="currentColor" stroke-width="1.5" points="${p}"/></svg>`;
}
function scoreBar(s){
  if(s==null)return '<span class="mu">–</span>';
  const c=s>=4?'':s<=2?'lo':'mid';
  return `<span class="score ${c}" title="Trend score ${s}/6">${[0,1,2,3,4,5].map(i=>`<i class="${i<s?'on':''}"></i>`).join('')}</span> <span class="mu">${s}</span>`;
}
function sigChips(r,max=9){
  return (r.signals||[]).slice(0,max).map(s=>`<span class="sig ${s.d>0?'b':s.d<0?'s':''}">${esc(s.t)}</span>`).join('');
}
// TradingView technical rating (-1..+1, from its screener): label plus moving-average / oscillator parts on hover
function tvCell(r){
  if(r.tv_label==null)return '<span class="mu">–</span>';
  const k=r.tvr>0.1?'up':r.tvr<-0.1?'dn':'mu';
  return `<span class="${k}" title="TradingView rating ${r.tvr.toFixed(2)} · moving averages ${f2(r.tv_ma)} · oscillators ${f2(r.tv_osc)}">${esc(r.tv_label)}</span>`;
}
function rsiGauge(v){return `<span class="rsi"><b style="left:${Math.max(0,Math.min(100,v))}%"></b></span>`}
function maPill(r){
  const p=(v,l)=>v==null?'':`<span class="pill ${r.last>v?'up':'dn'}">${r.last>v?'▲':'▼'} ${l}</span>`;
  return p(r.ma50,'50d')+p(r.ma200,'200d');
}
// breadth and averages over a list of stock rows (each a data.json stock merged with its list item)
function stats(rows){
  rows=rows.filter(r=>!r.missing);
  const n=k=>rows.filter(r=>r[k]!=null).length, above=k=>rows.filter(r=>r[k]!=null&&r.last>r[k]).length;
  return {n:rows.length,adv:rows.filter(r=>r.pct>0).length,dec:rows.filter(r=>r.pct<0).length,
    day:avg(rows.map(r=>r.pct)),w1:avg(rows.map(r=>r.w1)),m1:avg(rows.map(r=>r.m1)),m3:avg(rows.map(r=>r.m3)),ytd:avg(rows.map(r=>r.ytd)),
    rs1:avg(rows.map(r=>r.rs1)),rs3:avg(rows.map(r=>r.rs3)),rsi:avg(rows.map(r=>r.rsi)),score:avg(rows.map(r=>r.score)),
    a50:above('ma50'),n50:n('ma50'),a200:above('ma200'),n200:n('ma200'),
    bull:rows.reduce((p,r)=>p+(r.signals||[]).filter(s=>s.d>0).length,0),bear:rows.reduce((p,r)=>p+(r.signals||[]).filter(s=>s.d<0).length,0)};
}
function rowsOf(items,extra={}){return items.map(it=>{const s=D.stocks[it.k];return s?{...s,...it,...extra}:{...it,...extra,missing:true}})}
function lineFor(r){
  if(r.missing)return `${r.sym} (${r.label}): no data`;
  const rp=rangePos(r);
  return `${r.sym} (${r.label}): ${f2(r.last)} | day ${f2(r.pct)}% | 1W ${f2(r.w1)}% | 1M ${f2(r.m1)}% | 3M ${f2(r.m3)}% | YTD ${f2(r.ytd)}% | vs S&P 1M ${f2(r.rs1,1)} pts, 3M ${f2(r.rs3,1)} pts | 52w range pos ${rp==null?'n/a':(rp*100).toFixed(0)+'%'} (${f2(r.off_hi,1)}% from high) | ${r.ma50==null?'':(r.last>r.ma50?'above':'below')+' 50d'} ${r.ma200==null?'':(r.last>r.ma200?'above':'below')+' 200d'} | RSI14 ${f2(r.rsi,0)} | MACD ${r.macd==null||r.macd_sig==null?'n/a':(r.macd>r.macd_sig?'above':'below')+' signal'} | ATR ${f2(r.atr_pct,1)}% | vol ${f2(r.vol_x,1)}x | trend score ${r.score==null?'n/a':r.score+'/6'} | TradingView rating ${r.tv_label?r.tv_label+' ('+f2(r.tvr)+')':'n/a'}${r.tv_industry?' | industry '+r.tv_industry:''}${(r.signals||[]).length?' | SIGNALS: '+r.signals.map(s=>s.t).join('; '):''}`;
}
function header(title,back){
  document.body.insertAdjacentHTML('afterbegin',`<header><h1>${esc(title)}</h1>
   <div class="stamp">${back||''}<a href="https://alternateken.github.io/macro-updates/">Macro dashboard</a> &nbsp;·&nbsp; <span id="stamp">Loading…</span></div></header>
   <div class="banner" id="banner"></div><nav id="nav"></nav>`);
}
function copyBlock(id,title){
  return `<section id="${id}"><h2>${esc(title)} (free with your Claude Pro chat)</h2>
   <button class="copy" data-copy="${id}">Copy brief for Claude</button> <span class="note copymsg"></span>
   <div class="note">1) Press the button. 2) Open <a href="https://claude.ai/new" target="_blank" rel="noopener" style="color:var(--acc)">claude.ai/new</a>. 3) Paste (Ctrl+V or Cmd+V) and press Enter.</div></section>`;
}
function wireCopy(textFn){
  document.querySelectorAll('button[data-copy]').forEach(b=>b.addEventListener('click',async()=>{
    const t=textFn(b.dataset.copy),m=b.parentNode.querySelector('.copymsg');
    try{await navigator.clipboard.writeText(t);m.textContent=' Copied! Now paste it into Claude.'}
    catch(e){const ta=document.createElement('textarea');ta.value=t;document.body.appendChild(ta);ta.select();
      try{document.execCommand('copy');m.textContent=' Copied! Now paste it into Claude.'}catch(_){m.textContent=' Copy blocked by your browser.'}ta.remove()}
  }));
}
function freshness(){
  const g=new Date(D.generated);
  return `Data generated ${D.generated} (${g.toUTCString()}).${D.spx&&D.spx.intraday?' Built while the US market was OPEN: today\'s bar, volume and any signal from it are provisional.':''}`;
}
function errorsBlock(){
  if(!D.errors||!D.errors.length)return '';
  return `<details style="margin-top:8px"><summary>${D.errors.length} data warnings (tickers Yahoo could not find, etc.)</summary><div class="errs">${esc(D.errors.join('\n'))}</div></details>`;
}
let D=null;
function load(cb){
  fetch('data.json?'+Date.now()).then(r=>{if(!r.ok)throw new Error('data.json not found yet - run the workflow once');return r.json()}).then(d=>{
    D=d;const gen=new Date(d.generated);
    document.getElementById('stamp').textContent='Data refreshed '+gen.toLocaleString([],{weekday:'short',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',timeZoneName:'short'})+' · Yahoo Finance'+(d.spx&&d.spx.intraday?' · intraday':'');
    const age=(Date.now()-gen)/36e5;
    if(age>30){const b=document.getElementById('banner');b.style.display='block';b.textContent=`Warning: this data is ${Math.round(age)} hours old. The automatic refresh may have failed (check the Actions tab in GitHub).`}
    cb();
  }).catch(e=>{document.getElementById('stamp').textContent='Could not load data.json: '+e.message;console.error(e)});
}
// generic sortable table: cols = [[key, label, cellFn(r), sortFn(r) or null, hideOnPhone]]
function sortRows(rows,st,cols){
  if(!st.k)return rows;
  const c=cols.find(c=>c[0]===st.k),f=c&&c[3]?c[3]:(r=>r[st.k]);
  return rows.slice().sort((a,b)=>{const x=f(a),y=f(b);
    if(x==null&&y==null)return 0;if(x==null)return 1;if(y==null)return -1;
    return (typeof x==='string'?x.localeCompare(y):x-y)*st.dir});
}
