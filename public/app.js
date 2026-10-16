const $=(s,r=document)=>r.querySelector(s), $$=(s,r=document)=>[...r.querySelectorAll(s)];
const state={categories:[],items:[],watch:[],top:null,view:'dashboard',topSort:'opportunity'};
const months=['Janvier','Février','Mars','Avril','Mai','Juin','Juillet','Août','Septembre','Octobre','Novembre','Décembre'];
const platformColors={Vinted:'#5f8d79',Leboncoin:'#b56d3b',eBay:'#746c92',Autre:'#9a9a91'};
const statusLabels={en_vente:'En vente',reserve:'Réservé',vente_en_cours:'Vente en cours',vente_finalisee:'Vente finalisée',retire:'Retiré'};
const displayStatus=i=>Number(i.pending_quantity)>0?'vente_en_cours':i.status==='vendu'?'vente_finalisee':i.status;
const today=()=>new Date().toISOString().slice(0,10);
const euro=n=>new Intl.NumberFormat('fr-FR',{style:'currency',currency:'EUR'}).format(Number(n||0));
const escapeHtml=s=>String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const fmtDate=s=>s?new Date(s+'T12:00:00').toLocaleDateString('fr-FR'):'—';

async function api(path,options={}){
  const res=await fetch(path,{headers:{'Content-Type':'application/json',...(options.headers||{})},...options});
  if(res.status===401){showAuth(false);throw new Error('Votre session a expiré.');}
  const content=res.headers.get('content-type')||'';
  const data=content.includes('json')?await res.json():await res.blob();
  if(!res.ok)throw new Error(data.error||'Une erreur est survenue.');
  return data;
}
function toast(message,error=false){const el=document.createElement('div');el.className='toast'+(error?' error':'');el.textContent=message;$('#toast-zone').append(el);setTimeout(()=>el.remove(),3800)}
function openModal(html){
  $('#modal-content').innerHTML=html;
  $('#modal').classList.remove('hidden');
  document.body.classList.add('modal-open');
}
function closeModal(){
  // Safari iOS conserve parfois le zoom appliqué à un champ encore actif.
  // Retirer le focus avant de masquer la modale rend immédiatement le
  // tableau de bord à sa largeur normale.
  if($('#modal').contains(document.activeElement))document.activeElement.blur();
  $('#modal').classList.add('hidden');
  $('#modal-content').innerHTML='';
  document.body.classList.remove('modal-open');
}
document.addEventListener('click',e=>{if(e.target.matches('[data-close]'))closeModal();});

async function boot(){
  const auth=await api('/api/auth/state');
  if(!auth.configured)return showAuth(true);
  if(!auth.authenticated)return showAuth(false);
  await enterApp();
}
function showAuth(setup){
  $('#app').classList.add('hidden');$('#auth').classList.remove('hidden');
  $('#auth-title').textContent=setup?'Créer votre espace privé':'Bienvenue';
  $('#auth-copy').textContent=setup?'Choisissez un mot de passe d’au moins 8 caractères. Un code de récupération vous sera remis.':'Saisissez votre mot de passe pour accéder à votre boutique.';
  $('#auth-form').dataset.mode=setup?'setup':'login';
  $('#recover-toggle').classList.toggle('hidden',setup);
}
$('#auth-form').addEventListener('submit',async e=>{
  e.preventDefault();const mode=e.currentTarget.dataset.mode;
  try{const result=await api('/api/auth/'+mode,{method:'POST',body:JSON.stringify({password:$('#auth-password').value})});
    if(result.recovery)showRecovery(result.recovery);else await enterApp();
  }catch(err){toast(err.message,true)}
});
$('#recover-toggle').addEventListener('click',()=>$('#recover-form').classList.toggle('hidden'));
$('#recover-form').addEventListener('submit',async e=>{e.preventDefault();try{const r=await api('/api/auth/recover',{method:'POST',body:JSON.stringify({recovery:$('#recovery-code').value,password:$('#recovery-password').value})});showRecovery(r.recovery)}catch(err){toast(err.message,true)}});
function showRecovery(code){openModal(`<p class="eyebrow accent">À CONSERVER</p><h2>Votre code de récupération</h2><p class="muted">Notez ce code dans un endroit sûr. Il permet de créer un nouveau mot de passe sans e-mail.</p><div style="font:800 24px Manrope;letter-spacing:.08em;text-align:center;padding:22px;background:#f0ece4;border-radius:12px;margin:22px 0">${code}</div><button id="recovery-done" class="btn primary wide">J’ai conservé ce code</button>`);$('#recovery-done').onclick=async()=>{closeModal();await enterApp()}}
async function enterApp(){
  $('#auth').classList.add('hidden');$('#app').classList.remove('hidden');
  state.categories=await api('/api/categories');fillCategorySelects();
  const year=new Date().getFullYear();$('#dash-year').innerHTML=[-2,-1,0,1].map(o=>`<option ${o===0?'selected':''}>${year+o}</option>`).join('');
  $('#dash-month').innerHTML=months.map((m,i)=>`<option value="${i+1}" ${i===new Date().getMonth()?'selected':''}>${m}</option>`).join('');
  const start=new Date(year,0,1);$('#accounting-start').value=start.toISOString().slice(0,10);$('#accounting-end').value=today();
  await Promise.all([loadDashboard(),loadItems(),loadWatch()]);
}
function fillCategorySelects(){const opts=state.categories.map(c=>`<option value="${c.id}">${escapeHtml(c.name)}</option>`).join('');$('#items-category').innerHTML='<option value="">Toutes les catégories</option>'+opts}

