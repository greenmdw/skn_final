const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const won=n=>Math.round(n).toLocaleString('ko-KR')+'원';
const money=n=>Number.isFinite(Number(n))?Number(n):0;
// TF-DEV: 장바구니·조건 대화·추천·리포트는 서버 API(TF_PLAN) 기준으로 동작한다 — 계약: docs/frontend_외부수정요청.md §D-4
// 브라우저에는 "지금 열어 둔 장바구니 ID"와 사이드바 접힘 상태만 저장한다.
const TF_ACTIVE_LIST_KEY='truefit-active-list';
const SIDEBAR_STORE='planbasket-sidebar-collapsed';
const tfPlan={listId:null,condition:null,result:null,report:null,lists:null,listsLoaded:false,listsLoading:false,listsError:null,resultMessages:[],pollTimer:null,seq:0,busy:false};
try{tfPlan.listId=localStorage.getItem(TF_ACTIVE_LIST_KEY)||null;localStorage.removeItem('planbasket-demo-v1')}catch{}
let authNext='';
const tfSeg=value=>encodeURIComponent(String(value));
const TF_PLAN={
 createSession(){return TF_API.post('/session')},
 condition(id){return TF_API.get('/session/'+tfSeg(id))},
 chooseCategory(id,category){return TF_API.post('/session/'+tfSeg(id)+'/category',{category})},
 message(id,text){return TF_API.post('/session/'+tfSeg(id)+'/message',{text})},
 answer(id,questionId,selected){return TF_API.post('/session/'+tfSeg(id)+'/answer',{question_id:questionId,selected})},
 clearSlot(id,field){return TF_API.patch('/session/'+tfSeg(id)+'/slot',{field,value:null})},
 reset(id){return TF_API.post('/session/'+tfSeg(id)+'/reset')},
 specFile(id,fileName,content){return TF_API.post('/session/'+tfSeg(id)+'/spec-file',{file_name:fileName,content})},
 recommend(id,strategy){return TF_API.post('/session/'+tfSeg(id)+'/recommend',strategy?{strategy}:{})},
 result(id){return TF_API.get('/session/'+tfSeg(id)+'/result')},
 updateItem(id,itemId,changes){return TF_API.patch('/session/'+tfSeg(id)+'/items/'+tfSeg(itemId),changes)},
 alternatives(id,itemId){return TF_API.get('/session/'+tfSeg(id)+'/items/'+tfSeg(itemId)+'/alternatives')},
 swap(id,itemId,candidateId){return TF_API.post('/session/'+tfSeg(id)+'/items/'+tfSeg(itemId)+'/swap',{candidate_id:candidateId})},
 resultMessage(id,text){return TF_API.post('/session/'+tfSeg(id)+'/result-message',{text})},
 reviewSummary(productKey){return TF_API.get('/reviews/summary/'+tfSeg(productKey))},
 lists(){return TF_API.get('/lists')},
 renameList(id,name){return TF_API.patch('/lists/'+tfSeg(id),{name})},
 deleteList(id){return TF_API.del('/lists/'+tfSeg(id))},
 confirm(id,body){return TF_API.post('/lists/'+tfSeg(id)+'/confirm',body)},
 report(id){return TF_API.get('/lists/'+tfSeg(id)+'/report')},
 alert(id,body){return TF_API.post('/lists/'+tfSeg(id)+'/alert',body)}
};
function tfUiCategory(category){return category==='computer'?'pc':category||''}
function tfApiCategory(category){return category==='pc'?'computer':category}
function tfListSummary(id=tfPlan.listId){return (tfPlan.lists||[]).find(item=>item.list_id===id)||null}
function tfStageRoute(stage){return ['category','conditions','results','report'].includes(stage)?stage:'conditions'}
function tfPlanRoute(){const summary=tfListSummary();if(!tfPlan.listId)return 'category';if(tfPlan.report||summary?.stage==='report')return 'report';if(tfPlan.result||summary?.stage==='results')return 'results';if(tfPlan.condition?.category||summary?.category)return 'conditions';return 'category'}
function tfSelectList(id){tfStopPoll();tfPlan.listId=id||null;tfPlan.condition=null;tfPlan.result=null;tfPlan.report=null;tfPlan.resultMessages=[];try{id?localStorage.setItem(TF_ACTIVE_LIST_KEY,id):localStorage.removeItem(TF_ACTIVE_LIST_KEY)}catch{}}
function tfOnAuthChange(){tfPlan.lists=null;tfPlan.listsLoaded=false;tfPlan.report=null}
function tfListGone(err){if(err&&err.status===404&&err.code==='not_found'){tfSelectList(null);tfPlan.listsLoaded=false;toast('장바구니를 찾을 수 없어 새로 시작합니다.');go('category');return true}return false}
function tfStopPoll(){clearTimeout(tfPlan.pollTimer);tfPlan.pollTimer=null}
function toast(t,centered=false){let el=$('.toast');if(el)el.remove();el=document.createElement('div');el.className='toast'+(centered?' toast-center':'');el.setAttribute('role','status');el.textContent=t;document.body.append(el);setTimeout(()=>el.remove(),3500)}
function go(route){if(location.hash==='#/'+route)render();else location.hash='/'+route;window.scrollTo(0,0)}
function btn(t,a,cl=''){return `<button class="btn ${cl}" data-action="${a}">${t}</button>`}
function heading(k,t,p=''){return `<div class="flow-head"><div class="flow-logo">${k}</div><h1 tabindex="-1">${t}</h1>${p?`<p class="muted">${p}</p>`:''}</div>`}
function field(label,name,type,value,extra=''){return `<label for="f-${name}">${label}</label><input id="f-${name}" name="${name}" type="${type}" value="${esc(value)}" ${extra}>`}
function current(){return location.hash.replace(/^#\/?/,'').split('?')[0]}
const flow=document.createElement('section');flow.className='flow';flow.hidden=true;flow.id='flow';document.querySelector('main').after(flow);
function steps(i){const summary=tfListSummary(),result=tfPlan.result,defs=[['카테고리','category',true],['조건 입력','conditions',!!tfPlan.listId],['추천 결과','results',!!(result&&['running','done'].includes(result.status))||['results','report'].includes(summary?.stage)],['리스트 확정','confirm',!!(result&&result.totals&&result.totals.selected_units)],['리포트','report',!!tfPlan.report||summary?.stage==='report']];return `<ol class="flow-steps" aria-label="장바구니 만들기 단계">${defs.map(([label,route,enabled],n)=>{const text=`0${n+1} ${label}`;return `<li class="${n===i?'active ':''}${enabled?'':'disabled'}" ${n===i?'aria-current="step"':''}>${enabled?`<a href="#/${route}">${text}</a>`:`<span aria-disabled="true">${text}</span>`}</li>`}).join('')}</ol>`}
function tfRefreshLists(){if(tfPlan.listsLoading)return;tfPlan.listsLoading=true;TF_PLAN.lists().then(data=>{tfPlan.lists=Array.isArray(data&&data.items)?data.items:[];tfPlan.listsError=null}).catch(err=>{tfPlan.lists=tfPlan.lists||[];tfPlan.listsError=err}).finally(()=>{tfPlan.listsLoading=false;tfPlan.listsLoaded=true;const aside=flow.querySelector('.planner-sidebar');if(aside&&!flow.hidden)aside.outerHTML=sidebar()})}
function sidebar(){if(!tfPlan.listsLoaded&&!tfPlan.listsLoading)setTimeout(tfRefreshLists,0);const session=readAuthSession(),sideTitle=session?esc(session.name||'회원')+'님 장바구니':'내 장바구니';let collapsed=false;try{collapsed=localStorage.getItem(SIDEBAR_STORE)==='1'}catch{}const items=tfPlan.lists||[];let baskets;if(!tfPlan.listsLoaded)baskets='<p class="muted" style="font-size:12px;margin:4px 8px">장바구니를 불러오는 중…</p>';else if(tfPlan.listsError&&!items.length)baskets='<p class="muted" style="font-size:12px;margin:4px 8px">'+esc(tfAuthErrorMessage(tfPlan.listsError))+'</p>';else baskets=items.map(list=>{const id=esc(list.list_id),route=tfStageRoute(list.stage),name=esc(list.name||'새 장바구니');return '<div class="planner-saved-item" data-basket-item="'+id+'"><a class="'+(list.list_id===tfPlan.listId?'current':'')+'" href="#/'+route+'" data-open-basket="'+id+'" data-basket-route="'+route+'">'+name+'</a><button class="basket-rename-button" type="button" data-basket-rename="'+id+'" aria-label="'+name+' 이름 변경" title="장바구니 이름 변경">✎</button><button class="basket-delete-button" type="button" data-basket-delete="'+id+'" aria-label="'+name+' 삭제" title="장바구니 삭제">×</button><form class="basket-name-form" data-basket-name-form="'+id+'" hidden><input name="basketName" value="'+name+'" maxlength="60" aria-label="장바구니 이름" required><button type="submit">저장</button><button class="basket-name-cancel" type="button" data-basket-cancel>취소</button></form></div>'}).join('')||'<a href="#/category">아직 저장된 장바구니가 없어요</a>';return '<aside class="planner-sidebar '+(collapsed?'is-collapsed':'')+'"><button class="sidebar-toggle" type="button" data-sidebar-toggle aria-label="'+(collapsed?'사이드바 열기':'사이드바 접기')+'" aria-expanded="'+String(!collapsed)+'" title="'+(collapsed?'사이드바 열기':'사이드바 접기')+'">‹</button><a class="planner-home" href="#/"><span class="planner-brand-full">TrueFit.</span><span class="planner-brand-short">TF</span></a><a class="planner-new" href="#/category"><span class="planner-new-full">＋ 새 장바구니</span><span class="planner-new-short">＋</span></a><div><span class="planner-side-title">'+sideTitle+'</span><nav class="planner-saved" aria-label="내 장바구니">'+baskets+'</nav></div><p class="planner-side-note">장바구니는 서버에 저장됩니다.<br>로그인하지 않으면 이 브라우저에서만 이어볼 수 있어요.</p></aside>'}
function flowAccountNav(){const session=readAuthSession();if(!session)return '<nav class="mini-nav flow-account-nav" aria-label="회원 메뉴"><a href="#/login">로그인</a><a href="#/signup">회원가입</a></nav>';return '<nav class="mini-nav flow-account-nav" aria-label="회원 메뉴"><span class="account-user-name">'+esc(session.name||'회원')+'님</span><div class="service-menu mypage-menu"><button type="button" class="service-trigger" aria-haspopup="true">마이페이지</button><div class="service-dropdown" aria-label="마이페이지 메뉴"><a href="#/'+tfPlanRoute()+'">장바구니</a><a href="#/account">회원정보 수정</a><a href="#" data-flow-account-logout>로그아웃</a></div></div></nav>'}
function shell(body,i){flow.classList.remove('auth-route');const notice=(tfPlan.result&&tfPlan.result.data_notice)||(tfPlan.report&&tfPlan.report.data_notice)||'';flow.innerHTML=`<div class="planner-shell">${sidebar()}<div class="planner-work"><div class="flow-wrap"><div class="flow-top"><a href="#/" class="flow-logo">← TrueFit</a>${flowAccountNav()}</div>${steps(i)}${notice?`<div class="demo-note">${esc(notice)}</div>`:''}${body}</div></div></div>`;const h=flow.querySelector('h1');if(h)h.focus({preventScroll:true})}
function tfStatusPanel(title,message='',actions=''){return `<div class="panel empty"><h2>${esc(title)}</h2>${message?`<p class="muted">${esc(message)}</p>`:''}${actions}</div>`}
function tfLoadThen(route,stepIndex,task){const seq=++tfPlan.seq;shell(tfStatusPanel('불러오는 중이에요…'),stepIndex);task().then(()=>{if(seq===tfPlan.seq&&current()===route)render()}).catch(err=>{if(seq!==tfPlan.seq||current()!==route)return;if(tfListGone(err))return;shell(tfStatusPanel('정보를 불러오지 못했어요.',tfAuthErrorMessage(err),btn('다시 시도',route,'strong')),stepIndex)})}
function tfRequire(data){if(!data||typeof data!=='object')throw new TF_ApiError(0,'bad_response','서버 응답이 올바르지 않아요.');return data}
