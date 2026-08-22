(()=>{
  const cfg=window.PPOS;if(!cfg)return;
  const slug=cfg.slug, questions=cfg.questions||[], answers={};
  const sent=new Set();
  const track=(type,meta={})=>{if(sent.has(type)&&['engaged_15','engaged_30','price_viewed'].includes(type))return;if(['engaged_15','engaged_30','price_viewed'].includes(type))sent.add(type);fetch(`/api/v/${slug}/event`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({type,meta}),keepalive:true}).catch(()=>{});};
  setTimeout(()=>track('engaged_15'),15000);setTimeout(()=>track('engaged_30'),30000);
  const steps=[...document.querySelectorAll('.qstep')],bar=document.getElementById('bar');
  const max=steps.length;
  const show=n=>{steps.forEach(s=>s.classList.toggle('active',Number(s.dataset.step)===n));if(bar)bar.style.width=`${Math.min(100,(n/max)*100)}%`;if(n===2)track('campaign_started',{answers});if(n===max)track('campaign_completed',{answers});};
  document.querySelectorAll('.qstep[data-key]').forEach(step=>{
    const key=step.dataset.key, active=step.querySelector('.answer.active');if(active)answers[key]=active.dataset.value;
    step.querySelectorAll('.answer').forEach(btn=>btn.addEventListener('click',()=>{step.querySelectorAll('.answer').forEach(x=>x.classList.remove('active'));btn.classList.add('active');answers[key]=btn.dataset.value;const mirror=document.getElementById(`mirror-${key}`);if(mirror)mirror.textContent=btn.dataset.value;}));
  });
  document.querySelectorAll('[data-next]').forEach(btn=>btn.addEventListener('click',()=>show(Number(btn.dataset.next))));
  document.querySelectorAll('[data-prev]').forEach(btn=>btn.addEventListener('click',()=>show(Number(btn.dataset.prev))));
  document.querySelectorAll('[data-cta]').forEach(a=>a.addEventListener('click',()=>track('cta',{label:(a.textContent||'').trim()})));
  const offer=document.getElementById('offer');if(offer){const io=new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting)track('price_viewed');}),{threshold:.35});io.observe(offer);}
  const button=document.getElementById('captureLead'),msg=document.getElementById('captureMsg');
  button&&button.addEventListener('click',async()=>{
    const phone=(document.getElementById('customerPhone').value||'').trim(),name=(document.getElementById('customerName').value||'').trim();
    if(!/^09\d{9}$/.test(phone)){msg.textContent='شماره موبایل معتبر وارد کن.';msg.className='capturemsg error';return;}
    button.disabled=true;button.textContent='در حال ثبت...';msg.textContent='';
    try{const r=await fetch(`/api/v/${slug}/lead`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({phone,name,answers})});const data=await r.json();if(!r.ok)throw new Error(data.error||'خطا');button.textContent='لید ثبت شد ✓';msg.textContent='حالا پنل صاحب کسب‌وکار را ببین.';msg.className='capturemsg ok';setTimeout(()=>location.href=data.preview_url,650);}catch(e){button.disabled=false;button.textContent='ثبت درخواست';msg.textContent=e.message||'خطا در ثبت';msg.className='capturemsg error';}
  });
})();