$$('#nav button[data-view]').forEach(b=>b.addEventListener('click',()=>navigate(b.dataset.view)));
$$('[data-go]').forEach(b=>b.addEventListener('click',()=>navigate(b.dataset.go)));
async function navigate(view){
  state.view=view;$$('.view').forEach(v=>v.classList.remove('active'));$(`#${view}-view`).classList.add('active');
  $$('#nav button').forEach(b=>b.classList.toggle('active',b.dataset.view===view));$('.sidebar').classList.remove('open');
  const headings={dashboard:['TABLEAU DE BORD','Bonjour Dadou 👋'],items:['INVENTAIRE','Mes articles'],top:['ANALYSE','Top ventes'],watch:['SOURCING','À rechercher'],accounting:['LIVRE DE COMPTE','Comptabilité'],telegram:['AUTOMATISATION','Telegram'],projections:['SIMULATION','Projections']};
  $('#page-heading').innerHTML=`<p class="eyebrow">${headings[view][0]}</p><h1>${headings[view][1]}</h1>`;
  if(view==='dashboard')await loadDashboard();if(view==='items')await loadItems();if(view==='top')await loadTop();if(view==='watch')await loadWatch();if(view==='accounting')await loadAccounting();if(view==='telegram')await loadTelegram();
}
$('#mobile-menu').onclick=()=>$('.sidebar').classList.toggle('open');
$('#lock-btn').onclick=async()=>{try{await api('/api/auth/logout',{method:'POST',body:'{}'})}finally{location.reload()}};
$('#backup-btn').onclick=()=>{location.href='/api/backup';toast('Sauvegarde préparée.')};

async function loadDashboard(){
  const y=$('#dash-year').value||new Date().getFullYear(),m=$('#dash-month').value||new Date().getMonth()+1;
  const d=await api(`/api/dashboard?year=${y}&month=${m}`);renderDashboard(d);
}
$('#dash-year').onchange=loadDashboard;$('#dash-month').onchange=loadDashboard;
function renderDashboard(d){
  const cards=[['Argent dépensé',d.year.spent,'↙','#f4e9de','#a86236',`${d.year.purchased_count} achat${d.year.purchased_count>1?'s':''}`],['Argent encaissé',d.year.revenue,'↗','#e4eee8','#486b5b',`${d.year.sold_count} vente${d.year.sold_count>1?'s':''}`],['Marge réalisée',d.year.margin,'＋','#eee9f3','#746c92',`Moyenne ${euro(d.year.average_margin)}`],['Valeur du stock',d.stock.cost,'◇','#e7edf1','#5e7890',`${d.stock.count} article${d.stock.count>1?'s':''} disponible${d.stock.count>1?'s':''}`]];
  $('#year-kpis').innerHTML=cards.map(c=>`<div class="kpi" style="--tint:${c[3]};--tone:${c[4]}"><div class="kpi-top"><span>${c[0]} · ${d.selected_year}</span><i class="kpi-icon">${c[2]}</i></div><strong>${euro(c[1])}</strong><small>${c[5]}</small></div>`).join('');
  const max=Math.max(1,...d.monthly.flatMap(x=>[x.spent,x.revenue,Math.max(0,x.margin)]));
  $('#bar-chart').innerHTML=d.monthly.map((x,i)=>`<div class="bar-month" title="${months[i]} — achats ${euro(x.spent)}, ventes ${euro(x.revenue)}, marge ${euro(x.margin)}"><span class="p" style="height:${x.spent/max*100}%"></span><span class="r" style="height:${x.revenue/max*100}%"></span><span class="m" style="height:${Math.max(0,x.margin)/max*100}%"></span><label>${months[i].slice(0,3)}</label></div>`).join('');
  renderDonut(d.platforms);
  $('#month-title').textContent=`${months[d.selected_month-1]} ${d.selected_year}`;
  $('#month-kpis').innerHTML=[['Dépensé',d.month.spent],['Encaissé',d.month.revenue],['Marge',d.month.margin],['Articles vendus',d.month.sold_count]].map((x,i)=>`<div class="mini-kpi"><span>${x[0]}</span><strong>${i===3?x[1]:euro(x[1])}</strong></div>`).join('');
  $('#recent-list').innerHTML=d.recent.length?d.recent.map(r=>`<div class="recent-row"><span class="recent-icon">${r.kind==='vente'?'✓':r.kind==='vente_en_cours'?'…':'↙'}</span><div><strong>${escapeHtml(r.label)}</strong><small>${fmtDate(r.occurred_on)}</small></div><b class="${r.kind==='vente'?'margin-positive':''}">${r.kind==='vente'?'+':r.kind==='achat'?'−':'≈'}${euro(r.amount)}</b></div>`).join(''):'<div class="empty">Vos premières opérations apparaîtront ici.</div>';
  $('#nav-stock').textContent=d.stock.count;
}
function renderDonut(rows){
  const total=rows.reduce((s,r)=>s+r.count,0);let at=0;const gradients=[];
  rows.forEach(r=>{const from=total?at/total*360:0;at+=r.count;const to=total?at/total*360:0;gradients.push(`${platformColors[r.platform]} ${from}deg ${to}deg`)});
  const bg=gradients.length?`conic-gradient(${gradients.join(',')})`:'#ebe7df';
  $('#donut-wrap').innerHTML=`<div class="donut" style="background:${bg}"><div class="donut-center"><strong>${total}</strong><small>ventes</small></div></div><div class="platform-legend">${rows.length?rows.map(r=>`<div class="platform-row"><span style="background:${platformColors[r.platform]}"></span><span>${r.platform}</span><b>${Math.round(r.count/total*100)}%</b></div>`).join(''):'<p class="muted">Aucune vente cette année.</p>'}</div>`;
}

