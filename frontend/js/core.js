// TF-DEV: 모든 페이지 공통 유틸 + 장바구니 상태(tfPlan) — 계약: docs/frontend_외부수정요청.md §A-4, §D-4
// 멀티페이지 구조: 화면 이동은 실제 페이지 이동(location.href)이다. 브라우저에는
// "지금 열어 둔 장바구니 ID"와 사이드바 접힘 상태만 저장하고, 나머지는 페이지를 열 때마다 서버에서 다시 받는다.
const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const won=n=>Math.round(n).toLocaleString('ko-KR')+'원';
const money=n=>Number.isFinite(Number(n))?Number(n):0;
const flow=document.getElementById('flow'); // 랜딩 페이지(index.html)에는 없음 — null

const TF_ACTIVE_LIST_KEY='truefit-active-list';
const SIDEBAR_STORE='planbasket-sidebar-collapsed';
// TF-DEV: 페이지별 파일명 매핑 — 화면 로직은 예전과 같은 라우트 이름('conditions' 등)을 쓰고, 실제 이동만 이 표로 변환한다.
const TF_ROUTES={'':'index.html',category:'category.html',conditions:'conditions.html',results:'results.html',logs:'logs.html',confirm:'confirm.html',report:'report.html',login:'login.html',signup:'signup.html',account:'account.html'};
function tfHref(route){return TF_ROUTES[route]||'index.html'}
function go(route){location.href=tfHref(route)}

const tfPlan={listId:null,condition:null,result:null,report:null,lists:null,listsLoaded:false,listsLoading:false,listsError:null,resultMessages:[],pollTimer:null,seq:0,busy:false};
try{tfPlan.listId=localStorage.getItem(TF_ACTIVE_LIST_KEY)||null;localStorage.removeItem('planbasket-demo-v1')}catch{}

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
function btn(t,a,cl=''){return `<button class="btn ${cl}" data-action="${a}">${t}</button>`}
function heading(k,t,p=''){return `<div class="flow-head"><div class="flow-logo">${k}</div><h1 tabindex="-1">${t}</h1>${p?`<p class="muted">${p}</p>`:''}</div>`}
function field(label,name,type,value,extra=''){return `<label for="f-${name}">${label}</label><input id="f-${name}" name="${name}" type="${type}" value="${esc(value)}" ${extra}>`}
function tfRequire(data){if(!data||typeof data!=='object')throw new TF_ApiError(0,'bad_response','서버 응답이 올바르지 않아요.');return data}
function tfStatusPanel(title,message='',actions=''){return `<div class="panel empty"><h2>${esc(title)}</h2>${message?`<p class="muted">${esc(message)}</p>`:''}${actions}</div>`}
function readAuthSession(){return TF_AUTH.user}
// TF-DEV: 카테고리 선택은 index.html 퀵스타트 카드·category.html·푸터 바로가기 모두에서 쓰여 core.js에 둔다.
async function tfSetCategory(c,{fresh=false}={}){if(tfPlan.busy)return;const category=tfApiCategory(c),summary=tfListSummary(),known=tfPlan.condition?.category||summary?.category||null;if(!fresh&&tfPlan.listId&&known===category){go('conditions');return}if(!fresh&&tfPlan.listId&&known&&known!==category&&!window.confirm('카테고리를 바꾸면 지금까지의 조건과 추천 결과가 초기화돼요. 계속할까요?'))return;tfPlan.busy=true;try{if(fresh||!tfPlan.listId){const created=tfRequire(await TF_PLAN.createSession());tfSelectList(created.list_id)}const state=tfRequire(await TF_PLAN.chooseCategory(tfPlan.listId,category));tfPlan.condition=state;tfPlan.result=null;tfPlan.report=null;tfPlan.resultMessages=[];tfPlan.listsLoaded=false;go('conditions')}catch(err){if(!tfListGone(err))toast(tfAuthErrorMessage(err))}finally{tfPlan.busy=false}}
function choose(c){return tfSetCategory(c,{fresh:true})}
