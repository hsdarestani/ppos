(()=>{
  const extraCss=document.createElement('link');extraCss.rel='stylesheet';extraCss.href='/static/realestate-extra.css';document.head.appendChild(extraCss);
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
    if(progress)progress.style.width=({1:33,2:66,3:100}[n]||33)+'%';
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

  const submit=document.getElementById('submitCustomerLead');
  submit&&submit.addEventListener('click',async()=>{
    const phone=(document.getElementById('customerPhone').value||'').trim();
    const name=(document.getElementById('customerName').value||'').trim();
    const error=document.getElementById('captureError');
    const success=document.getElementById('captureSuccess');
    error.textContent='';
    if(!/^09\d{9}$/.test(phone)){
      error.textContent='شماره موبایل را به شکل 09121234567 وارد کنید.';
      document.getElementById('customerPhone').focus();
      return;
    }
    submit.disabled=true;
    const old=submit.textContent;
    submit.textContent='در حال ثبت...';
    try{
      const res=await fetch(`/api/realestate/${encodeURIComponent(slug)}/lead`,{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({...state,phone,name})
      });
      const data=await res.json();
      if(!res.ok||!data.ok)throw new Error(data.error||'ثبت انجام نشد');
      track('lead_preview',{...state,customer_lead_id:data.id});
      track('phone_mock_submit',{...state});
      document.getElementById('leadPhoneMirror').textContent=phone;
      const link=document.getElementById('merchantPreviewLink');
      if(link&&data.preview_url)link.href=data.preview_url;
      success.hidden=false;
      success.scrollIntoView({behavior:'smooth',block:'nearest'});
      setTimeout(()=>document.getElementById('merchantReveal')?.scrollIntoView({behavior:'smooth',block:'center'}),900);
    }catch(err){
      error.textContent=err.message||'خطا در ثبت. دوباره تلاش کنید.';
    }finally{
      submit.disabled=false;
      submit.textContent=old;
    }
  });
})();