async function loadItems(){
  const p=new URLSearchParams({search:$('#items-search').value,status:$('#items-status').value,category:$('#items-category').value});
  state.items=await api('/api/items?'+p);renderItems();
}
let itemSearchTimer;$('#items-search').oninput=()=>{clearTimeout(itemSearchTimer);itemSearchTimer=setTimeout(loadItems,220)};$('#items-status').onchange=loadItems;$('#items-category').onchange=loadItems;
$('#global-search').addEventListener('keydown',async e=>{if(e.key==='Enter'){await navigate('items');$('#items-search').value=e.target.value;await loadItems();if(state.items.length===1)showItem(state.items[0].id)}});
document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){e.preventDefault();$('#global-search').focus()}if(e.key==='Escape')closeModal()});
function renderItems(){
  const groups=[
    {key:'pending',title:'Ventes en cours',copy:'Transactions à confirmer après réception du paiement ou fin de la vente.',items:state.items.filter(i=>displayStatus(i)==='vente_en_cours')},
    {key:'stock',title:'Articles en stock',copy:'Articles disponibles, réservés ou temporairement retirés.',items:state.items.filter(i=>['en_vente','reserve','retire'].includes(displayStatus(i)))},
    {key:'done',title:'Ventes finalisées',copy:'Historique des ventes intégrées à vos résultats.',items:state.items.filter(i=>displayStatus(i)==='vente_finalisee')}
  ];
  const row=i=>{const st=displayStatus(i),quant=i.inventory_mode==='quantity',canSell=['en_vente','reserve'].includes(i.status)&&!Number(i.pending_quantity)&&Number(i.available_quantity)>0;return `<tr><td><div class="item-main"><span class="item-icon">${escapeHtml(i.designation.slice(0,1).toUpperCase())}</span><div><strong>${escapeHtml(i.designation)}</strong><small>${i.code}${i.serial_number?' · '+escapeHtml(i.serial_number):''}${quant?` · ${i.available_quantity} disponible(s) sur ${i.initial_quantity}`:''}</small></div></div></td><td>${escapeHtml(i.category_name||'—')}</td><td>${euro(i.purchase_price)}<br><small class="muted">${quant?`${euro(i.unit_cost)} / unité · `:''}${fmtDate(i.purchase_date)}</small></td><td>${Number(i.list_price)>0?euro(i.list_price):'<span class="muted">Variable</span>'}</td><td><span class="status ${st}">${statusLabels[st]}</span></td><td>${st==='vente_finalisee'?`<span class="margin-positive">+${euro(i.margin)}</span><br><small class="muted">${i.platform}${quant?` · ${i.sale_quantity} unité(s)`:''}</small>`:st==='vente_en_cours'?`<span>${euro(i.sale_price)}</span><br><small class="muted">En attente · ${i.platform}${quant?` · ${i.sale_quantity} unité(s)`:''}</small>`:'—'}</td><td><div class="table-actions">${canSell?`<button class="tiny-btn sell" data-sell="${i.id}">Vendre</button>`:''}${st==='vente_en_cours'?`<button class="tiny-btn sell" data-finalize="${i.id}">Finaliser</button>`:''}<button class="tiny-btn" data-detail="${i.id}">Voir</button></div></td></tr>`};
  const table=g=>`<section class="inventory-group ${g.key}"><div class="inventory-group-head"><div><h3>${g.title}</h3><p>${g.copy}</p></div><span>${g.items.length}</span></div><div class="card table-card"><div class="table-scroll"><table><thead><tr><th>Article</th><th>Catégorie</th><th>Achat</th><th>Prix affiché</th><th>Statut</th><th>Résultat</th><th></th></tr></thead><tbody>${g.items.length?g.items.map(row).join(''):`<tr><td colspan="7" class="group-empty">Aucun élément dans cette section.</td></tr>`}</tbody></table></div></div></section>`;
  $('#items-groups').innerHTML=groups.map(table).join('');
  $('#items-empty').classList.toggle('hidden',state.items.length>0);$('#items-empty').innerHTML='<strong>Aucun article trouvé</strong><p>Ajoutez votre premier article ou modifiez les filtres.</p>';
  $$('[data-detail]').forEach(b=>b.onclick=()=>showItem(Number(b.dataset.detail)));$$('[data-sell]').forEach(b=>b.onclick=()=>showSell(Number(b.dataset.sell)));$$('[data-finalize]').forEach(b=>b.onclick=()=>finalizeSale(Number(b.dataset.finalize)));
}
$$('[data-add],#quick-add').forEach(b=>b.onclick=showAddChoice);
function categoryOptions(selected=''){return state.categories.map(c=>`<option value="${c.id}" ${String(c.id)===String(selected)?'selected':''}>${escapeHtml(c.name)}</option>`).join('')}
function showAddChoice(){
  openModal(`<p class="eyebrow accent">NOUVELLE ENTRÉE</p><h2>Que souhaitez-vous ajouter ?</h2><p class="muted">Choisissez le fonctionnement adapté à votre achat.</p><div class="entry-choices"><button class="entry-choice" id="choice-single"><strong>Article unique</strong><span>Un article acheté et revendu individuellement.</span></button><button class="entry-choice" id="choice-batch"><strong>Lot d’articles distincts</strong><span>Plusieurs fiches créées d’un coup, avec le prix global réparti automatiquement.</span></button><button class="entry-choice" id="choice-quantity"><strong>Stock en quantité</strong><span>Un seul produit vendu progressivement, par exemple un lot de journaux.</span></button></div>`);
  $('#choice-single').onclick=()=>showItemForm();$('#choice-batch').onclick=showBatchForm;$('#choice-quantity').onclick=()=>showItemForm(null,'quantity');
}
function attachCategoryCreator(formSelector){
  $('#new-category').onclick=async()=>{const name=prompt('Nom de la nouvelle catégorie :');if(!name?.trim())return;try{const created=await api('/api/categories',{method:'POST',body:JSON.stringify({name:name.trim()})});state.categories=await api('/api/categories');fillCategorySelects();const select=$(`${formSelector} select[name="category_id"]`);select.innerHTML='<option value="">Sélectionner…</option>'+categoryOptions(created.id);select.value=created.id;toast('Catégorie ajoutée.')}catch(err){toast(err.message,true)}};
}
function showItemForm(item=null,mode='single'){
  mode=item?.inventory_mode||mode;const quantified=mode==='quantity';
  openModal(`<p class="eyebrow accent">${item?'MODIFIER':'NOUVEL ARTICLE'}</p><h2>${item?'Mettre à jour la fiche':quantified?'Ajouter un stock en quantité':'Ajouter un article en vente'}</h2><p class="muted">Les champs marqués d’un astérisque sont obligatoires.</p><form id="item-form" class="form-grid">
  <input type="hidden" name="inventory_mode" value="${mode}">
  <label class="span-2">Désignation *<input name="designation" value="${escapeHtml(item?.designation||'')}" required placeholder="Ex. Nintendo Switch OLED blanche"></label>
  <label class="span-2">Catégorie *<select name="category_id" required><option value="">Sélectionner…</option>${categoryOptions(item?.category_id)}</select><button id="new-category" class="text-btn" type="button">＋ Nouvelle catégorie</button></label>
  ${quantified?`<label>Quantité initiale *<input name="initial_quantity" type="number" min="1" step="1" value="${item?.initial_quantity??''}" ${item?'readonly':''} required></label>`:'<input type="hidden" name="initial_quantity" value="1">'}
  <label>${quantified?'Prix d’achat global':'Prix d’achat'} *<input name="purchase_price" type="number" min="0" step="0.01" value="${item?.purchase_price??''}" required></label>
  <label>${quantified?'Prix affiché unitaire (facultatif)':'Prix affiché *'}<input name="list_price" type="number" min="0" step="0.01" value="${item?.list_price??''}" ${quantified?'':'required'}></label>
  <label>Date d’achat *<input name="purchase_date" type="date" value="${item?.purchase_date||today()}" required></label>
  <label>Date de mise en ligne *<input name="listed_date" type="date" value="${item?.listed_date||today()}" required></label>
  <label class="span-2">N° de série<input name="serial_number" value="${escapeHtml(item?.serial_number||'')}" placeholder="Il restera retrouvable depuis la recherche globale"></label>
  <label class="span-2">Observations<textarea name="notes" placeholder="État, accessoires, provenance, informations utiles…">${escapeHtml(item?.notes||'')}</textarea></label>
  <div class="form-actions"><button type="button" class="btn secondary" data-close>Annuler</button><button class="btn primary" type="submit">${item?'Enregistrer':'Ajouter à la boutique'}</button></div></form>`);
  attachCategoryCreator('#item-form');
  $('#item-form').onsubmit=async e=>{e.preventDefault();const payload=Object.fromEntries(new FormData(e.target));try{await api('/api/items'+(item?'/'+item.id:''),{method:'POST',body:JSON.stringify(payload)});closeModal();toast(item?'Article mis à jour.':'Article ajouté à la boutique.');await Promise.all([loadItems(),loadDashboard()])}catch(err){toast(err.message,true)}};
}
function showBatchForm(){
  openModal(`<p class="eyebrow accent">LOT D’ARTICLES DISTINCTS</p><h2>Créer plusieurs articles</h2><p class="muted">Le prix global sera réparti au centime près. Chaque article peut avoir sa propre catégorie.</p><form id="batch-form" class="form-grid"><label class="span-2">Nom du lot<input name="name" placeholder="Ex. Lot brocante du dimanche"></label><label>Prix d’achat global *<input name="total_price" type="number" min="0" step="0.01" required></label><label>Date d’achat *<input name="purchase_date" type="date" value="${today()}" required></label><label>Date de mise en ligne *<input name="listed_date" type="date" value="${today()}" required></label><div class="span-2"><div class="batch-head"><span class="eyebrow">ARTICLES DU LOT</span><div><button type="button" id="new-batch-category" class="text-btn">＋ Nouvelle catégorie</button><button type="button" id="add-batch-row" class="text-btn">＋ Ajouter une ligne</button></div></div><div id="batch-rows"></div></div><div class="form-actions"><button type="button" class="btn secondary" data-close>Annuler</button><button class="btn primary">Créer toutes les fiches</button></div></form>`);
  const addRow=()=>{const row=document.createElement('div');row.className='batch-row';row.innerHTML=`<input data-field="designation" required placeholder="Désignation de l’article"><select data-field="category_id" required><option value="">Catégorie…</option>${categoryOptions()}</select><input data-field="list_price" type="number" min="0" step="0.01" placeholder="Prix affiché"><input data-field="serial_number" placeholder="N° de série"><button type="button" class="tiny-btn danger">×</button>`;row.querySelector('button').onclick=()=>{if($$('.batch-row').length>1)row.remove()};$('#batch-rows').append(row)};
  addRow();addRow();$('#add-batch-row').onclick=addRow;
  $('#new-batch-category').onclick=async()=>{const name=prompt('Nom de la nouvelle catégorie :');if(!name?.trim())return;try{const created=await api('/api/categories',{method:'POST',body:JSON.stringify({name:name.trim()})});state.categories=await api('/api/categories');fillCategorySelects();$$('.batch-row select[data-field="category_id"]').forEach(select=>{const value=select.value;select.innerHTML='<option value="">Catégorie…</option>'+categoryOptions();select.value=value});toast(`Catégorie « ${created.name} » ajoutée.`)}catch(err){toast(err.message,true)}};
  $('#batch-form').onsubmit=async e=>{e.preventDefault();const fd=new FormData(e.target),payload=Object.fromEntries(fd);payload.items=$$('.batch-row').map(row=>Object.fromEntries([...row.querySelectorAll('[data-field]')].map(input=>[input.dataset.field,input.value])));try{const result=await api('/api/batches',{method:'POST',body:JSON.stringify(payload)});closeModal();toast(`${result.item_count} fiches créées, prix du lot réparti.`);await Promise.all([loadItems(),loadDashboard()])}catch(err){toast(err.message,true)}};
}
async function showItem(id){
  const i=await api('/api/items/'+id);
  const sales=i.inventory_mode==='quantity'?await api(`/api/items/${id}/sales`):[];
  const st=displayStatus(i);
  const quant=i.inventory_mode==='quantity',canSell=['en_vente','reserve'].includes(i.status)&&!Number(i.pending_quantity)&&Number(i.available_quantity)>0;
  const history=quant?`<div class="sale-history"><h3>Ventes enregistrées</h3>${sales.filter(s=>!s.cancelled_at).length?sales.filter(s=>!s.cancelled_at).map(s=>`<div class="sale-history-row"><div><strong>${s.quantity} unité(s) · ${escapeHtml(s.platform)}</strong><small>${fmtDate(s.sale_date)} · ${s.finalized_at?'Finalisée':'En cours'}</small></div><div><strong>${euro(s.sale_price)}</strong><small class="${s.finalized_at?'margin-positive':''}">Marge ${euro(s.margin)}</small></div></div>`).join(''):'<p class="muted">Aucune vente enregistrée.</p>'}</div>`:'';
  openModal(`<p class="eyebrow accent">${i.code}</p><h2>${escapeHtml(i.designation)}</h2><p><span class="status ${st}">${statusLabels[st]}</span></p><div class="detail-grid"><div class="detail"><small>${quant?'Achat global':'Prix d’achat'}</small><strong>${euro(i.purchase_price)}</strong>${quant?`<small>${euro(i.unit_cost)} / unité</small>`:''}</div><div class="detail"><small>Prix affiché</small><strong>${Number(i.list_price)>0?euro(i.list_price):'Variable'}</strong></div>${quant?`<div class="detail"><small>Stock disponible</small><strong>${i.available_quantity} / ${i.initial_quantity}</strong></div><div class="detail"><small>Déjà vendu</small><strong>${i.sold_quantity} unité(s)</strong></div>`:''}<div class="detail"><small>Mise en ligne</small><strong>${fmtDate(i.listed_date)}</strong></div><div class="detail"><small>N° de série</small><strong>${escapeHtml(i.serial_number||'Non renseigné')}</strong></div>${i.sale_id?`<div class="detail"><small>${st==='vente_en_cours'?'Vente en cours':'Dernière vente'} sur ${i.platform}</small><strong>${euro(i.sale_price)}</strong></div><div class="detail"><small>${st==='vente_finalisee'?'Marge réalisée':'Marge prévue'}</small><strong class="${st==='vente_finalisee'?'margin-positive':''}">${euro(i.margin)}</strong></div>`:''}</div>${i.notes?`<p class="muted">${escapeHtml(i.notes)}</p>`:''}${history}<div class="modal-action-row"><button id="edit-item" class="btn secondary">Modifier</button>${canSell?`<button id="sell-item" class="btn primary">${quant?'Enregistrer une vente partielle':'Passer en vente en cours'}</button>`:''}${st==='vente_en_cours'?`<button id="finalize-item" class="btn primary">✓ Vente finalisée</button>`:''}${!quant&&i.status==='en_vente'?`<button id="reserve-item" class="btn secondary">Réserver</button>`:''}${!quant&&i.status==='reserve'?`<button id="unreserve-item" class="btn secondary">Remettre en vente</button>`:''}${!quant&&['en_vente','reserve'].includes(i.status)?`<button id="retire-item" class="btn secondary">Retirer de la vente</button>`:''}${!quant&&i.status==='retire'?`<button id="unretire-item" class="btn secondary">Remettre en vente</button>`:''}${st==='vente_finalisee'?`<button id="watch-item" class="btn secondary">◎ À rechercher</button>`:''}${st==='vente_en_cours'?`<button id="cancel-sale" class="btn danger">Annuler la vente en cours</button>`:''}<button id="archive-item" class="btn danger">Archiver</button></div>`);
  $('#edit-item').onclick=()=>showItemForm(i);if($('#sell-item'))$('#sell-item').onclick=()=>showSell(i.id);if($('#finalize-item'))$('#finalize-item').onclick=()=>finalizeSale(i.id);if($('#reserve-item'))$('#reserve-item').onclick=()=>setStatus(i.id,'reserve');if($('#unreserve-item'))$('#unreserve-item').onclick=()=>setStatus(i.id,'en_vente');if($('#retire-item'))$('#retire-item').onclick=()=>setStatus(i.id,'retire');if($('#unretire-item'))$('#unretire-item').onclick=()=>setStatus(i.id,'en_vente');if($('#watch-item'))$('#watch-item').onclick=()=>showWatchForm(i);if($('#cancel-sale'))$('#cancel-sale').onclick=()=>cancelSale(i.id);$('#archive-item').onclick=()=>archiveItem(i.id);
}
function showSell(id){const i=state.items.find(x=>x.id===id),quant=i?.inventory_mode==='quantity';openModal(`<p class="eyebrow accent">VENTE EN COURS</p><h2>${escapeHtml(i?.designation||'Article')}</h2><p class="muted">Cette vente ne sera comptabilisée qu’après sa finalisation.${quant?` Stock actuellement disponible : ${i.available_quantity} unité(s).`:''}</p><form id="sell-form" class="form-grid">${quant?`<label>Quantité vendue *<input name="quantity" type="number" min="1" max="${i.available_quantity}" step="1" value="1" required></label>`:'<input type="hidden" name="quantity" value="1">'}<label>${quant?'Prix total de cette vente':'Prix réellement vendu'} *<input name="sale_price" type="number" min="0" step="0.01" value="${i?.list_price||''}" required></label><label>Plateforme *<select name="platform" required><option value="">Sélectionner…</option><option>Vinted</option><option>Leboncoin</option><option>eBay</option><option>Autre</option></select></label><label>Date de vente *<input name="sale_date" type="date" value="${today()}" required></label><label>Référence de transaction<input name="transaction_ref" placeholder="Facultatif"></label><div class="form-actions"><button type="button" class="btn secondary" data-close>Annuler</button><button class="btn primary">Confirmer la vente en cours</button></div></form>`);$('#sell-form').onsubmit=async e=>{e.preventDefault();try{await api(`/api/items/${id}/sell`,{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(e.target)))});closeModal();toast('La vente est maintenant en cours.');await Promise.all([loadItems(),loadDashboard()])}catch(err){toast(err.message,true)}}}
async function finalizeSale(id){try{await api(`/api/items/${id}/finalize-sale`,{method:'POST',body:'{}'});closeModal();toast('Vente finalisée et intégrée aux résultats.');await Promise.all([loadItems(),loadDashboard()])}catch(err){toast(err.message,true)}}
async function setStatus(id,status){try{await api(`/api/items/${id}/status`,{method:'POST',body:JSON.stringify({status})});closeModal();await loadItems();toast('Statut mis à jour.')}catch(err){toast(err.message,true)}}
async function cancelSale(id){if(!confirm('Annuler cette vente et remettre l’article en vente ?'))return;try{await api(`/api/items/${id}/cancel-sale`,{method:'POST',body:'{}'});closeModal();await Promise.all([loadItems(),loadDashboard()]);toast('Vente annulée.')}catch(err){toast(err.message,true)}}
async function archiveItem(id){if(!confirm('Archiver cet article ? Il ne figurera plus dans vos résultats.'))return;try{await api(`/api/items/${id}`,{method:'DELETE'});closeModal();await Promise.all([loadItems(),loadDashboard()]);toast('Article archivé.')}catch(err){toast(err.message,true)}}

