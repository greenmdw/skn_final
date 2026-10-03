import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {Presentation, PresentationFile} from '@oai/artifact-tool';

const ROOT='C:/web_workspace/skn_final';
const BUILD=ROOT+'/.ppt-build/truefit';
const SKILL='C:/Users/green/.codex/plugins/cache/openai-primary-runtime/presentations/26.905.11957/skills/presentations';
const PY='C:/Users/green/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe';
const OUT=ROOT+'/output/TrueFit_사업모델_발표자료.pptx';
const FONT='Malgun Gothic';
process.env.RUNTIME_NODE_MODULES='C:/Users/green/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules';
const C={ink:'#171B24',muted:'#5E6674',blue:'#244BC4',pale:'#EEF2FC',line:'#DDE2EA',white:'#FFFFFF',navy:'#111B36',green:'#237462'};
const p=Presentation.create({slideSize:{width:1280,height:720}});
let seq=0;
function txt(s,t,x,y,w,h,sz=22,color=C.ink,bold=false){
  const a=s.shapes.add({name:'text-'+(++seq),geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
  a.text=t; a.text.style={typeface:FONT,fontSize:sz,color,bold,autoFit:'none',verticalAlignment:'top',insets:{left:0,right:0,top:0,bottom:0}};return a;
}
function box(s,x,y,w,h,fill=C.pale,stroke='none'){return s.shapes.add({geometry:'rect',position:{left:x,top:y,width:w,height:h},fill,line:{fill:stroke,width:stroke==='none'?0:1}});}
function line(s,x,y,w,color=C.line){return s.shapes.add({geometry:'line',position:{left:x,top:y,width:w,height:0},fill:'none',line:{fill:color,width:1}});}
function arrow(s,a,b,from='right',to='left'){s.shapes.connect(a,b,{kind:'straight',fromSide:from,toSide:to,line:{fill:C.blue,width:2},tail:{type:'triangle',width:'sm',length:'sm'}});}
function node(s,label,x,y,w,h=70,fill=C.pale,color=C.ink){const a=box(s,x,y,w,h,fill);a.text=label;a.text.style={typeface:FONT,fontSize:22,bold:true,color,alignment:'center',verticalAlignment:'middle',insets:{left:10,right:10,top:7,bottom:7}};return a;}
async function img(s,name,x,y,w,h,crop){s.images.add({blob:new Uint8Array(await fs.readFile(name)),contentType:'image/png',alt:path.basename(name),position:{left:x,top:y,width:w,height:h},fit:'contain',...(crop?{crop}: {})});}
function footer(s,n,note=''){line(s,64,668,1152);txt(s,'TrueFit',64,683,140,20,13,C.muted,true);if(note)txt(s,note,220,684,930,20,12,C.muted);txt(s,String(n).padStart(2,'0'),1170,681,44,22,15,C.muted,false);}
function slide(n,title,sub='',dark=false){const s=p.slides.add();s.background.fill=dark?C.navy:C.white;txt(s,title,64,47,1150,59,36,dark?C.white:C.ink,true);if(sub)txt(s,sub,66,116,1140,35,20,dark?'#C8D2EE':C.muted);if(!dark)footer(s,n);return s;}
function point(s,num,title,body,x,y,w=450){txt(s,num,x,y,40,35,21,C.blue,true);txt(s,title,x+52,y,w-52,37,24,C.ink,true);txt(s,body,x+52,y+45,w-52,67,21,C.muted);}
function note(s,text,sources=[]){s.speakerNotes.textFrame.setText(text+'\n\n자료 및 상태: '+sources.join('\n'));}
const source='사용자 제공 목업: C:/Users/green/Downloads/TrueFit Prototype v2.html. 화면의 가격·리뷰 수·제품 설명은 시연용 예시이며 실제 운영 성과가 아님.';

// 01 Cover
{
const s=p.slides.add();s.background.fill=C.white;
await img(s,ROOT+'/web/public/assets/truefit-hero.png',555,0,725,720,{left:0.34,top:0,right:0,bottom:0});
txt(s,'TrueFit',64,162,490,83,64,C.ink,true);
txt(s,'사양과 사용 경험을\n함께 반영하는\nPC 구매설계 플랫폼',66,264,460,125,30,C.ink,true);
txt(s,'나의 목적에 맞는 구성\n근거를 확인하는 추천\n사용 경험이 쌓이는 리뷰',68,412,422,114,23,C.muted);
txt(s,'2026 신격호 롯데 청년기업가대상\n① 유통·서비스 분야',68,621,454,50,16,C.muted);
note(s,'안녕하세요. TrueFit은 PC를 잘 모르는 사용자도 자신의 목적과 예산에 맞는 제품을 고를 수 있도록 돕는 구매설계 플랫폼입니다. 가격과 사양에 실제 리뷰에 담긴 소음과 사용감까지 더해 추천합니다. 새 PC 구성과 외부 견적 점검, 주변기기 추천을 연결하고, 구매 후에는 제품별 사용 경험을 축적하는 서비스를 목표로 합니다.',[source,'표지 이미지: 프로젝트 자산 web/public/assets/truefit-hero.png. 연출 이미지.']);
}
// 02 Problem
{
const s=slide(2,'PC 구매의 두 가지 정보 공백','함께 작동하는 구성과 나에게 맞는 사용 경험을 동시에 판단해야 합니다');
txt(s,'01',68,197,80,45,32,C.blue,true);txt(s,'기술적으로 맞는가',68,258,490,52,30,C.ink,true);
txt(s,'CPU 소켓과 메모리 규격\n케이스 크기와 전력 여유\n전체 예산 안의 성능 균형',68,337,490,140,24,C.muted);
line(s,620,205,0);box(s,620,201,1,304,C.line);
txt(s,'02',682,197,80,45,32,C.blue,true);txt(s,'내가 쓰기에 편한가',682,258,500,52,30,C.ink,true);
txt(s,'밤에 사용해도 조용한 키보드\n작은 손에 맞는 마우스\n오래 사용하는 모니터의 체감',682,337,500,140,24,C.muted);
box(s,64,553,1152,71,C.pale);txt(s,'가격·사양·리뷰를 여러 곳에서 찾고 조합하는 부담',88,575,1100,38,24,C.blue,true);
note(s,'PC 구매자는 두 가지 문제를 동시에 해결해야 합니다. 먼저 부품이 서로 맞고 예산 안에서 필요한 성능을 내는지 확인해야 합니다. 동시에 같은 사양의 제품 중 무엇이 더 조용한지, 어떤 마우스가 손에 편한지도 판단해야 합니다. 저희가 해결하려는 문제는 이렇게 흩어진 정보를 사용자 목적에 맞춰 다시 조합해야 하는 부담입니다. 이 문제의 크기는 초기 사용자 인터뷰와 사용성 테스트로 검증할 계획입니다.',[source,'문제 정의는 사업 가설이며 정량 조사 결과를 주장하지 않음.']);
}
// 03 Customer
{
const s=slide(3,'초기 고객과 구매 과업','구매 목적은 분명하지만 제품 선택의 기준이 필요한 사용자');
box(s,64,190,534,391,C.navy);
txt(s,'“150만 원으로\n엘든링을 할 수 있는\n조용한 PC가 필요해요.”',97,252,460,185,35,C.white,true);
txt(s,'대표 고객 시나리오 · 실제 인터뷰 인용 아님',98,520,445,29,15,'#BECBED');
point(s,'01','첫 구매와 교체','부품 지식이 부족한 조립 PC 구매자',656,201,545);
point(s,'02','체감 조건이 중요한 선택','저소음·타건감·그립감이 중요한 사용자',656,343,545);
point(s,'03','구매 전 마지막 확인','이미 받은 견적의 가격·호환성 점검',656,485,545);
note(s,'초기 고객은 구매 목적은 분명하지만 제품 선택의 기준이 필요한 사용자입니다. 예를 들어 150만 원으로 조용한 게임용 PC를 원한다고 말할 수는 있지만, 어떤 부품을 골라야 하는지는 모르는 고객입니다. 주변기기에서도 작은 손에 맞는 마우스처럼 원하는 경험은 표현할 수 있습니다. TrueFit은 이 표현을 구매 조건으로 바꾸고, 추천 제품과 선택 근거를 연결합니다.',[source,'대표 고객은 기획 시나리오.']);
}
// 04 Structure
{
const s=slide(4,'TrueFit 서비스 구조','서로 다른 구매 출발점을 하나의 구매 계획으로 연결합니다');
const a=node(s,'새 PC 본체',64,202,343,75),b=node(s,'받은 견적 점검',468,202,343,75),c=node(s,'주변기기 견적',873,202,343,75);
txt(s,'용도와 예산으로\n부품 8종 구성',85,302,310,73,23,C.muted);
txt(s,'이미지·텍스트 인식\n가격과 호환성 비교',489,302,310,73,23,C.muted);
txt(s,'사양과 체감 조건으로\n필요한 품목 선택',895,302,310,73,23,C.muted);
for(const x of [222,627,1032])s.shapes.add({geometry:'downArrow',position:{left:x,top:395,width:26,height:31},fill:C.blue,line:{fill:'none',width:0}});
const d=node(s,'통합 장바구니와 구매 리포트',64,450,1152,72,C.blue,C.white);
txt(s,'판매처 연결     /     맞춤 조립 가이드     /     저장한 대화 이어가기',230,564,850,39,22,C.muted);
note(s,'TrueFit에는 세 가지 진입점이 있습니다. 새 PC를 처음부터 구성하거나, 다른 곳에서 받은 견적을 점검하거나, 필요한 주변기기만 고를 수 있습니다. 사용자가 어느 경로로 시작하든 선택한 제품은 통합 장바구니와 구매 리포트로 이어집니다. 리포트에는 판매처 링크와 구성에 맞는 조립 가이드를 담고, 저장한 견적과 대화는 다시 열어 활용하도록 설계했습니다.',[source,'전체 서비스 설계 범위. 현재 구현 상태는 11장 참조.']);
}
// 05 Journey
{
const s=slide(5,'하나로 연결된 구매 여정','조건을 말하고, 추천의 이유를 확인하며, 원하는 구성으로 수정합니다');
await img(s,BUILD+'/assets/plan.png',430,196,786,418,{left:0.30,top:0.085,right:0.02,bottom:0.02});
point(s,'01','조건 입력','용도·예산·우선순위를 대화로 정리',64,201,340);
point(s,'02','비교와 교체','추천 이유 확인 후 대안으로 변경',64,349,340);
point(s,'03','구매 이후 연결','리포트·조립 가이드와 제품 리뷰',64,497,340);
txt(s,'목업 화면 · 가격·리뷰 수는 시연용 예시',777,633,437,22,13,C.muted);
note(s,'사용자는 전문 용어를 몰라도 원하는 조건을 말할 수 있습니다. TrueFit은 대화에서 조건을 정리하고, 추천 결과에서 각 부품을 선택한 이유와 확인이 필요한 항목을 제시합니다. 화면은 목업 예시입니다. 사용자는 더 저렴한 제품을 찾거나 특정 부품을 교체하며 구성을 완성할 수 있습니다. 이후에는 리포트와 조립 가이드를 활용하고, 실제 사용한 제품의 리뷰를 남기는 과정으로 연결할 계획입니다.',[source]);
}
// 06 recommendation
{
const s=slide(6,'사양 적합성과 경험 적합성','기술 조건을 충족하는 후보 안에서 사용 경험의 근거를 찾습니다');
await img(s,BUILD+'/assets/periPlan.png',64,194,699,413,{left:0.32,top:0.21,right:0.02,bottom:0.13});
point(s,'01','사양 적합성','규격·성능·연결 방식·예산',813,203,407);
point(s,'02','경험 적합성','소음·타건감·피로감 관련 리뷰',813,342,407);
point(s,'03','설명 가능한 선택','근거 문장과 표본 수를 함께 표시',813,481,407);
txt(s,'목업 화면 · 리뷰 인용과 건수는 시연용 예시',66,630,700,23,13,C.muted);
note(s,'추천은 사양과 리뷰를 함께 사용하도록 설계했습니다. 먼저 가격과 규격처럼 반드시 충족해야 하는 조건으로 후보를 좁힙니다. 이후 리뷰에서 소음과 타건감처럼 체감에 관련된 경험을 찾습니다. 화면은 이러한 추천 방식을 표현한 목업이며 리뷰 수치는 시연용 예시입니다. 리뷰의 눈이 편하다는 평가는 주관적 경험으로 다루며 효과를 보장하지 않습니다. 자료가 부족한 경우에는 그 한계도 함께 알립니다.',[source,'추천 설계: 규칙 기반 필터와 리뷰 근거 활용. 성능 개선 효과는 향후 검증 대상.']);
}
// 07 review asset
{
const s=slide(7,'제품별 리뷰 데이터 자산','사용 맥락을 연결한 리뷰를 축적하고 추천 개선에 활용합니다');
txt(s,'리뷰에 담을 정보',64,194,435,40,26,C.ink,true);
const rows=[['제품','정확한 모델과 구성'],['사용 맥락','목적·기간·환경'],['사용 경험','장점·불편·체감 특성'],['신뢰 단서','구매 확인·중복·표본 수']];
for(let i=0;i<rows.length;i++){const y=264+i*72;line(s,64,y-12,424);txt(s,rows[i][0],64,y,132,36,21,C.blue,true);txt(s,rows[i][1],204,y,288,45,21,C.ink);}
const a=node(s,'목적에 맞춘 추천',567,244,263,74),b=node(s,'구매 후 제품 리뷰',928,244,263,74),c=node(s,'경험 특성 분석',928,435,263,74),d=node(s,'근거 품질 평가',567,435,263,74);
arrow(s,a,b);arrow(s,b,c,'bottom','top');arrow(s,c,d,'left','right');arrow(s,d,a,'top','bottom');
txt(s,'표본이 적으면 판단을 유보하고,\n추천 개선은 사용자 실험으로 확인',593,560,590,72,22,C.muted);
txt(s,'신규 개발 계획 · 리뷰 작성 UI와 수집 정책 포함',65,629,810,24,13,C.muted);
note(s,'자체 리뷰는 TrueFit의 장기적인 자산입니다. 제품 모델뿐 아니라 어떤 목적으로, 얼마나 오래, 어떤 환경에서 사용했는지 함께 수집할 계획입니다. 구매 확인 리뷰와 일반 리뷰를 구분하고 중복이나 비정상적인 집중도 살펴보겠습니다. 핵심은 리뷰 수 자체보다 사용 맥락과 연결된 정보입니다. 초기에는 사용 권한을 확보한 자료와 검수된 근거를 활용하고 자체 리뷰를 늘려 가겠습니다. 추천 품질이 실제로 개선되는지는 사용자 실험으로 확인하겠습니다.',[source,'사용자 추가 요구사항: 자체 제품 리뷰 수집 및 비정형 경험 데이터 기반 추천. 신규 개발 계획.']);
}
// 08 Comparison native table
{
const s=slide(8,'기존 구매 방법과의 차이','흩어진 정보를 한 번의 구매 과정에서 연결하는 전략');
const values=[['구매 방법','주요 활용','TrueFit에서 연결할 가치'],['가격 비교','상품 사양과 판매 가격 확인','개인 조건과 전체 구성 예산'],['커뮤니티·영상','사용 경험과 구매 조언 탐색','제품별 경험 근거와 사용 맥락'],['범용 AI','자연어 질문과 답변','카탈로그·호환 규칙과 연결'],['TrueFit','구매설계와 제품별 리뷰 축적','사양·경험·구매 기록의 결합']];
const t=s.tables.add({rows:5,columns:3,left:64,top:207,width:1152,height:339,columnWidths:[210,374,568],values});
for(let r=0;r<5;r++)for(let c=0;c<3;c++){const cell=t.getCell(r,c);cell.fill=r===0?C.navy:r===4?C.pale:C.white;cell.text.style={typeface:FONT,fontSize:21,color:r===0?C.white:C.ink,bold:r===0||r===4,verticalAlignment:'middle',insets:{left:16,right:12,top:10,bottom:10}};}
t.borders.assign({fill:C.line,width:1});
txt(s,'차별화의 중심: 구매 맥락에 연결된 자체 리뷰 데이터',66,581,1140,42,26,C.blue,true);
txt(s,'구매 방식별 일반적 활용을 정리한 전략 비교이며, 개별 서비스의 기능 유무를 단정하지 않습니다.',65,634,1150,22,13,C.muted);
note(s,'소비자는 가격 비교와 커뮤니티, AI를 목적에 따라 함께 사용합니다. TrueFit의 전략은 이러한 정보 탐색을 사용자 조건에 맞는 하나의 구매 과정으로 연결하는 것입니다. 차별화의 중심에는 정확한 제품 모델과 사용 목적에 연결한 자체 리뷰가 있습니다. 다만 리뷰를 보유하는 것만으로 경쟁력이 보장되지는 않습니다. 조건별 데이터 범위와 근거 품질을 높여 실제로 더 적합한 선택을 돕는지 검증하겠습니다.',[source,'비교표는 사업 포지셔닝 설명. 개별 경쟁 서비스의 현행 기능 조사표가 아님.']);
}
// 09 Business
{
const s=slide(9,'수익 구조','초기에는 구매 전환, 이후에는 판매점 도입과 집계 분석으로 확장');
const a=node(s,'소비자',64,231,256,92),b=node(s,'TrueFit',491,231,280,92,C.blue,C.white),c=node(s,'제휴 판매점',948,231,268,92);
arrow(s,a,b);arrow(s,b,c);txt(s,'무료 구매설계',341,197,162,32,19,C.muted);txt(s,'구매 연결',792,197,147,32,19,C.muted);
txt(s,'초기 수익: 확인된 구매 전환에 따른 제휴 수수료',173,371,1030,46,26,C.blue,true);
line(s,64,452,1152);
point(s,'02','판매점용 SaaS·API','추천 위젯·견적 검증의 월 또는 사용량 과금',64,482,540);
point(s,'03','집계 리뷰 인사이트','제조사·유통사를 위한 사용 경험 분석',665,482,551);
txt(s,'사업 가설 · 제휴 조건과 단가는 검증 예정 · 추천 순위와 수수료의 분리 원칙',65,632,1150,24,13,C.muted);
note(s,'소비자에게는 기본 구매설계를 무료로 제공하고, 판매처에서 실제 구매가 확인됐을 때 제휴 수수료를 받는 모델을 우선 검증하겠습니다. 다음 단계에서는 판매점에 추천 위젯과 견적 검증 API를 제공합니다. 리뷰가 충분히 쌓이면 사용 목적별 선호와 반복 불만을 집계한 분석 서비스도 검토할 수 있습니다. 원문이나 개인 정보 판매를 전제로 하지 않습니다. 현재 제휴 매출은 검증 전 가설이며, 구매 추적과 환불 반영, 데이터 비용을 포함해 수익성을 확인할 계획입니다.',[source,'수익 구조 및 정책은 기획안. 제휴 계약·매출 실적 없음으로 취급.']);
}
// 10 GTM
{
const s=slide(10,'초기 시장과 시장 진입','국내 조립 PC와 주변기기 구매자의 구체적인 구매 과업부터 시작');
txt(s,'사용자 확보',64,199,460,46,28,C.ink,true);
point(s,'01','외부 견적 무료 점검','구매를 고민 중인 사용자의 첫 진입점',64,267,540);
point(s,'02','커뮤니티·크리에이터','용도별 추천과 실제 사용 경험 콘텐츠',64,408,540);
point(s,'03','판매점 파일럿','상담 과정에 적용하고 구매 연결 확인',64,543,540);
txt(s,'사업성 검증',712,199,490,46,28,C.ink,true);
const labels=['견적 완성률','판매처 이동률','확인된 구매 전환','제품별 리뷰 작성률'];
labels.forEach((t,i)=>{const y=279+i*73;txt(s,String(i+1).padStart(2,'0'),714,y,55,35,21,C.blue,true);txt(s,t,785,y,410,36,24,C.ink);line(s,714,y+52,488);});
note(s,'초기에는 국내 조립 PC와 주변기기를 함께 다루되, 외부 견적 무료 점검을 사용자 확보의 첫 접점으로 삼겠습니다. 커뮤니티와 크리에이터 협업으로 구매 상황이 분명한 사용자를 만나고, 판매점과는 소규모 파일럿을 제안할 계획입니다. 견적 완성과 판매처 이동, 실제 구매 확인까지 이어지는 비율을 측정하고 구매 후 리뷰 작성도 확인하겠습니다. 사용자 확보 비용과 건당 제휴 수익, 추천 운영 비용을 함께 비교해 사업성을 판단하겠습니다.',[source,'채널·지표는 검증 계획이며 실제 확보 고객이나 제휴 실적이 아님.']);
}
// 11 Roadmap
{
const s=slide(11,'현재 개발 수준과 12개월 계획','현재 구현한 PC 추천 흐름을 전체 서비스와 자체 리뷰로 확장');
txt(s,'현재 구현',64,204,285,48,28,C.blue,true);
txt(s,'조건 대화·PC 추천\n부품 교체와 호환 검사\n장바구니·저장 리포트',64,277,455,119,24,C.ink);
txt(s,'React · FastAPI · PostgreSQL',64,436,470,34,20,C.muted);
txt(s,'코드·문서 확인 기준',64,486,450,30,15,C.muted);
const stages=[['1–3개월','서비스 연결','견적 점검·주변기기 화면'],['4–6개월','리뷰 수집','제품 모델·사용 맥락·구매 확인'],['7–12개월','추천 반영과 실증','사용자 평가·판매점 파일럿']];
stages.forEach((r,i)=>{const y=198+i*140;txt(s,r[0],648,y,180,33,19,C.blue,true);txt(s,r[1],648,y+38,540,40,27,C.ink,true);txt(s,r[2],648,y+88,540,38,21,C.muted);if(i<2)line(s,648,y+128,550);});
txt(s,'일정은 제안 목표이며, 데이터 확보와 사용자 검증 결과에 따라 조정합니다.',65,632,1140,24,13,C.muted);
note(s,'현재 코드에는 조건 대화, PC 추천, 부품 교체, 호환 검사, 장바구니와 저장 리포트가 있습니다. 목업으로 정의한 전체 서비스와 현재 구현 범위를 구분해 보여드리고 있습니다. 앞으로 3개월은 외부 견적과 주변기기 서비스 연결을 우선하고, 6개월까지 제품별 리뷰 수집 구조를 구축하는 계획입니다. 이후 리뷰를 추천에 반영하고 사용자 평가와 판매점 파일럿으로 효과를 검증하겠습니다. 이는 제안 일정으로 데이터 확보와 검증 결과에 따라 조정할 수 있습니다.',[source,'프로젝트 README.md, web/src/pages 및 src 추천 관련 코드의 이전 대화 내 확인. 이번 PPT 작업에서 실행 테스트를 수행한 것은 아님.']);
}
// 12 Team and use
{
const s=slide(12,'팀과 지원금 활용','구현한 제품을 실제 구매 경험과 데이터로 검증하겠습니다');
txt(s,'확인된 실행 기반',64,200,527,48,29,C.ink,true);
txt(s,'추천 엔진과 호환 규칙\n상품·리뷰 데이터 처리 구조\n대화형 화면과 저장 리포트',64,281,536,146,24,C.ink);
txt(s,'프로젝트 코드와 서비스 목업을\n기반으로 검증 단계에 진입',64,483,529,78,22,C.muted);
txt(s,'지원금 활용 우선순위',688,200,521,48,29,C.ink,true);
point(s,'01','데이터 기반 확보','상품·가격 갱신과 제품 식별 정비',688,278,526);
point(s,'02','자체 리뷰 시스템','사용 맥락 수집과 근거 품질 관리',688,398,526);
point(s,'03','실제 사용자·판매점 검증','구매 전환과 추천 적합성 측정',688,518,526);
note(s,'저희는 추천 엔진과 데이터베이스, 사용자 화면을 갖춘 프로젝트를 바탕으로 다음 검증 단계에 들어가고자 합니다. 지원금은 상품과 가격 데이터 정비, 자체 리뷰 수집 시스템, 사용자와 판매점 실증에 우선 사용하겠습니다. 핵심 목표는 사용자가 자신의 목적에 맞는 제품을 선택하도록 돕는 것입니다. 구매 전에 선택의 근거를 제공하고, 구매 후에는 사용 경험을 축적해 다음 사용자의 추천을 개선하겠습니다. 감사합니다.',[source,'팀원 성명·경력·역할 배분은 제공되지 않아 기재하지 않음. 지원금 세부 금액은 확정 전.']);
}

await fs.mkdir(BUILD+'/renders',{recursive:true});
await (await PresentationFile.exportPptx(p)).save(BUILD+'/candidate.pptx');
console.log('Draft exported');
for(let i=0;i<p.slides.items.length;i++){
 const s=p.slides.items[i];
 const png=await p.export({slide:s,format:'png',scale:1});
 await fs.writeFile(BUILD+'/renders/'+String(i+1).padStart(2,'0')+'.png',new Uint8Array(await png.arrayBuffer()));
 const layout=await s.export({format:'layout'});await fs.writeFile(BUILD+'/renders/'+String(i+1).padStart(2,'0')+'.json',await layout.text());
 console.log('Rendered',i+1);
}
const {finalizePresentation}=await import(pathToFileURL(SKILL+'/container_tools/artifact_tool_utils.mjs').href);
const result=await finalizePresentation({workspaceDir:ROOT,candidatePath:BUILD+'/candidate.pptx',finalPath:OUT,pythonExecutable:PY,integrityValidatorPath:SKILL+'/container_tools/inspect_presentation_package_integrity.py',layoutValidatorPath:SKILL+'/container_tools/inspect_presentation_layout_geometry.py',layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit','--require-native-table-slide','8'],explicitTotalSlideCount:12,requiredNativeTableOwnerSlides:[8],fontPolicy:{basis:'design',families:[FONT]},verifyArtifactToolImport:true,receiptPath:BUILD+'/validation.json'});
console.log(JSON.stringify(result));
