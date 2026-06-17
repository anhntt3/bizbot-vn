import os
import json as _json
import pathlib
import ssl
import urllib.request
from datetime import datetime
from typing import Annotated, Optional, TypedDict

from starlette.responses import HTMLResponse, JSONResponse

try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL_CTX = ssl.create_default_context()

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

from greennode_agentbase import (
    GreenNodeAgentBaseApp,
    RequestContext,
    PingStatus,
)
from greennode_agentbase.memory import MemoryClient
from greennode_agentbase.memory.models import (
    MemoryRecordSearchRequest,
    MemoryRecordInsertDirectlyRequest,
)
from greennode_agent_bridge import AgentBaseMemoryEvents
from langgraph.config import get_config

load_dotenv()

app = GreenNodeAgentBaseApp()

# --- Memory Configuration ---
# Create a memory with: /agentbase-memory
MEMORY_ID = os.environ.get("MEMORY_ID", "")
if not MEMORY_ID:
    raise ValueError("MEMORY_ID environment variable is required for memory-enabled agents")

MEMORY_STRATEGY_ID = os.environ.get("MEMORY_STRATEGY_ID", "default")

# CheckpointSaver: persists LangGraph graph state (short-term conversation memory)
checkpointer = AgentBaseMemoryEvents(memory_id=MEMORY_ID)

# MemoryClient: long-term semantic facts (remember/recall tools)
memory_client = MemoryClient()

# --- LLM Configuration ---
LLM_MODEL = os.environ.get("LLM_MODEL", "")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
if not LLM_MODEL or not LLM_BASE_URL or not LLM_API_KEY:
    raise ValueError(
        "LLM_MODEL, LLM_BASE_URL, and LLM_API_KEY environment variables are required. "
        "Set them in your .env file or use /agentbase-llm to get a platform API key."
    )

llm = ChatOpenAI(
    model=LLM_MODEL,
    base_url=LLM_BASE_URL,
    api_key=LLM_API_KEY,
    temperature=0.3,
)


# ============================================================
# SYSTEM PROMPT — BizBot VN (Trợ lý SME)
# ============================================================
SYSTEM_PROMPT = """\
Bạn là **BizBot VN** — trợ lý kinh doanh AI dành cho chủ shop, tiểu thương, hộ kinh \
doanh và SME Việt Nam, kể cả người KHÔNG rành công nghệ.

## Phong cách trả lời
- Trả lời bằng tiếng Việt, ngắn gọn, dễ hiểu, thực chiến — TRÁNH trích dẫn văn bản luật dài dòng.
- Dùng emoji + gạch đầu dòng để dễ đọc. Khi có con số, trình bày rõ ràng từng khoản.
- Khi câu hỏi liên quan tính toán (thuế, giá bán, lợi nhuận, dòng tiền, thuế nhập khẩu), \
LUÔN gọi tool tính toán tương ứng để ra số chính xác — đừng nhẩm trong đầu.
- Cuối câu trả lời, gợi ý 1-2 hành động tiếp theo dạng [Gợi ý].
- Nếu thiếu thông tin để tính (vd: chưa biết doanh thu, ngành hàng), hỏi lại 1 câu ngắn gọn.

## CẬP NHẬT QUY ĐỊNH 2026 (BẮT BUỘC áp dụng khi tư vấn thuế hộ kinh doanh)
- Từ 1/1/2026: **BỎ thuế khoán** — hộ kinh doanh chuyển sang **kê khai** doanh thu thực tế (khai theo quý).
- Từ 1/1/2026: **BỎ lệ phí môn bài** cho hộ kinh doanh — KHÔNG còn khoản môn bài 300k–1tr/năm nữa, đừng nhắc tới.
- Ngưỡng MIỄN thuế GTGT & TNCN là **200 triệu/năm** (KHÔNG còn là 100 triệu). Đang có đề xuất nâng lên 500 triệu/năm (chưa hiệu lực) — có thể nhắc như thông tin tham khảo.
- Tỷ lệ % trên doanh thu theo Thông tư 40/2021 (không đổi): phân phối hàng hóa 1%/0.5%; ăn uống & SX gắn hàng hóa 3%/1.5%; dịch vụ không bao thầu NVL 5%/2%; khác 2%/1%.
- ĐỪNG giả định ngành hàng của người dùng. Nếu chưa rõ họ bán gì, hỏi lại hoặc gợi ý họ dùng công cụ "Thuế theo ngành (MCC)".

## Mẫu trả lời tham khảo
Người dùng: "Mình bán đồ ăn online, doanh thu tháng khoảng 30 triệu, đóng thuế gì?"
BizBot:
✅ Phân loại: Hộ kinh doanh F&B online
📊 Ngưỡng miễn thuế: 200tr/năm
💰 Ước tính ~360tr/năm → CÓ phải nộp (kê khai theo tỷ lệ %)

Các loại thuế (đã bỏ môn bài từ 2026):
• Thuế GTGT (3%): ...
• Thuế TNCN (1.5%): ...

👉 Tổng ước tính: ~.../tháng
[Tính chi tiết hơn] [Hỏi thêm về hóa đơn]

## 4 Module bạn phụ trách
1. 📋 **Tra cứu Thuế & Pháp lý**: VAT, thuế TNCN/TNDN, hóa đơn điện tử, đăng ký kinh doanh, \
quy định TMĐT (Shopee/TikTok), mã HS & thuế nhập khẩu.
2. 🧮 **Công cụ Tính toán**: dùng các tool có sẵn (tính thuế, giá bán/lợi nhuận, thuế nhập khẩu, dòng tiền).
3. 📖 **Sổ tay Vận hành & Bán hàng**: mở/vận hành cửa hàng, bán đa kênh, vận chuyển (GHN/GHTK/J&T...), \
thanh toán (QR/ZaloPay/VNPay), đối soát.
4. 🆘 **Hỗ trợ Tình huống**: khách đòi hoàn tiền, bị sàn phạt/khóa shop, tranh chấp NCC, hàng bị hải quan giữ, vay vốn SME.

## Bộ nhớ
- Dùng tool `ghi_nho` để lưu thông tin shop của người dùng (ngành hàng, quy mô doanh thu, kênh bán, \
sở thích) để cá nhân hóa các lần sau.
- Dùng tool `nho_lai` để truy xuất thông tin đã lưu trước khi tư vấn.

## QUAN TRỌNG — Tuyên bố pháp lý
Các con số thuế là **ƯỚC TÍNH tham khảo**, thuế suất thực tế thay đổi theo ngành nghề và quy định \
hiện hành. Luôn nhắc người dùng kiểm tra với cơ quan thuế / kế toán cho trường hợp cụ thể.
"""


