(()=>{
  const slug=window.PPOS_SLUG;
  const sent=new Set();
  const track=(type,meta={})=>{
    if(!slug)return;
    const once=['engaged_15','engaged_30','scroll_50','scroll_90','price_viewed'];
    if(once.includes(type)&&sent.has(type))return;
    if(once.includes(type))sent.add(type);
    fetch('/api/event',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({slug,type,meta}),keepalive:true}).catch(()=>{});
  };

  setTimeout(()=>track('engaged_15'),15000);
  setTimeout(()=>track('engaged_30'),30000);
  addEventListener('scroll',()=>{
    const max=document.documentElement.scrollHeight-innerHeight;
    if(max<=0)return;
    const p=scrollY/max;
    if(p>.5)track('scroll_50');
    if(p>.88)track('scroll_90');
    const activation=document.getElementById('activation');
    if(activation&&activation.getBoundingClientRect().top<innerHeight*.85)track('price_viewed');
  },{passive:true});

  document.querySelectorAll('[data-track="cta"]').forEach(el=>el.addEventListener('click',()=>track('cta',{label:(el.textContent||'').trim()})));

  let state={intent:'خرید',area:'',budget:'۵ تا ۱۰ میلیارد'};
  const steps=[...document.querySelectorAll('.finder-step')];
  const progress=document.getElementById('progressBar');
  const go=n=>{
    steps.forEach(s=>s.classList.toggle('active',Number(s.dataset.step)===n));
    progress.style.width=({1:33,2:66,3:100}[n]||33)+'%';
    if(n===2)track('finder_started',{intent:state.intent});
    if(n===3){
      state.area=(document.getElementById('areaInput').value||'منطقه موردنظر').trim();
      state.budget=document.getElementById('budgetInput').value;
      document.getElementById('areaMirror1').textContent=state.area;
      document.getElementById('areaMirror2').textContent=state.area;
      document.getElementById('leadIntent').textContent=state.intent;
      document.getElementById('leadArea').textContent=state.area;
      document.getElementById('leadBudget').textContent=state.budget;
      track('finder_completed',state);
    }
  };

  document.querySelectorAll('#intentChoices .pick').forEach(btn=>btn.addEventListener('click',()=>{
    document.querySelectorAll('#intentChoices .pick').forEach(x=>x.classList.remove('active'));
    btn.classList.add('active');
    state.intent=btn.dataset.value;
  }));
  document.querySelectorAll('[data-next]').forEach(btn=>btn.addEventListener('click',()=>go(Number(btn.dataset.next))));
  document.querySelectorAll('[data-back]').forEach(btn=>btn.addEventListener('click',()=>go(Number(btn.dataset.back))));

  const showLead=document.getElementById('showLeadPreview');
  showLead&&showLead.addEventListener('click',()=>{
    const reveal=document.getElementById('merchantReveal');
    track('lead_preview',state);
    reveal.scrollIntoView({behavior:'smooth',block:'center'});
    const phone=reveal.querySelector('.lead-phone');
    phone.animate([{transform:'scale(.97)',boxShadow:'0 20px 60px #0005'},{transform:'scale(1.02)'},{transform:'scale(1)'}],{duration:650,easing:'ease-out'});
  });
})();