async function loadTop(){state.top=await api('/api/top-sales?platform='+encodeURIComponent($('#top-platform').value));renderTop()}
$('#top-platform').onchange=loadTop;$$('#top-sort button').forEach(b=>b.onclick=()=>{state.topSort=b.dataset.sort;$$('#top-sort button').forEach(x=>x.classList.toggle('active',x===b));renderTop()});
function renderTop(){
  let sales=[...(state.top?.sales||[])];const sorter={opportunity:(a,b)=>b.opportunity_score-a.opportunity_score,margin:(a,b)=>b.margin-a.margin,speed:(a,b)=>a.sale_days-b.sale_days}[state.topSort];sales.sort(sorter);
  const best=sales[0],total=sales.reduce((s,x)=>s+x.margin,0),avgDays=sales.length?sales.reduce((s,x)=>s+x.sale_days,0)/sales.length:0;
  $('#top-summary').innerHTML=[['Marge cumulée',euro(total)],['Délai moyen',sales.length?Math.round(avgDays)+' jours':'—'],['Meilleure vente',best?escapeHtml(best.designation):'—']].map(x=>`<div class="summary-chip"><p>${x[0]}</p><strong>${x[1]}</strong></div>`).join('');
  $('#top-grid').innerHTML=sales.length?sales.slice(0,9).map((i,n)=>`<article class="top-card"><span class="rank">${String(n+1).padStart(2,'0')}</span><div class="score-ring">${i.opportunity_score}</div><h3>${escapeHtml(i.designation)}</h3><span class="meta">${i.platform} · ${fmtDate(i.sale_date)}</span><div class="top-metrics"><div><span>Marge</span><strong class="margin-positive">+${euro(i.margin)}</strong></div><div><span>Taux</span><strong>${i.margin_rate}%</strong></div><div><span>Vendu en</span><strong>${i.sale_days} j</strong></div></div><button class="btn secondary" data-watch-item="${i.id}">◎ Rechercher de nouveau</button></article>`).join(''):'<div class="empty">Enregistrez quelques ventes pour révéler vos meilleures opportunités.</div>';
  $('#repeat-grid').innerHTML=state.top.repeats.length?state.top.repeats.map(r=>`<div class="repeat-card"><strong>${escapeHtml(r.product_name)}</strong><p>${r.sales_count} ventes · marge moyenne ${euro(r.average_margin)} · ${Math.round(r.average_days)} jours en moyenne</p></div>`).join(''):'<div class="empty">Les produits vendus plusieurs fois seront regroupés ici.</div>';
  $$('[data-watch-item]').forEach(b=>b.onclick=()=>showWatchForm(sales.find(x=>x.id===Number(b.dataset.watchItem))));
}

