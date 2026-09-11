function render(){const r=current();const home=!r||r==='how'||r==='faq',route=r.split('?')[0];
 /* TF-DEV: 서버 로그인 확인 전에는 보호 화면 대기 */if(['report','account'].includes(route)&&!TF_AUTH.loaded){document.querySelector('main').hidden=true;flow.hidden=false;authShell('<section class="auth-card"><p class="auth-sub">로그인 상태를 확인하고 있어요…</p></section>');(TF_AUTH.ready||TF_AUTH.refresh()).then(()=>{if(current()===route)render()});return}
 if(route==='report'&&!readAuthSession()){toast('로그인 후 이용해 주세요.',true);tfSendToLogin('#/report');return}
 document.querySelector('main').hidden=!home;flow.hidden=home;closeResultOverlay();if(!['results','logs'].includes(route))tfStopPoll();
 if(home){flow.classList.remove('auth-route');return}
 ({category:categoryPage,conditions:conditionsPage,results:resultsPage,logs:logsPage,confirm:confirmPage,login:loginPage,signup:signupPage,account:accountPage,report:reportPage}[route]||categoryPage)()}
flow.addEventListener('click',e=>{const b=e.target.closest('button,a');if(!b)return;
 if(b.matches('[data-sidebar-toggle]')){const panel=b.closest('.planner-sidebar'),collapsed=panel.classList.toggle('is-collapsed');b.setAttribute('aria-expanded',String(!collapsed));b.setAttribute('aria-label',collapsed?'사이드바 열기':'사이드바 접기');b.title=collapsed?'사이드바 열기':'사이드바 접기';try{localStorage.setItem(SIDEBAR_STORE,collapsed?'1':'0')}catch{}return}
 if(b.matches('a.planner-new')){e.preventDefault();createNewBasket();return}
 if(b.matches('a[data-open-basket]')){e.preventDefault();if(b.dataset.openBasket!==tfPlan.listId)tfSelectList(b.dataset.openBasket);go(b.dataset.basketRoute||'conditions');return}
 if(b.matches('[data-basket-rename]')){const item=b.closest('.planner-saved-item'),form=item?.querySelector('[data-basket-name-form]'),link=item?.querySelector('a[data-open-basket]');if(!form)return;b.hidden=true;if(link)link.hidden=true;form.hidden=false;const input=form.querySelector('input');input?.focus();input?.select();return}
 if(b.matches('[data-basket-cancel]')){const item=b.closest('.planner-saved-item'),form=b.closest('form'),link=item?.querySelector('a[data-open-basket]'),rename=item?.querySelector('[data-basket-rename]');form.hidden=true;if(link)link.hidden=false;if(rename)rename.hidden=false;return}
 if(b.matches('[data-basket-delete]')){tfDeleteList(b.dataset.basketDelete);return}
 if(b.dataset.categoryChoice){tfSetCategory(b.dataset.categoryChoice);return}
 if(b.hasAttribute('data-answer-value')){if(b.hasAttribute('data-answer-multi')){const pressed=b.getAttribute('aria-pressed')!=='true';b.setAttribute('aria-pressed',String(pressed));b.classList.toggle('primary-option',pressed);return}tfConditionAction(listId=>TF_PLAN.answer(listId,b.dataset.answerQuestion,[b.dataset.answerValue]),{button:b});return}
 if(b.dataset.answerSubmit){const selected=[...flow.querySelectorAll('[data-answer-multi][aria-pressed="true"]')].map(x=>x.dataset.answerValue),error=flow.querySelector('#tf-chat-error');if(!selected.length){if(error)error.textContent='하나 이상 선택해 주세요.';return}tfConditionAction(listId=>TF_PLAN.answer(listId,b.dataset.answerSubmit,selected),{button:b});return}
 if(b.dataset.editField){tfConditionAction(listId=>TF_PLAN.clearSlot(listId,b.dataset.editField),{button:b,busyLabel:'수정 중…'});return}
 if(b.hasAttribute('data-plan-reset')){if(window.confirm('대화를 처음부터 다시 시작할까요? 입력한 조건과 추천 결과가 초기화돼요.'))tfConditionAction(listId=>TF_PLAN.reset(listId),{button:b,busyLabel:'초기화 중…'});return}
 if(b.hasAttribute('data-plan-recommend')){tfStartRecommend(b);return}
 if(b.hasAttribute('data-plan-rerun')){tfStartRecommend(b,b.dataset.planRerun||undefined);return}
 if(b.dataset.planReview){e.preventDefault();tfShowReviewOverlay(b.dataset.planReview);return}
 if(b.dataset.planAlternatives){e.preventDefault();tfShowAlternatives(b.dataset.planAlternatives);return}
 if(b.dataset.planToggle){e.preventDefault();const item=tfFindItem(b.dataset.planToggle);if(item)tfResultAction(listId=>TF_PLAN.updateItem(listId,item.item_id,{selected:!item.selected})).then(tfApplyResult);return}
 if(b.dataset.planRemove){tfResultAction(listId=>TF_PLAN.updateItem(listId,b.dataset.planRemove,{selected:false})).then(tfApplyResult);return}
 if(b.dataset.planQty){const item=tfFindItem(b.dataset.planItem);if(item){const qty=Math.max(1,Math.min(99,(Number(item.qty)||1)+Number(b.dataset.planQty)));tfResultAction(listId=>TF_PLAN.updateItem(listId,item.item_id,{qty})).then(tfApplyResult)}return}
 if(b.dataset.planSwapCandidate){const itemId=b.dataset.planSwapItem;tfResultAction(listId=>TF_PLAN.swap(listId,itemId,b.dataset.planSwapCandidate),{errorTarget:'#tf-swap-error'}).then(data=>{if(data){closeResultOverlay();tfApplyResult(data);toast('선택한 후보로 바꿨어요.')}});return}
 if(b.hasAttribute('data-plan-product-url')){e.preventDefault();const url=b.dataset.planProductUrl||'';if(/^https?:\/\//i.test(url))window.open(url,'_blank','noopener');else toast('판매처 링크가 아직 연결되지 않았어요.');return}
 if(b.hasAttribute('data-overlay-close')){closeResultOverlay();return}
 const a=b.dataset.action;if(!a)return;
 if(a==='print')return window.print();
 if(a==='download'){if(!tfPlan.report)return;const blob=new Blob([JSON.stringify(tfPlan.report,null,2)],{type:'application/json'}),link=document.createElement('a');link.href=URL.createObjectURL(blob);link.download='truefit-report.json';link.click();setTimeout(()=>URL.revokeObjectURL(link.href),1000);return}
 go(a)});
flow.addEventListener('submit',e=>{const f=e.target;
 if(f.id==='tf-chat-form'){e.preventDefault();const text=String(f.querySelector('#tf-chat-input')?.value||'').trim();if(text)tfConditionAction(listId=>TF_PLAN.message(listId,text),{button:f.querySelector('button[type=submit]')});return}
 if(f.id==='tf-result-chat-form'){e.preventDefault();const input=f.querySelector('#tf-result-chat-input'),text=String(input?.value||'').trim(),button=f.querySelector('button[type=submit]');if(!text)return;tfBusy(button,true,'보내는 중…');tfResultAction(listId=>TF_PLAN.resultMessage(listId,text),{errorTarget:'#tf-result-chat-error'}).then(data=>{if(!data){tfBusy(button,false);return}tfPlan.resultMessages.push('나: '+text,'TrueFit: '+(data.reply||''));input.value='';if(data.result)tfApplyResult(data.result);else resultsPage({preserve:true})});return}
 if(f.id==='confirm-form'){e.preventDefault();tfSubmitConfirm(f);return}
 if(f.matches('[data-basket-name-form]')){e.preventDefault();tfRenameList(f.dataset.basketNameForm,String(new FormData(f).get('basketName')||'').trim())}});
flow.addEventListener('change',e=>{const el=e.target;
 if(el.id==='tf-spec-file'){tfReadSpecFile(el);return}
 if(el.dataset.planSelect){tfResultAction(listId=>TF_PLAN.updateItem(listId,el.dataset.planSelect,{selected:el.checked})).then(data=>data?tfApplyResult(data):resultsPage({preserve:true}));return}
 if(el.dataset.planTiming){tfResultAction(listId=>TF_PLAN.updateItem(listId,el.dataset.planTiming,{timing:el.value})).then(data=>data?tfApplyResult(data):resultsPage({preserve:true}));return}
 if(el.id==='alert-pref')tfToggleAlert(el)});
let basketContextMenu=null;
function closeBasketContextMenu(){if(basketContextMenu){basketContextMenu.remove();basketContextMenu=null}}
flow.addEventListener('contextmenu',e=>{const item=e.target.closest('.planner-saved-item[data-basket-item]');if(!item)return;e.preventDefault();closeBasketContextMenu();const id=item.dataset.basketItem,menu=document.createElement('div');menu.className='basket-context-menu';menu.setAttribute('role','menu');menu.innerHTML='<button type="button" role="menuitem" data-context-rename>이름 변경</button><button type="button" role="menuitem" data-context-delete>삭제</button>';document.body.append(menu);const rect=menu.getBoundingClientRect(),left=Math.min(e.clientX,window.innerWidth-rect.width-8),top=Math.min(e.clientY,window.innerHeight-rect.height-8);menu.style.left=Math.max(8,left)+'px';menu.style.top=Math.max(8,top)+'px';basketContextMenu=menu;menu.addEventListener('click',event=>{if(event.target.closest('[data-context-rename]'))item.querySelector('[data-basket-rename]')?.click();if(event.target.closest('[data-context-delete]'))tfDeleteList(id);closeBasketContextMenu()});menu.querySelector('button')?.focus()})
document.addEventListener('click',e=>{if(basketContextMenu&&!basketContextMenu.contains(e.target))closeBasketContextMenu()})
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeBasketContextMenu()})
window.addEventListener('blur',closeBasketContextMenu)
// Preserve the existing landing-page slideshow and header behavior.
const scene=$('.visual'),secondScene=$('.scene-secondary'),motionPreference=window.matchMedia('(prefers-reduced-motion: reduce)');let sceneTimer;
function startSceneRotation(){clearInterval(sceneTimer);if(motionPreference.matches){scene.classList.remove('show-second');return}sceneTimer=setInterval(()=>{if(!document.hidden&&!document.querySelector('main').hidden)scene.classList.toggle('show-second')},2500)}
if(secondScene.complete&&secondScene.naturalWidth)startSceneRotation();else secondScene.addEventListener('load',startSceneRotation,{once:true});motionPreference.addEventListener('change',startSceneRotation);
document.querySelectorAll('[data-start]').forEach(b=>b.onclick=()=>go('category'));
document.querySelectorAll('[data-category]').forEach(b=>b.onclick=e=>{e.preventDefault();choose(b.dataset.category==='컴퓨터'?'pc':'baby')});
// TF-DEV: 예전 브라우저 로그인 저장값(가짜 세션) 정리. 로그인 상태는 서버 쿠키 + TF_AUTH.user로만 판단
try{sessionStorage.removeItem('truefit-session-v1');localStorage.removeItem('truefit-session-v1')}catch{}
function readAuthSession(){return TF_AUTH.user}
function bindAuthButtons(){document.querySelectorAll('[data-auth]').forEach(b=>b.onclick=()=>{if(b.dataset.auth==='회원가입'){go('signup');return}if(b.dataset.auth==='로그인'){go('login');return}authNext='';go('auth')})}
function renderAccountHeader(){const nav=$('.account-nav');if(!nav)return;const session=readAuthSession();if(!session){nav.innerHTML='<button type="button" data-auth="로그인">로그인</button><button type="button" data-auth="회원가입">회원가입</button>';bindAuthButtons();return}nav.innerHTML='<span class="account-user-name">'+esc(session.name||'회원')+'님</span><div class="service-menu mypage-menu"><button type="button" class="service-trigger" aria-haspopup="true">마이페이지</button><div class="service-dropdown" aria-label="마이페이지 메뉴"><a href="#/results" data-account-basket>장바구니</a><a href="#" data-account-profile>회원정보 수정</a><a href="#" data-account-logout>로그아웃</a></div></div>';nav.querySelector('[data-account-basket]').onclick=e=>{e.preventDefault();go(tfPlanRoute())};nav.querySelector('[data-account-profile]').onclick=e=>{e.preventDefault();go('account')};nav.querySelector('[data-account-logout]').onclick=async e=>{e.preventDefault();if(await tfLogout())render()}}
flow.addEventListener('click',async e=>{const logout=e.target.closest('[data-flow-account-logout]');if(!logout)return;e.preventDefault();if(await tfLogout())render()});
renderAccountHeader();
// TF-DEV: 서버에서 로그인 상태 확인 (확정 화면은 결과에 따라 문구가 달라져 다시 그림)
TF_AUTH.ready=TF_AUTH.refresh().then(user=>{if(!flow.hidden&&current().split('?')[0]==='confirm')render();return user});
$('.brand').href='#/';
window.addEventListener('hashchange',render);render();


