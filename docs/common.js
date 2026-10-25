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
  golden:['Golden cross',1],death:['Death cross',-1],macdu:['MACD up',1],macdd:['MACD down',-1],rsi70:['RSI ≥ 70',-1],rsi30:['RSI ≤ 30',1],vol:['Volume surge',0],
  brku:['Breakout',1],brkd:['Breakdown',-1],dbot:['Double bottom',1],ihs:['Inverse H&S',1],cup:['Cup & handle',1],rbot:['Rounding bottom',1],
  tria:['Ascending triangle',1],wedf:['Falling wedge',1],flagu:['Bull flag / pennant',1],tris:['Symmetrical triangle',0],
  dtop:['Double top',-1],hs:['Head & shoulders',-1],trid:['Descending triangle',-1],wedr:['Rising wedge',-1],flagd:['Bear flag / pennant',-1],
  ...Object.fromEntries([9,21,50,100,200].flatMap(n=>[[`t${n}d`,[`At ${n}d EMA`,0]],[`t${n}w`,[`At ${n}w EMA`,0]]]))};
// EMA periods (daily and weekly) and their direction: eslope = {d9: 1 rising / -1 falling, ..., w200: ...}
const EMAS=[9,21,50,100,200];
// EMA touches are information, not trade signals: left out of the bullish / bearish counts and rankings
const isTouch=s=>/^t\d+[dw]$/.test(s.k),core=r=>(r.signals||[]).filter(s=>!isTouch(s));
const slopeWord=(r,k)=>{const s=(r.eslope||{})[k];return s>0?'rising':s<0?'falling':'n/a'};
const TREND_ORDER={up:1,side:0,down:-1};
// trend from price structure (higher highs / lows), the 50/200-day averages and ADX (scripts/patterns.py)
// plus the short-term trend from the 9 / 21-day EMAs (scripts/screen.py short_trend)
const stermText=r=>!r.sterm?'':r.sterm.dir==='up'?'short-term up':r.sterm.dir==='down'?'short-term down':'short-term mixed';
function stermCell(r){
  const s=r.sterm;if(!s)return '';
  const c=s.dir==='up'?'up':s.dir==='down'?'dn':'mu',a=s.dir==='up'?'↗ ':s.dir==='down'?'↘ ':'→ ';
  return `<small class="${c}" style="display:block;font-size:11px;font-weight:400" title="${esc(s.why)}">${a}${stermText(r)}</small>`;
}
function trendCell(r){
  const t=r.trend;if(!t)return '<span class="mu">–</span>';
  const c=t.dir==='up'?'up':t.dir==='down'?'dn':'mu',a=t.dir==='up'?'↗ ':t.dir==='down'?'↘ ':'→ ';
  return `<span class="${c}" title="${esc(t.why||'')}${t.adx!=null?' · ADX '+t.adx:''}">${a}${esc(t.label)}</span>${stermCell(r)}`;
}
const lvPct=(p,last)=>last?(p/last-1)*100:null;
// nearest support and resistance with distance from the price; hover shows the second level and the number of touches
function srCell(r){
  const s=r.sr;if(!s)return '<span class="mu">–</span>';
  const one=(x,k)=>x?`<span class="${k==='S'?'up':'dn'}">${k} ${fmt(x.p,x.p>=1000?0:2)}</span> <span class="mu">${pc(lvPct(x.p,r.last),1)}</span>`:`<span class="mu">${k} –</span>`;
  const tip=['Support: '+(s.sup||[]).map(x=>fmt(x.p,2)+' ('+x.n+' touches)').join(', '),'Resistance: '+((s.res||[]).map(x=>fmt(x.p,2)+' ('+x.n+' touches)').join(', ')||'none: at or near highs')].join(' · ');
  return `<span title="${esc(tip)}" style="white-space:nowrap">${one((s.sup||[])[0],'S')}<br>${(s.res||[]).length?one(s.res[0],'R'):'<span class="mu">R none (at highs)</span>'}</span>`;
}
const lvlWord=p=>['dtop','dbot','hs','ihs'].includes(p.k)?'neckline':'breakout level';
function patText(r){return (r.pat||[]).map(p=>`${p.name} ${p.state} (${lvlWord(p)} ${fmt(p.neck,2)}, target ${fmt(p.target,2)})`).join('; ')}
const TREND_COL=['trend','Trend',r=>`<td class="hide-sm" style="text-align:left">${trendCell(r)}</td>`,r=>r.trend?r.trend.score:null,1];
const SR_COL=['sr','Support / Resistance',r=>`<td class="hide-sm" style="text-align:left;font-size:12px">${srCell(r)}</td>`,r=>r.sr&&r.sr.sup&&r.sr.sup[0]?lvPct(r.sr.sup[0].p,r.last):null,1];

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
// Bloomberg consensus (derived numbers from bloomberg/bbg_sync.py): upside to target, % Buy ratings, 4-week EPS revision
function stCell(r){
  const s=r.st;if(!s||s.up==null&&s.buy==null)return '<span class="mu">–</span>';
  const t=`Consensus target upside ${s.up==null?'n/a':pc(s.up)} · ${s.buy==null?'n/a':s.buy+'%'} of ${s.n||'?'} analysts rate Buy · rating ${s.rt==null?'n/a':s.rt.toFixed(1)+'/5'} · next-12-month EPS estimate ${s.rev4w==null?'n/a':pc(s.rev4w)} over 4 weeks`;
  return `<span title="${esc(t)}"><span class="${cls(s.up)}">${s.up==null?'–':pc(s.up,0)}</span>${s.buy==null?'':` <span class="mu">${s.buy}%B</span>`}${s.rev4w==null?'':` <span class="${cls(s.rev4w)}" style="font-size:11px">${s.rev4w>0?'▲':s.rev4w<0?'▼':''}</span>`}</span>`;
}
const STREET_COL=['stup','Street',r=>`<td class="hide-sm">${stCell(r)}</td>`,r=>r.st?r.st.up:null,1];
const chartUrl=k=>'chart.html?k='+encodeURIComponent(k);
// the stock's name links to its chart page (stopPropagation keeps a table row's click-to-expand working)
const dqMark=r=>r.dq?` <span class="warn" title="${esc(r.dq)}. Signals for this stock may be wrong.">⚠</span>`:'';
const chartLink=(r,txt)=>`<a class="stk" href="${chartUrl(r.k)}" onclick="event.stopPropagation()" title="Open chart">${txt}</a>${dqMark(r)}`;
function rsiGauge(v){return `<span class="rsi"><b style="left:${Math.max(0,Math.min(100,v))}%"></b></span>`}
// price above (▲) or below (▼) each EMA; hover for the EMA's value and whether it is rising or falling
function maPill(r,wk=false){
  const p=n=>{const v=r[(wk?'wema':'ema')+n];if(v==null)return '';const s=(r.eslope||{})[(wk?'w':'d')+n];
    return `<span class="pill ${r.last>v?'up':'dn'}" title="${n}-${wk?'week':'day'} EMA ${fmt(v,2)}, ${s>0?'rising':s<0?'falling':'direction n/a'}">${r.last>v?'▲':'▼'} ${n}${wk?'w':''}${s>0?'↗':s<0?'↘':''}</span>`};
  return EMAS.map(p).join('');
}
const maPills=r=>`<div style="margin-bottom:3px">${maPill(r)}</div><div>${maPill(r,true)}</div>`;
// breadth and averages over a list of stock rows (each a data.json stock merged with its list item)
function stats(rows){
  rows=rows.filter(r=>!r.missing);
  const n=k=>rows.filter(r=>r[k]!=null).length, above=k=>rows.filter(r=>r[k]!=null&&r.last>r[k]).length;
  return {n:rows.length,adv:rows.filter(r=>r.pct>0).length,dec:rows.filter(r=>r.pct<0).length,
    day:avg(rows.map(r=>r.pct)),w1:avg(rows.map(r=>r.w1)),m1:avg(rows.map(r=>r.m1)),m3:avg(rows.map(r=>r.m3)),ytd:avg(rows.map(r=>r.ytd)),
    rs1:avg(rows.map(r=>r.rs1)),rs3:avg(rows.map(r=>r.rs3)),rsi:avg(rows.map(r=>r.rsi)),score:avg(rows.map(r=>r.score)),
    a50:above('ma50'),n50:n('ma50'),a200:above('ma200'),n200:n('ma200'),
    bull:rows.reduce((p,r)=>p+core(r).filter(s=>s.d>0).length,0),bear:rows.reduce((p,r)=>p+core(r).filter(s=>s.d<0).length,0),
    tup:rows.filter(r=>r.trend&&r.trend.dir==='up').length,tdn:rows.filter(r=>r.trend&&r.trend.dir==='down').length,nt:rows.filter(r=>r.trend).length};
}
function rowsOf(items,extra={}){return items.map(it=>{const s=D.stocks[it.k];return s?{...s,...it,...extra}:{...it,...extra,missing:true}})}
function lineFor(r){
  if(r.missing)return `${r.sym} (${r.label}): no data`;
  const rp=rangePos(r);
  return `${r.sym} (${r.label}): ${f2(r.last)} | day ${f2(r.pct)}% | 1W ${f2(r.w1)}% | 1M ${f2(r.m1)}% | 3M ${f2(r.m3)}% | YTD ${f2(r.ytd)}% | vs S&P 1M ${f2(r.rs1,1)} pts, 3M ${f2(r.rs3,1)} pts | 52w range pos ${rp==null?'n/a':(rp*100).toFixed(0)+'%'} (${f2(r.off_hi,1)}% from high) | vs daily EMA ${EMAS.join('/')}: ${EMAS.map(n=>r['ema'+n]==null?'n/a':(r.last>r['ema'+n]?'above':'below')+' ('+slopeWord(r,'d'+n)+')').join(', ')} | vs weekly EMA ${EMAS.join('/')}: ${EMAS.map(n=>r['wema'+n]==null?'n/a':(r.last>r['wema'+n]?'above':'below')+' ('+slopeWord(r,'w'+n)+')').join(', ')} | vs MA50/MA200: ${[r.ma50,r.ma200].map(v=>v==null?'n/a':(r.last>v?'above':'below')).join('/')} | RSI14 ${f2(r.rsi,0)} | MACD ${r.macd==null||r.macd_sig==null?'n/a':(r.macd>r.macd_sig?'above':'below')+' signal'} | ATR ${f2(r.atr_pct,1)}% | vol ${f2(r.vol_x,1)}x | trend score ${r.score==null?'n/a':r.score+'/6'} | TREND ${r.trend?r.trend.label+' ('+r.trend.why+(r.trend.adx!=null?', ADX '+r.trend.adx:'')+')':'n/a'} | SHORT-TERM TREND (EMA 9/21) ${r.sterm?r.sterm.dir+' ('+r.sterm.why+')':'n/a'} | SUPPORT ${r.sr&&r.sr.sup.length?r.sr.sup.map(x=>f2(x.p)+' ('+x.n+' touches)').join(', '):'n/a'} | RESISTANCE ${r.sr&&r.sr.res.length?r.sr.res.map(x=>f2(x.p)+' ('+x.n+' touches)').join(', '):'none (at highs)'}${(r.pat||[]).length?' | PATTERNS: '+patText(r):''} | TradingView rating ${r.tv_label?r.tv_label+' ('+f2(r.tvr)+')':'n/a'}${r.tv_industry?' | industry '+r.tv_industry:''}${r.st?` | Bloomberg consensus: target upside ${f2(r.st.up,1)}%, ${r.st.buy==null?'n/a':r.st.buy+'%'} Buy of ${r.st.n||'?'} analysts, rating ${f2(r.st.rt,1)}/5, NTM EPS estimate 4-week change ${f2(r.st.rev4w,1)}%`:''}${(r.signals||[]).length?' | SIGNALS: '+r.signals.map(s=>s.t).join('; '):''}${r.dq?' | DATA WARNING (treat as unreliable): '+r.dq:''}`;
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
  return `Data generated ${D.generated} (${g.toUTCString()}).${D.street_asof?` Bloomberg consensus as of ${D.street_asof}.`:''}${D.spx&&D.spx.intraday?' Built while the US market was OPEN: today\'s bar, volume and any signal from it are provisional.':''}`;
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
