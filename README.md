# BizBot VN — Trợ lý kinh doanh AI cho SME Việt Nam

Trợ lý kinh doanh AI dành cho **chủ shop, tiểu thương, hộ kinh doanh và SME Việt Nam**, triển khai trên **GreenNode AgentBase**. Một endpoint cloud phục vụ **cả giao diện web (UI) lẫn API agent**.

> Framework: **LangGraph + Memory** (`greennode-agent-bridge`). LLM qua **GreenNode AI Platform** (OpenAI-compatible).

---

## ✨ Tính năng

**6 module trên giao diện web:**

| Module | Mô tả |
|--------|-------|
| 🤖 **Trợ lý AI (chat)** | Hỏi đáp kinh doanh, thuế, pháp lý bằng tiếng Việt; có bộ nhớ hội thoại + ghi nhớ thông tin shop. |
| 🧮 **Công cụ Tính toán** | Tính thuế hộ kinh doanh, giá bán, lợi nhuận, thuế nhập khẩu, dòng tiền. |
| 📖 **Sổ thu chi** | Ghi thu/chi theo tháng, khung tiến độ, xuất CSV (lưu tại trình duyệt người dùng). |
| 🏷️ **Thuế theo ngành (MCC)** | Tra mã ngành (~230 mã), tìm không dấu, gợi ý nhóm thuế. |
| 📋 **Tra cứu Thuế & Pháp lý** | VAT, TNCN/TNDN, hóa đơn điện tử, đăng ký kinh doanh, quy định TMĐT (Shopee/TikTok), mã HS. |
| 🆘 **Hỗ trợ Tình huống** | Hoàn tiền, bị sàn phạt/khóa shop, tranh chấp NCC, hàng bị hải quan giữ, vay vốn SME. |

**5 công cụ tính toán (tool) cho agent:** `tinh_thue_ho_kinh_doanh`, `tinh_gia_ban`, `tinh_loi_nhuan`, `tinh_thue_nhap_khau`, `tinh_dong_tien` — agent luôn gọi tool để ra **số chính xác** thay vì nhẩm.

**Bộ nhớ dài hạn:** `ghi_nho` / `nho_lai` — lưu & truy xuất thông tin shop (ngành hàng, doanh thu, kênh bán) để cá nhân hóa qua các phiên.

**Tra cứu Mã số thuế (MST):** route `GET /lookup-mst?mst=...` proxy server-side (nguồn Cục Thuế qua xinvoice/vietqr), trả tên/địa chỉ/loại hình.

---

## 🧩 Kiến trúc

`main.py` chạy `GreenNodeAgentBaseApp` (Starlette) với các route:

- `GET /health` → health check (port 8080)
- `POST /invocations` → agent hội thoại (LangGraph + memory; **cần** header `X-GreenNode-AgentBase-User-Id` & `-Session-Id`)
- `GET /` → trả `chat_ui.html` (UI web cùng origin, không cần proxy/CORS)
- `GET /lookup-mst?mst=...` → proxy tra cứu Mã số thuế

> Cập nhật quy định thuế 2026 đã được tích hợp trong system prompt: bỏ thuế khoán, bỏ lệ phí môn bài, ngưỡng miễn thuế **200 triệu/năm** (tỷ lệ % theo Thông tư 40/2021). Các con số là **ước tính tham khảo** — luôn kiểm tra với cơ quan thuế/kế toán.

---

## 📂 Cấu trúc dự án

| File | Vai trò |
|------|---------|
| `main.py` | Agent entrypoint: LangGraph graph + memory, system prompt, 5 tool tính toán, route `/`, `/lookup-mst`. |
| `chat_ui.html` | Toàn bộ giao diện web (HTML/CSS/JS thuần, 1 file): 6 module + data MCC. |
| `ui_server.py` | Proxy chạy LOCAL (port 3001) để dev UI riêng — **không deploy**. |
| `Dockerfile` | Image Python 3.13-slim, chạy `main.py` cổng 8080. |
| `requirements.txt` | greennode-agentbase, greennode-agent-bridge[langgraph], langgraph, langchain-openai, python-dotenv. |
| `.env.example` | Mẫu biến môi trường (LLM + Memory). |

---

## ⚙️ Biến môi trường

Tạo `.env` từ `.env.example`:

```
LLM_API_KEY=        # API key GreenNode AI Platform (tạo qua /agentbase-llm)
LLM_BASE_URL=https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1
LLM_MODEL=          # vd: google/gemma-4-31b-it hoặc qwen/qwen3-5-27b
MEMORY_ID=          # tạo memory store qua /agentbase-memory
MEMORY_STRATEGY_ID= # strategy ID của memory store (mặc định "default")
```

> IAM (`.greennode.json`) chỉ cần cho local dev. Trên AgentBase Runtime, `GREENNODE_CLIENT_ID/SECRET/AGENT_IDENTITY` được runtime **tự inject** — **không** để các biến này trong `.env`.

---

## 🖥️ Chạy local

```bash
python -m venv venv
# Windows PowerShell: venv\Scripts\Activate.ps1   |  macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
python main.py
```

Mở **http://localhost:8080/** → toàn bộ UI + AI chạy cùng origin.

Test API (memory cần đủ 2 header):
```bash
curl -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -H "X-GreenNode-AgentBase-User-Id: test-user" \
  -H "X-GreenNode-AgentBase-Session-Id: test-session-1" \
  -d '{"message": "Mình bán cà phê online, doanh thu năm 600 triệu, đóng thuế gì?"}'
```

---

## 🚀 Deploy lên GreenNode AgentBase

Dùng skill `/agentbase-deploy` (Custom Agent), hoặc thủ công:

```bash
TAG="v$(date +%Y%m%d%H%M%S)"
IMG="<registry>/<repo>/sme-all-in-one-tool:$TAG"
docker build --platform linux/amd64 -t "$IMG" .
bash .claude/skills/agentbase/scripts/cr.sh credentials docker-login
docker push "$IMG"
bash .claude/skills/agentbase/scripts/runtime.sh create \
  --name sme-all-in-one-tool --image "$IMG" \
  --flavor runtime-s2-general-2x4 --env-file .env --from-cr \
  --min-replicas 1 --max-replicas 1
```

Console: https://aiplatform.console.vngcloud.vn/agent-runtime?tab=runtime · Theo dõi log: `/agentbase-monitor`.

---

## ⚠️ Lưu ý

- Các con số thuế là **ước tính tham khảo**, thay đổi theo ngành nghề & quy định hiện hành.
- **Sổ thu chi** lưu ở `localStorage` máy người dùng cuối — không nằm trên server.
- `/lookup-mst` cần container có quyền gọi internet ra ngoài (xinvoice/vietqr).