// Reveal once when each column enters the viewport; preserve readable fallback.
const revealTargets=[...document.querySelectorAll('.about-category-grid > .about-category')];
const principles=document.querySelector('.about-principles');
if(principles)revealTargets.push(...principles.parentElement.children);
if('IntersectionObserver' in window && !motionPreference.matches){
 const revealObserver=new IntersectionObserver(entries=>{entries.forEach(entry=>{
  if(entry.isIntersecting){entry.target.classList.remove('reveal-wait');revealObserver.unobserve(entry.target);}
 });},{threshold:.12});
 revealTargets.forEach((el,i)=>{el.style.setProperty('--reveal-x',i%2===0?'-55px':'55px');el.classList.add('reveal-side','reveal-wait');revealObserver.observe(el);});
 motionPreference.addEventListener('change',e=>{if(e.matches){revealTargets.forEach(el=>el.classList.remove('reveal-wait'));revealObserver.disconnect();}});
}


const footerBrand=document.querySelector('.footer-brand');
if(footerBrand)footerBrand.innerHTML='<img class="footer-brand-logo" src="./assets/truefit-logo.png" alt="TrueFit"><p>Your needs, perfectly matched.<br>진짜 나에게 맞는 조합을 찾아드립니다.</p>';
const footerCompanyTitle=document.querySelector('.footer-company h2');
if(footerCompanyTitle)footerCompanyTitle.textContent='TrueFit 서비스 정보';
const footerDialog=document.querySelector('#footer-info-dialog');
const footerCopy={
 '이용약관':'정식 서비스 이용약관은 준비 중입니다. 현재 페이지는 서비스 흐름을 체험하는 목업이며, 실제 상품 판매나 결제는 진행되지 않습니다.',
 '개인정보 처리방침':'정식 개인정보 처리방침은 준비 중입니다. 이 목업의 표시 이름과 입력 조건, 리스트는 현재 브라우저의 로컬 저장소에 저장됩니다. 실제 계정 인증이나 이메일 발송은 하지 않습니다. 브라우저 사이트 데이터를 삭제하면 저장 내용이 지워집니다. 글꼴 로딩에는 Google Fonts 연결이 사용됩니다.',
 '제휴 문의':'제휴 문의 채널은 아직 등록되지 않았습니다. 정식 서비스 출시 시 안내할 예정입니다.',
 '고객센터':'고객지원 연락처와 운영시간은 준비 중입니다. 서비스 사용 방법은 하단의 자주 묻는 질문에서 확인할 수 있습니다.'
};
document.querySelectorAll('[data-footer-info]').forEach(b=>b.addEventListener('click',()=>{document.querySelector('#footer-info-title').textContent=b.dataset.footerInfo;document.querySelector('#footer-info-body').textContent=footerCopy[b.dataset.footerInfo];footerDialog.showModal()}));
document.querySelector('#footer-info-close').onclick=()=>footerDialog.close();
document.querySelector('#footer-service').addEventListener('change',e=>{const v=e.target.value;if(v==='pc'||v==='baby')choose(v);else if(v==='report')go(tfPlanRoute());e.target.value=''});