async function loadWatch(){state.watch=await api('/api/watchlist');$('#nav-watch').textContent=state.watch.filter(x=>x.active).length;renderWatch()}
function renderWatch(){
  $('#watch-grid').innerHTML=state.watch.length?state.watch.map(w=>`<article class="watch-card"><div class="card-head"><div><p class="eyebrow">${escapeHtml(w.category_name||'PRODUIT')}</p><h3>${escapeHtml(w.product_name)}</h3></div><span class="status ${w.active?'en_vente':'retire'}">${w.active?'Active':'Pause'}</span></div><div class="watch-data"><div class="watch-stat"><small>Prix maximal</small><strong>${w.max_purchase_price!=null?euro(w.max_purchase_price):'À définir'}</strong></div><div class="watch-stat"><small>Marge historique</small><strong>${w.average_margin!=null?euro(w.average_margin):'—'}</strong></div><div class="watch-stat"><small>Revente moyenne</small><strong>${w.average_sale_price!=null?euro(w.average_sale_price):'—'}</strong></div><div class="watch-stat"><small>Délai moyen</small><strong>${w.average_days!=null?Math.round(w.average_days)+' jours':'—'}</strong></div></div><div class="tags">${w.platforms.map(p=>`<span class="tag">${p}</span>`).join('')}</div><button class="btn secondary wide" data-edit-watch="${w.product_id}" style="margin-top:14px">Modifier les critères</button></article>`).join(''):'<div class="empty"><strong>Aucun produit à rechercher</strong><p>Depuis une vente ou l’onglet Top ventes, cliquez sur « Rechercher de nouveau ».</p></div>';
  $$('[data-edit-watch]').forEach(b=>b.onclick=()=>showWatchForm(null,state.watch.find(x=>x.product_id===Number(b.dataset.editWatch))));
}
function showWatchForm(item,watch=null){
  const pid=watch?.product_id||item?.product_id,name=watch?.product_name||item?.product_name||item?.designation;if(!pid)return;
  const platforms=watch?.platforms||['Vinted','Leboncoin','eBay'];
  openModal(`<p class="eyebrow accent">CRITÈRES DE RECHERCHE</p><h2>${escapeHtml(name)}</h2><p class="muted">Ces réglages serviront aux futurs connecteurs automatiques.</p><form id="watch-form" class="form-grid"><label class="span-2">Mots-clés<input name="keywords" value="${escapeHtml(watch?.keywords||name)}"></label><label class="span-2">Mots à exclure<input name="excluded_words" value="${escapeHtml(watch?.excluded_words||'')}" placeholder="HS, cassé, incomplet…"></label><label>Prix d’achat maximal<input name="max_purchase_price" type="number" min="0" step="0.01" value="${watch?.max_purchase_price??item?.purchase_price??''}"></label><label>Marge minimale<input name="min_margin" type="number" min="0" step="0.01" value="${watch?.min_margin??item?.margin??''}"></label><label class="span-2">État recherché<input name="desired_condition" value="${escapeHtml(watch?.desired_condition||'')}" placeholder="Ex. Très bon état, complet"></label><div class="span-2"><p class="eyebrow">PLATEFORMES</p>${['Vinted','Leboncoin','eBay'].map(p=>`<label class="check-row"><input type="checkbox" name="platform" value="${p}" ${platforms.includes(p)?'checked':''}> ${p}</label>`).join('')}</div><label class="span-2">Notes<textarea name="notes">${escapeHtml(watch?.notes||'')}</textarea></label><label class="span-2 check-row"><input type="checkbox" name="active" ${watch?.active===0?'':'checked'}> Recherche active</label><div class="form-actions"><button type="button" class="btn secondary" data-close>Annuler</button><button class="btn primary">Enregistrer les critères</button></div></form>`);
  $('#watch-form').onsubmit=async e=>{e.preventDefault();const fd=new FormData(e.target),payload=Object.fromEntries(fd);payload.product_id=pid;payload.platforms=fd.getAll('platform');payload.active=fd.has('active');try{await api('/api/watchlist',{method:'POST',body:JSON.stringify(payload)});closeModal();await loadWatch();toast('Critères de recherche enregistrés.')}catch(err){toast(err.message,true)}};
}

