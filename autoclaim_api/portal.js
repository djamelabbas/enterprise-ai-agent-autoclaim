'use strict';
// Secure by construction: never use innerHTML for model, document or API text.
// The browser holds only bounded conversation history; it does NOT grant access.
const $ = id => document.getElementById(id);
const state = {claims:[],current:null,documents:[],histories:new Map(),busy:false};
const create = (tag,text,cls) => {const n=document.createElement(tag);if(text!==undefined)n.textContent=String(text);if(cls)n.className=cls;return n;};
const set = (id,value) => {$(id).textContent=String(value);};
const money = amount => typeof amount==='number'?new Intl.NumberFormat('fr-FR',{style:'currency',currency:'EUR',maximumFractionDigits:0}).format(amount):'--';
let alertHandle;
function toast(message){const n=$('toast');n.textContent=message;n.classList.add('show');clearTimeout(alertHandle);alertHandle=setTimeout(()=>n.classList.remove('show'),5000);}
async function api(path,options={}){
  const response=await fetch(path,{credentials:'same-origin',cache:'no-store',...options});
  const data=await response.json().catch(()=>({detail:'Reponse indisponible'}));
  if(!response.ok){const error=new Error(data.detail||('HTTP '+response.status));error.status=response.status;throw error;}
  return data;
}
const claimPath = () => '/api/claims/'+encodeURIComponent(state.current||'');
function renderClaimList(){
  const container=$('case-list');container.replaceChildren();
  if(!state.claims.length){container.append(create('div','Aucun sinistre accessible.','info-note'));return;}
  for(const item of state.claims){
    const row=create('button',undefined,'case-item'+(item.claim_id===state.current?' selected':''));row.type='button';row.setAttribute('aria-label','Ouvrir '+item.claim_id);
    row.append(create('div','\u25a7','case-icon'));
    const info=create('div',undefined,'case-info');const line=create('div',undefined,'case-line');
    line.append(create('strong',item.claim_id),create('small',item.event_date));
    const desc=create('div',item.description,'case-desc');const bottom=create('div',undefined,'case-line');
    bottom.append(create('span',item.coverage_code,'tag'+(item.needs_attention?' warning':'')),create('span',money(item.damage_eur),'case-money'));
    info.append(line,desc,bottom);row.append(info);row.addEventListener('click',()=>selectClaim(item.claim_id));container.append(row);
  }
}
function renderDocuments(){
  const container=$('document-list');container.replaceChildren();set('count-docs',state.documents.length);
  if(!state.documents.length){container.append(create('div','Aucun document visible pour ce dossier.'));return;}
  for(const doc of state.documents){
    const row=create('div',undefined,'doc-row');const type=create('span',doc.format.toUpperCase(),'doc-type'+(doc.format==='docx'?' word':''));
    const info=create('div',undefined,'doc-info');info.append(create('strong',doc.title),create('small','Document fictif - v'+doc.version));
    const link=create('a','Consulter','doc-link');link.href=claimPath()+'/documents/'+encodeURIComponent(doc.document_id);link.target='_blank';link.rel='noopener noreferrer';
    row.append(type,info,link);container.append(row);
  }
}
async function selectClaim(input){
  const id=input.trim().toUpperCase();
  if(!/^SIN-[0-9]{4,8}$/.test(id)){toast('Identifiant incorrect. Exemple : SIN-1001.');return;}
  try{
    // The backend checks the verified IAP identity before revealing any data.
    const summary=await api('/api/claims/'+encodeURIComponent(id));
    state.current=id;$('claim-input').value=id;
    set('selected-id',id);set('detail-policy',summary.policy_id);set('detail-coverage',summary.coverage_code);
    set('detail-date',summary.event_date);set('detail-amount',money(summary.damage_eur));set('detail-description',summary.description);
    set('claim-status',summary.needs_attention?'Revue requise':'En instruction');
    $('analyze').disabled=false;$('ask-context').disabled=false;
    $('review-result').replaceChildren();$('review-result').classList.remove('visible');
    set('chat-claim',id);renderClaimList();renderChat();
    const result=await api(claimPath()+'/documents');
    if(state.current===id){state.documents=result.documents;renderDocuments();}
  }catch(error){toast(error.status===404?'Dossier indisponible ou non autorise.':'Erreur : '+error.message);}
}
function showReview(data){
  const panel=$('review-result');panel.replaceChildren();panel.classList.add('visible');
  panel.append(create('strong','Preanalyse : '+(data.status||'examen requis')));
  if(typeof data.indicative_amount_eur==='number'){
    const grid=create('div',undefined,'review-grid');
    for(const [label,amount] of [['Franchise',data.deductible_eur],['Plafond',data.limit_eur],['Montant indicatif',data.indicative_amount_eur]]){
      const cell=create('div');cell.append(create('small',label),create('strong',money(amount)));grid.append(cell);
    }
    panel.append(grid);
  }else{panel.append(create('div',data.message||'Examen humain necessaire.'));}
  panel.append(create('div','Sources verifiees : '+(data.source_refs||[]).length+'. Validation humaine obligatoire.'));
}
async function preanalyze(){
  if(!state.current)return;
  const id=state.current;$('analyze').disabled=true;
  try{const result=await api(claimPath()+'/review');if(state.current===id)showReview(result);}
  catch(error){toast('Preanalyse indisponible : '+error.message);}
  finally{$('analyze').disabled=false;}
}
function toggleChat(show){
  const panel=$('chat-panel');const next=show===undefined?!panel.classList.contains('open'):show;
  panel.classList.toggle('open',next);$('chat-launch').setAttribute('aria-expanded',String(next));
  if(next){renderChat();$('chat-input').focus();}
}
function chatHistory(){return state.histories.get(state.current)||[];}
function renderText(node,content){
  // A minimal markdown subset (bold/inline code), constructed without HTML injection.
  String(content).split('\n').forEach(line=>{
    const paragraph=create('div',undefined,'line');const raw=line.replace(/^\s*[*-]\s+/,'\u2022 ');
    for(const part of raw.split(/(\*\*[^*]+\*\*|`[^`]+`)/g)){
      if(part.startsWith('**')&&part.endsWith('**')) paragraph.append(create('strong',part.slice(2,-2)));
      else if(part.startsWith('`')&&part.endsWith('`'))paragraph.append(create('code',part.slice(1,-1)));
      else paragraph.append(document.createTextNode(part));
    }
    node.append(paragraph);
  });
}
function appendMessage(role,text,sources=[]){
  const container=$('messages');const row=create('div',undefined,'message '+role);
  if(role==='assistant')row.append(create('span','\u2726','bot-icon'));
  const bubble=create('div',undefined,'bubble');renderText(bubble,text);
  if(Array.isArray(sources)&&sources.length){
    const details=create('details',undefined,'sources');details.append(create('summary','Sources verifiees ('+sources.length+')'));
    for(const source of sources){
      const item=create('div',undefined,'source');item.append(create('strong',source.citation),create('small',source.title));
      if(source.excerpt)item.append(create('small',source.excerpt.slice(0,350)+(source.excerpt.length>350?'...':'')));
      if(source.document_id&&state.current){
        const link=create('a','Consulter le document source');link.href=claimPath()+'/documents/'+encodeURIComponent(source.document_id);
        link.target='_blank';link.rel='noopener noreferrer';item.append(link);
      }else item.append(create('small','Origine : '+(source.origin||'SI fictif')));
      details.append(item);
    }
    bubble.append(details);
  }
  row.append(bubble);container.append(row);container.scrollTop=container.scrollHeight;
}
function renderChat(){
  $('messages').replaceChildren();
  if(!state.current){appendMessage('assistant','Selectionnez un dossier pour commencer.');return;}
  if(!chatHistory().length){appendMessage('assistant','Bonjour ! Je suis votre copilote AutoClaim. Je peux examiner '+state.current+', rechercher les clauses du contrat et les justificatifs dans les PDF et documents Word. Que souhaitez-vous savoir ?');return;}
  for(const turn of chatHistory())appendMessage(turn.role,turn.content,turn.sources||[]);
}
async function sendMessage(raw){
  if(state.busy)return;const text=raw.trim();if(text.length<3)return;
  if(!state.current){toast('Selectionnez d abord un dossier.');return;}
  const id=state.current;
  const previous=chatHistory().slice(-6).map(({role,content})=>({role,content:content.slice(0,1000)}));
  let turns=state.histories.get(id);if(!turns){turns=[];state.histories.set(id,turns);}
  turns.push({role:'user',content:text});appendMessage('user',text);
  state.busy=true;$('chat-send').disabled=true;$('chat-input').value='';$('suggestions').hidden=true;
  appendMessage('assistant','Recherche documentaire et interrogation de Gemini en cours...');
  try{
    const result=await api('/api/claims/'+encodeURIComponent(id)+'/chat',{
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:text,history:previous}),
    });
    turns.push({role:'assistant',content:result.answer,sources:result.sources||[]});
  }catch(error){turns.push({role:'assistant',content:'La demande ne peut pas etre traitee ('+(error.status||'reseau')+'). '+error.message+'. Aucun resultat non justifie ne sera presente comme une decision.'});}
  finally{state.busy=false;$('chat-send').disabled=false;$('suggestions').hidden=false;if(state.current===id){renderChat();$('chat-input').focus();}}
}
async function init(){
  try{
    const [identity,response]=await Promise.all([api('/api/me'),api('/api/claims')]);
    state.claims=response.claims;set('account',identity.email);set('role',identity.groups.join(' / '));
    set('avatar',identity.email.slice(0,2).toUpperCase());set('count-claims',response.total);set('list-total',response.total+' dossiers');
    renderClaimList();if(state.claims.length)await selectClaim(state.claims[0].claim_id);
  }catch(error){set('account','Acces non autorise');toast('Acces impossible : '+error.message);}
}
$('claim-form').addEventListener('submit',event=>{event.preventDefault();selectClaim($('claim-input').value);});
$('analyze').addEventListener('click',preanalyze);
$('ask-context').addEventListener('click',()=>toggleChat(true));
$('open-chat').addEventListener('click',()=>toggleChat(true));
$('sidebar-chat').addEventListener('click',()=>toggleChat(true));
$('chat-launch').addEventListener('click',()=>toggleChat());
$('chat-close').addEventListener('click',()=>toggleChat(false));
$('chat-expand').addEventListener('click',()=>$('chat-panel').classList.toggle('max'));
$('chat-clear').addEventListener('click',()=>{if(state.current)state.histories.set(state.current,[]);renderChat();});
$('chat-form').addEventListener('submit',event=>{event.preventDefault();sendMessage($('chat-input').value);});
$('chat-input').addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendMessage($('chat-input').value);}});
document.querySelectorAll('.suggestions button').forEach(button=>button.addEventListener('click',()=>{toggleChat(true);sendMessage(button.dataset.prompt);}));
init();
