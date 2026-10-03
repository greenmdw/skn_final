import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {Presentation,PresentationFile,FileBlob} from '@oai/artifact-tool';

const ROOT='C:/web_workspace/skn_final';
const B=ROOT+'/.ppt-build/truefit';
const TMP=B+'/redesign';
const OUT=ROOT+'/output/TrueFit_사업모델_인디고민트_v2.pptx';
const SKILL='C:/Users/green/.codex/plugins/cache/openai-primary-runtime/presentations/26.905.11957/skills/presentations';
const PY='C:/Users/green/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe';
process.env.RUNTIME_NODE_MODULES='C:/Users/green/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules';
const FONT='Malgun Gothic';
const C={indigo:'#2C2879',mint:'#2CB98C',green:'#168769',white:'#FFFFFF',ink:'#222239',muted:'#68687A',pale:'#E7F6F0',lilac:'#EFEEF8',line:'#DEDEE7',light:'#D8D8EE',panel:'#3C378C'};
const p=Presentation.create({slideSize:{width:1280,height:720}});
const source='사용자 제공 목업: C:/Users/green/Downloads/TrueFit Prototype v2.html. 화면의 가격·리뷰 수·제품 설명은 시연용 예시이며 실제 운영 성과가 아님.';
const src=await fs.readFile(B+'/build.mjs','utf8');
const notes=[...src.matchAll(/note\(s,('(?:[^'\\]|\\.)*'),(\[[^\n]*\])\);/g)].map(m=>Function('source','return ['+m[1]+','+m[2]+']')(source));
if(notes.length!==12)throw new Error('Expected 12 original speaker notes');
const bg={dark:new Uint8Array(await fs.readFile(B+'/assets/background-indigo.png')),light:new Uint8Array(await fs.readFile(B+'/assets/background-white.png'))};
let seq=0;
function tx(s,text,x,y,w,h,size=22,color=C.ink,bold=false,align='left'){
 const a=s.shapes.add({name:'text-'+(++seq),geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
 a.text=text;a.text.style={typeface:FONT,fontSize:size,color,bold,alignment:align,autoFit:'none',verticalAlignment:'top',insets:{left:0,right:0,top:0,bottom:0}};return a;
}
function panel(s,x,y,w,h,fill,rad=20,stroke='none'){
 return s.shapes.add({geometry:'roundRect',position:{left:x,top:y,width:w,height:h},borderRadius:rad,fill,line:{fill:stroke,width:stroke==='none'?0:1}});
}
function pill(s,text,x,y,w,fill,color,size=15){const a=panel(s,x,y,w,29,fill,15);a.text=text;a.text.style={typeface:FONT,fontSize:size,color,alignment:'center',verticalAlignment:'middle',insets:{left:8,right:8,top:0,bottom:0}};return a;}
function rule(s,x,y,w,col=C.line){return s.shapes.add({geometry:'line',position:{left:x,top:y,width:w,height:0},line:{fill:col,width:1}});}
function arrow(s,a,b,from='right',to='left',color=C.mint){const c=s.shapes.connect(a,b,{kind:'straight',fromSide:from,toSide:to,line:{fill:color,width:2.5},tail:{type:'triangle',width:'med',length:'med'}});c.bringToFront();return c;}
function node(s,label,x,y,w,h,fill=C.white,color=C.indigo){const a=panel(s,x,y,w,h,fill,18);a.text=label;a.text.style={typeface:FONT,fontSize:23,bold:true,color,alignment:'center',verticalAlignment:'middle',insets:{left:14,right:14,top:10,bottom:10}};return a;}
async function im(s,file,x,y,w,h,fit='contain',radius=22,crop){s.images.add({blob:new Uint8Array(await fs.readFile(file)),contentType:'image/png',alt:path.basename(file),fit,position:{left:x,top:y,width:w,height:h},geometry:'roundRect',borderRadius:radius,...(crop?{crop}: {})});}
function base(n,section,dark=false){
 const s=p.slides.add();s.background.fill=dark?C.indigo:C.white;
 s.images.add({blob:bg[dark?'dark':'light'],contentType:'image/png',alt:'Indigo and mint editorial background',position:{left:0,top:0,width:1280,height:720},fit:'cover'});
 tx(s,'TrueFit',56,31,130,31,22,dark?C.white:C.indigo,true);
 tx(s,'서비스',239,38,80,22,14,dark?C.light:C.muted);tx(s,'데이터',336,38,80,22,14,dark?C.light:C.muted);tx(s,'사업모델',433,38,98,22,14,dark?C.light:C.muted);
 pill(s,section,974,31,156,dark?C.mint:C.indigo,C.white,14);
 pill(s,'2026',1142,31,81,dark?C.panel:C.lilac,dark?C.light:C.indigo,14);
 tx(s,'TrueFit  /  유통·서비스',56,680,600,20,12,dark?C.light:C.muted);
 tx(s,String(n).padStart(2,'0')+' / 12',1143,677,80,24,14,dark?C.light:C.indigo,false,'right');
 const [speech,refs]=notes[n-1];
 s.speakerNotes.textFrame.setText(speech+'\n\n자료 및 상태: '+refs.join('\n')+'\n디자인 참고: 사용자 첨부 인디고·민트 피치덱 이미지. 배경은 생성된 추상 디자인이며 내용 텍스트와 도표는 편집 가능한 개체.');
 return s;
}
function heading(s,a,b,x=56,y=108,w=1160,dark=false,size=43){tx(s,a,x,y,w,60,size,dark?C.white:C.indigo,true);if(b)tx(s,b,x,y+57,w,61,size,C.mint,false);}
function point(s,num,title,body,x,y,w=450,dark=false){tx(s,num,x,y,42,32,21,dark?C.mint:C.green,true);tx(s,title,x+50,y,w-50,35,24,dark?C.white:C.indigo,true);tx(s,body,x+50,y+45,w-50,68,21,dark?C.light:C.muted);}
function caption(s,t,x,y,w,dark=false){tx(s,t,x,y,w,24,13,dark?C.light:C.muted);}

// 01 — dark editorial cover
{
 const s=base(1,'Business Pitch',true);
 tx(s,'TrueFit',56,153,640,112,88,C.mint,true);
 tx(s,'사양과 사용 경험을 함께 반영하는',59,290,615,55,31,C.white,true);
 tx(s,'PC 구매설계 플랫폼',59,346,612,64,42,C.white,false);
 tx(s,'나의 목적에 맞는 구성\n선택의 근거와 제품별 리뷰',61,458,530,82,23,C.light);
 await im(s,ROOT+'/web/public/assets/truefit-hero.png',743,130,482,437,'cover',30,{left:0.24,top:0,right:0,bottom:0});
 pill(s,'유통·서비스 분야',60,591,188,C.mint,C.white,18);
 tx(s,'2026 신격호 롯데 청년기업가대상',271,594,710,35,21,C.light);
}
// 02 — white editorial title + contrasting information panels
{
 const s=base(2,'Problem');
 heading(s,'PC 구매의','두 가지 정보 공백',56,116,530,false,43);
 tx(s,'함께 작동하는 구성과\n나에게 맞는 사용 경험을\n동시에 판단해야 합니다',59,292,436,134,24,C.muted);
 panel(s,570,122,654,221,C.indigo,24);
 tx(s,'01',598,149,82,61,46,C.mint,true);
 tx(s,'기술적으로 맞는가',700,150,480,43,30,C.white,true);
 tx(s,'CPU 소켓과 메모리 규격\n케이스 크기와 전력 여유\n전체 예산 안의 성능 균형',700,218,481,104,22,C.light);
 panel(s,570,366,654,221,C.pale,24);
 tx(s,'02',598,394,82,61,46,C.green,true);
 tx(s,'내가 쓰기에 편한가',700,394,480,44,30,C.indigo,true);
 tx(s,'밤에도 조용한 키보드\n작은 손에 맞는 마우스\n오래 사용하는 모니터의 체감',700,460,480,110,22,C.muted);
 tx(s,'가격·사양·리뷰를 여러 곳에서 찾고 조합하는 부담',60,616,1130,38,23,C.indigo,true);
}
// 03 — customer quote and three flat use cases
{
 const s=base(3,'Customer');
 heading(s,'초기 고객과','구매 과업',56,116,460,false,46);
 tx(s,'구매 목적은 분명하지만\n선택의 기준이 필요한 사용자',59,280,460,79,23,C.muted);
 panel(s,576,114,648,253,C.indigo,26);
 tx(s,'“150만 원으로 엘든링을 할 수 있는\n조용한 PC가 필요해요.”',610,169,579,110,31,C.white,true);
 caption(s,'대표 고객 시나리오 · 실제 인터뷰 인용 아님',610,319,568,true);
 const xs=[56,458,860];
 const titles=['첫 구매와 교체','체감 조건이 중요한 선택','구매 전 마지막 확인'];
 const bodies=['부품 지식이 부족한\n조립 PC 구매자','저소음·타건감·그립감이\n중요한 사용자','이미 받은 견적의\n가격과 호환성 점검'];
 xs.forEach((x,i)=>{tx(s,'0'+(i+1),x,420,84,66,47,C.green);rule(s,x,498,348);tx(s,titles[i],x,520,362,44,24,C.indigo,true);tx(s,bodies[i],x,570,358,66,21,C.muted);});
}
// 04 — native editable service diagram
{
 const s=base(4,'Service',true);
 heading(s,'세 가지 출발점,','하나의 구매 계획',56,105,990,true,43);
 const xs=[56,456,856];
 const titles=['새 PC 본체','받은 견적 점검','주변기기 견적'];
 const bodies=['용도와 예산으로\n부품 8종 구성','이미지·텍스트 인식\n가격과 호환성 비교','사양과 체감 조건으로\n필요한 품목 선택'];
 xs.forEach((x,i)=>{panel(s,x,268,368,205,i===1?C.mint:C.white,22);tx(s,'0'+(i+1),x+26,287,69,48,33,i===1?C.indigo:C.green);tx(s,titles[i],x+26,341,310,40,27,C.indigo,true);tx(s,bodies[i],x+26,397,320,67,22,i===1?C.indigo:C.muted);s.shapes.add({geometry:'downArrow',position:{left:x+172,top:493,width:24,height:28},fill:C.mint,line:{fill:'none',width:0}});});
 node(s,'통합 장바구니와 구매 리포트',56,541,1168,65,C.panel,C.white);
 tx(s,'판매처 연결     /     맞춤 조립 가이드     /     저장한 대화 이어가기',139,627,1060,30,21,C.light);
}
// 05 — screenshot-led split layout
{
 const s=base(5,'Journey');
 heading(s,'하나로 연결된','구매 여정',56,110,510,false,43);
 point(s,'01','조건 입력','용도·예산·우선순위 정리',56,302,357);
 point(s,'02','비교와 교체','이유 확인 후 대안으로 변경',56,421,357);
 point(s,'03','구매 이후 연결','리포트·가이드와 제품 리뷰',56,540,357);
 panel(s,435,206,790,432,C.indigo,26);
 pill(s,'TrueFit Prototype',457,223,194,C.mint,C.white,15);
 await im(s,B+'/assets/plan.png',451,267,758,349,'cover',14,{left:0,top:0.08,right:0,bottom:0.08});
 caption(s,'목업 화면 · 가격·리뷰 수는 시연용 예시',770,646,440);
}
// 06 — specification + qualitative evidence
{
 const s=base(6,'Recommendation');
 heading(s,'사양 적합성 +','경험 적합성',56,105,760,false,43);
 tx(s,'기술 조건을 충족하는 후보 안에서 사용 경험의 근거를 찾습니다',59,238,1136,34,22,C.muted);
 panel(s,56,297,667,325,C.indigo,24);
 await im(s,B+'/assets/periPlan.png',69,310,641,299,'cover',16,{left:0.13,top:0.12,right:0,bottom:0.08});
 const ys=[293,407,521];
 [['사양 적합성','규격·성능·연결 방식·예산'],['경험 적합성','소음·타건감·피로감 관련 리뷰'],['설명 가능한 선택','근거 문장과 표본 수 함께 표시']].forEach((a,i)=>{pill(s,'0'+(i+1),769,ys[i]+1,53,i===1?C.mint:C.indigo,C.white,17);tx(s,a[0],841,ys[i]-1,364,36,25,C.indigo,true);tx(s,a[1],770,ys[i]+51,439,55,21,C.muted);});
 caption(s,'목업 화면 · 리뷰 인용과 건수는 시연용 예시',58,640,716);
}
// 07 — proprietary review asset and editable feedback loop
{
 const s=base(7,'Data Asset',true);
 heading(s,'제품별 리뷰,','플랫폼의 데이터 자산',56,107,1130,true,43);
 const rows=[['제품','정확한 모델과 구성'],['사용 맥락','목적·기간·환경'],['사용 경험','장점·불편·체감 특성'],['신뢰 단서','구매 확인·중복·표본 수']];
 tx(s,'리뷰에 담을 정보',58,270,480,39,26,C.mint,true);
 rows.forEach((a,i)=>{let y=339+i*63;tx(s,a[0],58,y,131,35,21,C.white,true);tx(s,a[1],208,y,315,39,21,C.light);if(i<3)rule(s,58,y+47,449,'#514D99');});
 const a=node(s,'목적에 맞춘 추천',580,294,276,78,C.white,C.indigo),b=node(s,'구매 후 제품 리뷰',946,294,278,78,C.mint,C.indigo),c=node(s,'경험 특성 분석',946,467,278,78,C.white,C.indigo),d=node(s,'근거 품질 평가',580,467,276,78,C.panel,C.white);
 arrow(s,a,b);arrow(s,b,c,'bottom','top');arrow(s,c,d,'left','right');arrow(s,d,a,'top','bottom');
 tx(s,'표본이 적으면 판단을 유보하고\n추천 개선은 사용자 실험으로 확인',607,584,595,65,22,C.light);
 caption(s,'신규 개발 계획 · 리뷰 작성 UI와 수집 정책 포함',58,640,550,true);
}
// 08 — editable comparison table
{
 const s=base(8,'Positioning');
 heading(s,'기존 구매 방법과','TrueFit의 연결 가치',56,104,1160,false,42);
 const values=[['구매 방법','주요 활용','TrueFit에서 연결할 가치'],['가격 비교','상품 사양과 판매 가격 확인','개인 조건과 전체 구성 예산'],['커뮤니티·영상','사용 경험과 구매 조언 탐색','제품별 경험 근거와 사용 맥락'],['범용 AI','자연어 질문과 답변','카탈로그·호환 규칙과 연결'],['TrueFit','구매설계와 제품별 리뷰 축적','사양·경험·구매 기록의 결합']];
 const t=s.tables.add({rows:5,columns:3,left:56,top:267,width:1168,height:289,columnWidths:[222,418,528],values});
 for(let r=0;r<5;r++)for(let c=0;c<3;c++){const cell=t.getCell(r,c);cell.fill=r===0?C.indigo:r===4?C.pale:C.white;cell.text.style={typeface:FONT,fontSize:21,color:r===0?C.white:C.ink,bold:r===0||r===4,verticalAlignment:'middle',insets:{left:16,right:12,top:8,bottom:8}};}
 t.borders.assign({fill:C.line,width:1});
 pill(s,'핵심 차별화',57,584,156,C.mint,C.white,17);
 tx(s,'구매 맥락에 연결된 자체 리뷰 데이터',238,580,938,45,27,C.indigo,true);
 caption(s,'구매 방식별 일반적 활용을 정리한 전략 비교이며, 개별 서비스의 기능 유무를 단정하지 않습니다.',58,636,1157);
}
// 09 — dark revenue model, with honest staged expansion
{
 const s=base(9,'Business Model',true);
 heading(s,'수익 구조와','단계별 확장',56,108,700,true,43);
 tx(s,'초기 수익',893,116,295,34,21,C.light);
 tx(s,'구매 전환\n제휴 수수료',889,161,330,109,35,C.mint,true);
 const a=node(s,'소비자',56,316,275,73,C.white,C.indigo),b=node(s,'TrueFit',497,316,281,73,C.mint,C.indigo),c=node(s,'제휴 판매점',949,316,275,73,C.white,C.indigo);
 arrow(s,a,b);arrow(s,b,c);
 tx(s,'무료 구매설계',337,273,174,33,20,C.light);tx(s,'구매 연결',797,273,145,33,20,C.light);
 tx(s,'확인된 구매 전환을 기준으로 수수료 정산',58,419,1118,37,24,C.white);
 panel(s,56,490,568,133,C.panel,22);panel(s,648,490,576,133,C.panel,22);
 tx(s,'02',80,514,55,35,23,C.mint,true);tx(s,'판매점용 SaaS·API',143,510,439,39,25,C.white,true);tx(s,'추천 위젯·견적 검증의 월 또는 사용량 과금',80,568,518,42,21,C.light);
 tx(s,'03',672,514,55,35,23,C.mint,true);tx(s,'집계 리뷰 인사이트',735,510,441,39,25,C.white,true);tx(s,'제조사·유통사를 위한 사용 경험 분석',672,568,521,42,21,C.light);
 caption(s,'사업 가설 · 제휴 조건과 단가는 검증 예정 · 추천 순위와 수수료의 분리 원칙',58,641,1155,true);
}
// 10 — screenshot as acquisition context, staged go-to-market
{
 const s=base(10,'Go-to-Market');
 heading(s,'초기 시장과','시장 진입',56,105,560,false,43);
 tx(s,'국내 조립 PC와 주변기기 구매자',58,251,554,38,22,C.muted);
 await im(s,B+'/assets/check.png',56,313,545,267,'cover',23,{left:0.20,top:0.08,right:0,bottom:0.06});
 point(s,'01','외부 견적 무료 점검','구매를 고민하는 사용자의 첫 진입점',659,126,565);
 point(s,'02','커뮤니티·크리에이터','용도별 추천과 사용 경험 콘텐츠',659,273,565);
 point(s,'03','판매점 파일럿','상담에 적용하고 구매 연결 확인',659,420,565);
 caption(s,'목업 화면 · 외부 견적 점검 서비스 예시',58,586,560);
 const labs=['견적 완성률','판매처 이동률','확인된 구매 전환','제품별 리뷰 작성률'];
 labs.forEach((a,i)=>{panel(s,56+i*299,623,272,38,i%2===0?C.indigo:C.pale,19);tx(s,a,66+i*299,631,252,27,18,i%2===0?C.white:C.green,false,'center');});
}
// 11 — current execution plus native timeline
{
 const s=base(11,'Roadmap');
 panel(s,56,115,362,514,C.indigo,27);
 pill(s,'현재 구현',82,143,133,C.mint,C.white,17);
 tx(s,'PC 추천 흐름',83,210,305,54,32,C.white,true);
 tx(s,'조건 대화와 PC 추천\n\n부품 교체와 호환 검사\n\n장바구니·저장 리포트',84,297,299,221,22,C.light);
 tx(s,'React · FastAPI\nPostgreSQL',84,536,300,61,20,C.mint);
 heading(s,'현재 구현과','12개월 개발 계획',462,108,747,false,40);
 const xs=[462,722,982],ws=[233,233,242];
 const data=[['1–3개월','서비스 연결','견적 점검과\n주변기기 화면'],['4–6개월','리뷰 수집','제품 모델·사용 맥락\n구매 확인'],['7–12개월','추천 반영과 실증','사용자 평가와\n판매점 파일럿']];
 data.forEach((a,i)=>{let x=xs[i];pill(s,a[0],x,285,ws[i],i===1?C.mint:C.indigo,C.white,20);tx(s,a[1],x,354,ws[i],80,26,C.indigo,true);tx(s,a[2],x,451,ws[i],89,21,C.muted);});
 rule(s,462,555,762);
 tx(s,'데이터 확보와 사용자 검증 결과에 따라 일정 조정',463,584,749,41,20,C.muted);
 caption(s,'현재 구현은 코드·문서 확인 기준 · 향후 일정은 제안 목표',58,641,1126);
}
// 12 — closing slide / funding use, no invented team members
{
 const s=base(12,'Execution',true);
 heading(s,'실행 기반과','지원금 활용',56,108,768,true,46);
 tx(s,'확인된 실행 기반',60,307,520,46,28,C.mint,true);
 tx(s,'추천 엔진과 호환 규칙\n상품·리뷰 데이터 처리 구조\n대화형 화면과 저장 리포트',60,380,520,128,23,C.light);
 tx(s,'프로젝트 코드와 목업을 기반으로\n실제 구매 경험과 데이터를 검증합니다',60,554,541,72,22,C.white);
 panel(s,671,139,553,486,C.white,27);
 tx(s,'지원금 활용 우선순위',703,167,484,48,28,C.indigo,true);
 const rows=[['01','데이터 기반 확보','상품·가격 갱신과 제품 식별 정비'],['02','자체 리뷰 시스템','사용 맥락 수집과 근거 품질 관리'],['03','사용자·판매점 검증','구매 전환과 추천 적합성 측정']];
 rows.forEach((a,i)=>{let y=259+i*116;pill(s,a[0],703,y,51,C.mint,C.white,17);tx(s,a[1],775,y-3,405,42,25,C.indigo,true);tx(s,a[2],704,y+50,483,47,21,C.muted);if(i<2)rule(s,704,y+96,481);});
}

await fs.mkdir(TMP,{recursive:true});
const candidate=TMP+'/candidate.pptx';
await (await PresentationFile.exportPptx(p)).save(candidate);
await fs.mkdir(TMP+'/draft-renders',{recursive:true});
for(let i=0;i<12;i++){
 const png=await p.export({slide:p.slides.items[i],format:'png',scale:1});
 await fs.writeFile(TMP+'/draft-renders/'+String(i+1).padStart(2,'0')+'.png',new Uint8Array(await png.arrayBuffer()));
 console.log('Draft rendered',i+1);
}
if(process.argv.includes('--draft-only'))process.exit(0);
const {finalizePresentation}=await import(pathToFileURL(SKILL+'/container_tools/artifact_tool_utils.mjs').href);
const result=await finalizePresentation({workspaceDir:ROOT,candidatePath:candidate,finalPath:OUT,pythonExecutable:PY,integrityValidatorPath:SKILL+'/container_tools/inspect_presentation_package_integrity.py',layoutValidatorPath:SKILL+'/container_tools/inspect_presentation_layout_geometry.py',layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit','--require-native-table-slide','8'],explicitTotalSlideCount:12,requiredNativeTableOwnerSlides:[8],fontPolicy:{basis:'design',families:[FONT]},verifyArtifactToolImport:true,receiptPath:TMP+'/validation.json'});
console.log('Finalized',result.finalPath);
const final=await PresentationFile.importPptx(await FileBlob.load(OUT));
await fs.mkdir(TMP+'/final-renders',{recursive:true});
for(let i=0;i<12;i++){
 const png=await final.export({slide:final.slides.items[i],format:'png',scale:1});
 await fs.writeFile(TMP+'/final-renders/'+String(i+1).padStart(2,'0')+'.png',new Uint8Array(await png.arrayBuffer()));
 console.log('Final rendered',i+1);
}