# ============================================================
# MODULE 2 — CÔNG CỤ TÍNH TOÁN (Tools)
# Các tool chỉ lo phần SỐ HỌC. Thuế suất do LLM cung cấp dựa trên
# ngành hàng (để tránh hardcode số liệu pháp lý có thể sai).
# ============================================================


def _vnd(x: float) -> str:
    """Định dạng số tiền VND dễ đọc."""
    return f"{x:,.0f}đ".replace(",", ".")


# Ngưỡng miễn thuế GTGT/TNCN cho hộ kinh doanh (hiệu lực 1/1/2026).
# Đang có đề xuất nâng lên 500 triệu/năm (dự kiến giữa 2026) — chỉnh hằng số này khi luật có hiệu lực.
NGUONG_MIEN_THUE = 200_000_000


@tool
def tinh_thue_ho_kinh_doanh(
    doanh_thu_nam: float,
    ty_le_gtgt_phan_tram: float,
    ty_le_tncn_phan_tram: float,
) -> str:
    """Tính thuế cho HỘ KINH DOANH theo phương pháp KÊ KHAI tỷ lệ % trên doanh thu.

    Từ 1/1/2026: bỏ thuế khoán (hộ KD chuyển sang kê khai) và BỎ lệ phí môn bài.
    Ngưỡng miễn thuế GTGT & TNCN là 200 triệu/năm (đang đề xuất nâng lên 500 triệu).
    LLM truyền tỷ lệ % theo ngành (Thông tư 40/2021): phân phối hàng hóa 1%/0.5%;
    dịch vụ ăn uống / SX gắn hàng hóa 3%/1.5%; dịch vụ không bao thầu NVL 5%/2%; khác 2%/1%.

    Args:
        doanh_thu_nam: Tổng doanh thu cả năm (VND).
        ty_le_gtgt_phan_tram: Tỷ lệ thuế GTGT trên doanh thu (%), theo ngành.
        ty_le_tncn_phan_tram: Tỷ lệ thuế TNCN trên doanh thu (%), theo ngành.
    """
    if doanh_thu_nam <= NGUONG_MIEN_THUE:
        return (
            f"📊 Doanh thu {_vnd(doanh_thu_nam)}/năm ≤ 200 triệu → "
            f"được MIỄN thuế GTGT & TNCN. (Lệ phí môn bài cũng đã bỏ từ 1/1/2026.)"
        )
    gtgt = doanh_thu_nam * ty_le_gtgt_phan_tram / 100
    tncn = doanh_thu_nam * ty_le_tncn_phan_tram / 100
    tong_nam = gtgt + tncn
    return (
        f"📊 Doanh thu năm: {_vnd(doanh_thu_nam)} (kê khai theo tỷ lệ % — đã bỏ thuế khoán & môn bài từ 2026)\n"
        f"• Thuế GTGT ({ty_le_gtgt_phan_tram}%): {_vnd(gtgt)}/năm\n"
        f"• Thuế TNCN ({ty_le_tncn_phan_tram}%): {_vnd(tncn)}/năm\n"
        f"👉 Tổng ước tính: {_vnd(tong_nam)}/năm ≈ {_vnd(tong_nam / 12)}/tháng"
    )