async function loadAccounting(){const q=accountingQuery();const d=await api('/api/accounting?'+q);$('#accounting-kpis').innerHTML=[['Total des achats',d.summary.purchases,`${d.summary.purchase_count} opération(s)`],['Chiffre d’affaires',d.summary.revenue,`${d.summary.sale_count} vente(s)`],['Marge brute',d.summary.margin,'sur les ventes de la période']].map(x=>`<div class="accounting-kpi"><span>${x[0]}</span><strong>${euro(x[1])}</strong><small class="muted">${x[2]}</small></div>`).join('');$('#accounting-tbody').innerHTML=d.rows.length?d.rows.map(r=>`<tr><td>${fmtDate(r.date)}</td><td><span class="status ${r.kind==='vente'?'vendu':'en_vente'}">${r.kind}</span></td><td>${r.code}</td><td><strong>${escapeHtml(r.designation)}</strong></td><td>${escapeHtml(r.category||'—')}</td><td>${r.platform||'—'}</td><td>${euro(r.amount)}</td><td>${r.margin!=null?`<span class="margin-positive">+${euro(r.margin)}</span>`:'—'}</td></tr>`).join(''):'<tr><td colspan="8" class="empty">Aucune opération sur cette période.</td></tr>'}
function accountingQuery(){return new URLSearchParams({start:$('#accounting-start').value,end:$('#accounting-end').value,platform:$('#accounting-platform').value,kind:$('#accounting-kind').value})}
$('#accounting-apply').onclick=loadAccounting;$('#export-csv').onclick=()=>location.href='/api/export/csv?'+accountingQuery();$('#export-pdf').onclick=()=>location.href='/api/export/pdf?'+accountingQuery();$('#export-xlsx').onclick=()=>location.href='/api/export/xlsx?'+accountingQuery();

