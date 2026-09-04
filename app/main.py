"""
목업 화면 ↔ API 매핑
  화면 1 (셀러 등록)        -> POST /api/sellers/register
  화면 2 (구매 요청 등록)    -> POST /api/buyers/request   (등록 즉시 협상까지 동기 실행)
  화면 3 (협상 결과·승인)    -> GET  /api/deals/{txid}
                              POST /api/deals/{txid}/approve
                              POST /api/deals/{txid}/reject
"""

from __future__ import annotations
from dotenv import load_dotenv

load_dotenv()  # .env 파일을 읽어서 OPENAI_API_KEY, NEGOTIATOR_MODE 등을 환경변수로 등록
# (OS/셸 종류(Windows PowerShell, macOS/Linux bash 등)와 무관하게 항상 같은 방식으로 동작)

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .schemas import SellerRegister, BuyerRequest
from .store import store
from .negotiate import run_negotiation
from .report import write_report, summarizer
from .rfq_parse import parse_buyer_text
from .seed_catalog import seed as seed_catalog
from .integrations.odoo.router import router as odoo_router
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Deal Ledger MMVP")
app.include_router(odoo_router)

# 데모 목적: 로컬에서 파일로 연 목업 HTML(origin: null)도 호출 가능하도록 전체 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 목업 화면(static/index.html)을 백엔드가 직접 서빙 — API와 같은 도메인/포트에서
# 나가기 때문에 상대경로("/api")가 로컬이든 AWS든 어디서나 그대로 동작한다.
app.mount("/static-assets", StaticFiles(directory="static"), name="static-assets")


@app.get("/")
def serve_mockup():
    from fastapi.responses import FileResponse
    return FileResponse("static/index.html")


@app.post("/api/sellers/register")
def register_seller(offer: SellerRegister):
    store.register_seller(offer)
    return {"ok": True, "registered": offer}


@app.get("/api/sellers")
def list_sellers():
    return store.list_sellers()


@app.post("/api/buyers/request")
def buyer_request(request: BuyerRequest):
    """규칙 기반이라 즉시(동기) 협상까지 끝내고 결과를 바로 반환한다."""
    summary = run_negotiation(store, request)
    return summary


@app.post("/api/buyers/parse")
def buyer_parse(body: dict):
    """자연어 P.list → 구조화 RFQ 필드. 화면에서 확인·수정 후 request로 보낸다 (§2-2)."""
    return parse_buyer_text(body.get("text", ""))


@app.post("/api/buyers/request_text")
def buyer_request_text(body: dict):
    """자연어 요청을 파싱해서 바로 협상까지 실행. 파싱 결과와 협상 결과를 함께 반환."""
    parsed = parse_buyer_text(body.get("text", ""))
    if parsed.get("_missing"):
        raise HTTPException(422, f"필수 항목을 해석하지 못했습니다: {', '.join(parsed['_missing'])}")
    req = BuyerRequest(**{k: v for k, v in parsed.items() if not k.startswith("_")})
    summary = run_negotiation(store, req)
    return {"rfq": parsed, "result": summary}


@app.post("/api/dev/seed")
def dev_seed(per_model: int = 3):
    """CSV 정가 기반으로 셀러 카탈로그를 재시드 (데모 준비용)."""
    n = seed_catalog(reset=True, per_model=per_model)
    return {"ok": True, "seeded": n, "sellers": store.list_sellers()}


@app.get("/api/deals/{txid}")
def get_deal(txid: str):
    deal = store.get_deal(txid)
    if not deal:
        raise HTTPException(404, "존재하지 않는 거래ID입니다")
    log = store.get_log(txid)
    return {
        "deal": deal,
        "summary": summarizer.summarize(log),
        "log": [e.model_dump(by_alias=True) for e in log],
    }


@app.post("/api/deals/{txid}/approve")
def approve_deal(txid: str):
    deal = store.get_deal(txid)
    if not deal:
        raise HTTPException(404, "존재하지 않는 거래ID입니다")
    store.set_approval(txid, "APPROVED")
    log = store.get_log(txid)
    path = write_report(txid, log)
    return {"ok": True, "status": "APPROVED", "report_path": str(path)}


@app.post("/api/deals/{txid}/reject")
def reject_deal(txid: str):
    deal = store.get_deal(txid)
    if not deal:
        raise HTTPException(404, "존재하지 않는 거래ID입니다")
    store.set_approval(txid, "REJECTED")
    log = store.get_log(txid)
    path = write_report(txid, log)
    return {"ok": True, "status": "REJECTED", "report_path": str(path)}