@tool
def tinh_gia_ban(
    gia_von: float,
    chi_phi_khac: float = 0,
    margin_phan_tram: Optional[float] = None,
    markup_phan_tram: Optional[float] = None,
) -> str:
    """Tính GIÁ BÁN đề xuất từ giá vốn + chi phí, theo margin (% trên giá bán)
    hoặc markup (% trên giá vốn).

    Args:
        gia_von: Giá nhập/giá vốn của sản phẩm (VND).
        chi_phi_khac: Chi phí khác phân bổ cho mỗi sản phẩm (ship, đóng gói, phí sàn...) (VND).
        margin_phan_tram: Biên lợi nhuận mong muốn tính trên GIÁ BÁN (%). Vd 30 = lãi 30% giá bán.
        markup_phan_tram: Tỷ lệ cộng thêm tính trên GIÁ VỐN (%). Vd 50 = giá bán = vốn x 1.5.
    """
    von_tong = gia_von + chi_phi_khac
    if margin_phan_tram is not None:
        if margin_phan_tram >= 100:
            return "⚠️ Margin phải < 100%."
        gia_ban = von_tong / (1 - margin_phan_tram / 100)
        loi_nhuan = gia_ban - von_tong
        return (
            f"💰 Tổng vốn (vốn + chi phí): {_vnd(von_tong)}\n"
            f"• Margin mục tiêu: {margin_phan_tram}% trên giá bán\n"
            f"👉 Giá bán đề xuất: {_vnd(gia_ban)}\n"
            f"• Lợi nhuận/sản phẩm: {_vnd(loi_nhuan)}"
        )
    if markup_phan_tram is not None:
        gia_ban = von_tong * (1 + markup_phan_tram / 100)
        loi_nhuan = gia_ban - von_tong
        margin_thuc = loi_nhuan / gia_ban * 100 if gia_ban else 0
        return (
            f"💰 Tổng vốn (vốn + chi phí): {_vnd(von_tong)}\n"
            f"• Markup: {markup_phan_tram}% trên giá vốn\n"
            f"👉 Giá bán đề xuất: {_vnd(gia_ban)}\n"
            f"• Lợi nhuận/sản phẩm: {_vnd(loi_nhuan)} (margin thực ≈ {margin_thuc:.1f}%)"
        )
    return "⚠️ Cần cung cấp margin_phan_tram HOẶC markup_phan_tram để tính giá bán."


@tool
def tinh_loi_nhuan(gia_ban: float, gia_von: float, chi_phi_khac: float = 0) -> str:
    """Tính LỢI NHUẬN và biên lợi nhuận (margin) khi đã biết giá bán.

    Args:
        gia_ban: Giá bán thực tế (VND).
        gia_von: Giá vốn (VND).
        chi_phi_khac: Chi phí khác/sản phẩm (ship, phí sàn, đóng gói...) (VND).
    """
    von_tong = gia_von + chi_phi_khac
    loi_nhuan = gia_ban - von_tong
    margin = loi_nhuan / gia_ban * 100 if gia_ban else 0
    canh_bao = "" if loi_nhuan > 0 else "\n⚠️ Đang LỖ ở mức giá này!"
    return (
        f"💰 Giá bán: {_vnd(gia_ban)} | Tổng vốn: {_vnd(von_tong)}\n"
        f"👉 Lợi nhuận/sản phẩm: {_vnd(loi_nhuan)} (margin ≈ {margin:.1f}%){canh_bao}"
    )