async function loadTelegram(){
  try{
    const s=await api('/api/telegram/status');
    const pill=$('#telegram-status-pill');
    pill.className='status '+(s.paired&&s.running?'en_vente':s.configured?'reserve':'retire');
    pill.textContent=s.paired&&s.running?'Connecté':s.configured?'Association requise':'Non configuré';
    $('#telegram-nav-dot').textContent=s.paired&&s.running?'✓':'!';
    $('#telegram-pair-btn').disabled=!s.configured;
    $('#telegram-disable').classList.toggle('hidden',!s.configured);
    $('#telegram-token-form').classList.toggle('hidden',s.configured);
    if(s.bot_name){
      $('#telegram-bot-link').classList.remove('hidden');
      $('#telegram-bot-link').innerHTML=`Bot connecté : <a href="https://t.me/${escapeHtml(s.bot_name)}" target="_blank" rel="noopener">@${escapeHtml(s.bot_name)}</a>`;
    }
    $('#telegram-health-title').textContent=s.paired&&s.running?'Bot actif et sécurisé':s.configured?'Bot connecté — compte à associer':'En attente de configuration';
    $('#telegram-health-copy').textContent=s.last_error?`Dernière erreur : ${s.last_error}`:s.paired?'Votre compte Telegram est associé. Les commandes sont disponibles.':'Le bot fonctionnera tant que La boutique à Dadou restera ouverte sur cet ordinateur.';
  }catch(err){toast(err.message,true)}
}
$('#telegram-token-form').onsubmit=async e=>{e.preventDefault();const button=e.target.querySelector('button');button.disabled=true;button.textContent='Connexion…';try{await api('/api/telegram/config',{method:'POST',body:JSON.stringify({token:$('#telegram-token').value})});$('#telegram-token').value='';toast('Bot Telegram connecté.');await loadTelegram()}catch(err){toast(err.message,true)}finally{button.disabled=false;button.textContent='Connecter le bot'}};
$('#telegram-pair-btn').onclick=async()=>{try{const r=await api('/api/telegram/pair-code',{method:'POST',body:'{}'});const box=$('#telegram-pair-code');box.classList.remove('hidden');box.innerHTML=`/lier ${r.code}<small>Envoyez exactement ce message au bot · valable ${r.expires_minutes} minutes</small>`}catch(err){toast(err.message,true)}};
$('#telegram-disable').onclick=async()=>{if(!confirm('Désactiver la connexion Telegram ?'))return;try{await api('/api/telegram/disable',{method:'POST',body:'{}'});toast('Telegram désactivé.');await loadTelegram()}catch(err){toast(err.message,true)}};
setInterval(()=>{if(state.view==='telegram')loadTelegram()},5000);

boot().catch(err=>toast(err.message,true));