@tool
def tinh_thue_nhap_khau(
    gia_tri_hang: float,
    thue_suat_nhap_khau_phan_tram: float,
    thue_suat_gtgt_phan_tram: float = 10,
) -> str:
    """Tính THUẾ NHẬP KHẨU + VAT cho hàng nhập.

    LLM cần truyền thuế suất nhập khẩu theo mã HS của mặt hàng.

    Args:
        gia_tri_hang: Trị giá tính thuế của lô hàng (CIF, VND).
        thue_suat_nhap_khau_phan_tram: Thuế suất nhập khẩu theo mã HS (%).
        thue_suat_gtgt_phan_tram: Thuế suất GTGT hàng nhập (%), mặc định 10%.
    """
    thue_nk = gia_tri_hang * thue_suat_nhap_khau_phan_tram / 100
    can_cu_gtgt = gia_tri_hang + thue_nk
    thue_gtgt = can_cu_gtgt * thue_suat_gtgt_phan_tram / 100
    tong_thue = thue_nk + thue_gtgt
    return (
        f"📦 Trị giá hàng (CIF): {_vnd(gia_tri_hang)}\n"
        f"• Thuế nhập khẩu ({thue_suat_nhap_khau_phan_tram}%): {_vnd(thue_nk)}\n"
        f"• Thuế GTGT ({thue_suat_gtgt_phan_tram}% trên {_vnd(can_cu_gtgt)}): {_vnd(thue_gtgt)}\n"
        f"👉 Tổng thuế phải nộp: {_vnd(tong_thue)}\n"
        f"• Tổng chi phí hàng về kho: {_vnd(gia_tri_hang + tong_thue)}"
    )


@tool
def tinh_dong_tien(tong_thu: float, tong_chi: float, ky: str = "tháng") -> str:
    """Tính DÒNG TIỀN ròng (cash flow) và cảnh báo khi âm.

    Args:
        tong_thu: Tổng tiền thu vào trong kỳ (VND).
        tong_chi: Tổng tiền chi ra trong kỳ (VND).
        ky: Đơn vị kỳ, vd "tuần" hoặc "tháng".
    """
    rong = tong_thu - tong_chi
    if rong < 0:
        canh_bao = (
            f"\n🚨 CẢNH BÁO: Dòng tiền ÂM {_vnd(abs(rong))} trong {ky} này. "
            f"Cần cắt giảm chi phí hoặc tăng thu / giãn công nợ ngay."
        )
    else:
        canh_bao = f"\n✅ Dòng tiền dương, dư {_vnd(rong)} trong {ky} này."
    return (
        f"💵 Thu: {_vnd(tong_thu)} | Chi: {_vnd(tong_chi)} ({ky})\n"
        f"👉 Dòng tiền ròng: {_vnd(rong)}{canh_bao}"
    )


# ============================================================
# Bộ nhớ dài hạn (long-term memory) — remember / recall
# ============================================================


def _get_actor_id() -> str:
    config = get_config()
    return config["configurable"].get("actor_id", "default")


def _build_namespace(actor_id: str) -> str:
    return f"/strategies/{MEMORY_STRATEGY_ID}/actors/{actor_id}"


@tool
def ghi_nho(thong_tin: str) -> str:
    """Lưu một thông tin quan trọng về người dùng/shop vào bộ nhớ dài hạn
    (vd: ngành hàng, quy mô doanh thu, kênh bán, sở thích) để cá nhân hóa lần sau.

    Args:
        thong_tin: Nội dung cần ghi nhớ.
    """
    namespace = _build_namespace(_get_actor_id())
    memory_client.insert_memory_records_directly(
        id=MEMORY_ID,
        namespace=namespace,
        request=MemoryRecordInsertDirectlyRequest(memory_records=[thong_tin]),
    )
    return f"Đã ghi nhớ: {thong_tin}"


@tool
def nho_lai(cau_hoi: str) -> str:
    """Tìm trong bộ nhớ dài hạn các thông tin liên quan đến người dùng/shop.

    Args:
        cau_hoi: Câu truy vấn bằng ngôn ngữ tự nhiên.
    """
    namespace = _build_namespace(_get_actor_id())
    results = memory_client.search_memory_records(
        id=MEMORY_ID,
        namespace=namespace,
        request=MemoryRecordSearchRequest(query=cau_hoi, limit=10),
    )
    if not results:
        return "Chưa có thông tin nào được ghi nhớ."

    def _field(r, key):
        # search_memory_records returns a list of dicts in this SDK version,
        # but tolerate object-style results too.
        return r.get(key) if isinstance(r, dict) else getattr(r, key, None)

    lines = []
    for r in results:
        mem = _field(r, "memory")
        score = _field(r, "score")
        score_txt = f" (độ liên quan: {score:.2f})" if isinstance(score, (int, float)) else ""
        lines.append(f"- {mem}{score_txt}")
    return "\n".join(lines)


# ============================================================
# Build graph
# ============================================================
TOOLS = [
    tinh_thue_ho_kinh_doanh,
    tinh_gia_ban,
    tinh_loi_nhuan,
    tinh_thue_nhap_khau,
    tinh_dong_tien,
    ghi_nho,
    nho_lai,
]

llm_with_tools = llm.bind_tools(TOOLS)


class State(TypedDict):
    messages: Annotated[list, add_messages]


def chatbot(state: State) -> dict:
    """Node chatbot: chèn system prompt rồi gọi LLM (có tool)."""
    messages = state["messages"]
    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=SYSTEM_PROMPT)] + list(messages)
    return {"messages": [llm_with_tools.invoke(messages)]}


graph_builder = StateGraph(State)
graph_builder.add_node("chatbot", chatbot)
graph_builder.add_node("tools", ToolNode(TOOLS))
graph_builder.add_edge(START, "chatbot")
graph_builder.add_conditional_edges("chatbot", tools_condition)
graph_builder.add_edge("tools", "chatbot")

graph = graph_builder.compile(checkpointer=checkpointer)


@app.entrypoint
def handler(payload: dict, context: RequestContext) -> dict:
    """Entrypoint chính — BizBot VN (LangGraph + Memory)."""
    if not context.user_id or not context.session_id:
        return {
            "status": "error",
            "error": "Missing required headers: X-GreenNode-AgentBase-User-Id and X-GreenNode-AgentBase-Session-Id are required when using memory.",
        }

    message = payload.get("message", "Xin chào")

    config = {
        "configurable": {
            "thread_id": context.session_id,
            "actor_id": context.user_id,
        }
    }

    result = graph.invoke({"messages": [("user", message)]}, config)
    ai_message = result["messages"][-1]

    return {
        "status": "success",
        "response": ai_message.content,
        "timestamp": datetime.now().isoformat(),
    }


@app.ping
def health_check() -> PingStatus:
    """Custom health check for GET /health endpoint."""
    return PingStatus.HEALTHY


# --- Serve the chat UI at GET / so the public endpoint opens a usable web page ---
# chat_ui.html calls /invocations on the same origin, so no proxy/CORS is needed.
_UI_FILE = pathlib.Path(__file__).parent / "chat_ui.html"


async def serve_ui(request):
    try:
        return HTMLResponse(_UI_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return HTMLResponse(
            "<h1>BizBot VN</h1><p>Chat UI is not bundled. Use POST /invocations.</p>",
            status_code=404,
        )


app.add_route("/", serve_ui, methods=["GET"])


# --- Tra cứu Mã số thuế (proxy server-side để tránh CORS) ---
# Nguồn: tổng hợp từ Cục Thuế (gdt.gov.vn). Chỉ trả tên/địa chỉ/loại hình/tình trạng.
def _fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "BizBotVN/1.0"})
    with urllib.request.urlopen(req, timeout=12, context=_SSL_CTX) as r:
        return _json.loads(r.read().decode("utf-8"))


async def lookup_mst(request):
    mst = "".join(ch for ch in (request.query_params.get("mst") or "") if ch.isdigit())
    if len(mst) < 10:
        return JSONResponse({"found": False, "error": "MST phải gồm 10–13 chữ số."})
    # Ưu tiên xinvoice (có orgType để nhận biết hộ kinh doanh), fallback VietQR.
    try:
        d = _fetch_json(f"https://api.xinvoice.vn/gdt-api/tax-payer/{mst}")
        if d.get("name"):
            return JSONResponse({
                "found": True, "name": d.get("name"), "address": d.get("address"),
                "orgType": d.get("orgType"), "status": d.get("status"), "source": "gdt.gov.vn",
            })
    except Exception:
        pass
    try:
        d = _fetch_json(f"https://api.vietqr.io/v2/business/{mst}")
        if d.get("code") == "00" and d.get("data"):
            x = d["data"]
            return JSONResponse({
                "found": True, "name": x.get("name"), "address": x.get("address"),
                "orgType": None, "status": x.get("status"), "source": "gdt.gov.vn",
            })
    except Exception:
        pass
    return JSONResponse({"found": False, "error": "Không tìm thấy MST (hoặc chưa đăng ký)."})


app.add_route("/lookup-mst", lookup_mst, methods=["GET"])


if __name__ == "__main__":
    app.run(port=8080, host="0.0.0.0")
