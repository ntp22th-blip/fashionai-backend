from flask import Flask, request, jsonify, send_from_directory, redirect, url_for, session
from flask_cors import CORS
from flask_dance.contrib.google import make_google_blueprint, google
import google.generativeai as genai
import os, io, base64, json
from PIL import Image
from colorthief import ColorThief

# ==============================
# 🔧 CẤU HÌNH CHUNG
# ==============================
app = Flask(__name__, static_folder="../frontend", template_folder="../frontend")
CORS(app)

# Cho phép Flask-Dance hoạt động trên môi trường Render (HTTPS)
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

# Secret key cho session Flask
app.secret_key = os.getenv("FLASK_SECRET_KEY", "fashionai_secret")

# Cấu hình API key Gemini
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_KEY:
    print("⚠️  LỖI: Không tìm thấy GEMINI_API_KEY trong Render Environment!")
else:
    genai.configure(api_key=GEMINI_KEY)
    print("✅ Đã tải GEMINI_API_KEY thành công!")

# ==============================
# 🔑 CẤU HÌNH GOOGLE LOGIN (OAuth2)
# ==============================
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
    google_bp = make_google_blueprint(
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scope=["profile", "email"],
        redirect_to="google_login_success"
    )
    app.register_blueprint(google_bp, url_prefix="/login")
    print("✅ Đã kích hoạt Google OAuth2 login")
else:
    print("⚠️  Chưa có GOOGLE_CLIENT_ID hoặc GOOGLE_CLIENT_SECRET trong Render Environment")

# ==============================
# 🎨 HÀM PHỤ
# ==============================
def rgb_to_hex(rgb):
    return '#%02x%02x%02x' % rgb

def detect_tone(r, g, b):
    if r > g and r > b:
        return "Spring Warm 🌸"
    elif b > r and b > g:
        return "Winter Cool ❄️"
    elif g > r and g > b:
        return "Summer Light ☀️"
    else:
        return "Autumn Deep 🍂"

# ==============================
# 🌐 GIAO DIỆN FRONTEND
# ==============================
@app.route('/')
def index():
    return send_from_directory('../frontend', 'index.html')

@app.route('/<path:filename>')
def serve_static(filename):
    return send_from_directory('../frontend', filename)

# ==============================
# 🔐 GOOGLE LOGIN ROUTES
# ==============================
@app.route("/login/google")
def login_google():
    return redirect(url_for("google.login", _external=True))

@app.route("/login/success")
def google_login_success():
    if not google.authorized:
        return redirect(url_for("google.login"))
    resp = google.get("/oauth2/v2/userinfo")
    user_info = resp.json()
    session["user"] = {
        "name": user_info.get("name"),
        "email": user_info.get("email"),
        "picture": user_info.get("picture")
    }
    print(f"✅ Đăng nhập thành công: {user_info.get('email')}")
    return redirect("/")

@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect("/")

@app.route("/user")
def get_user():
    return jsonify(session.get("user"))

# ==============================
# 🧠 API 1: PHÂN TÍCH ẢNH MÀU CÁ NHÂN
# ==============================
@app.route('/analyze_image', methods=['POST'])
def analyze_image():
    try:
        data = request.get_json()
        img_data = data['image'].split(",")[1]
        img = Image.open(io.BytesIO(base64.b64decode(img_data)))

        os.makedirs("data", exist_ok=True)
        temp_path = os.path.join("data", "temp_face.jpg")
        img.save(temp_path)

        color_thief = ColorThief(temp_path)
        palette = color_thief.get_palette(color_count=5)
        dominant = palette[0]
        hex_palette = [rgb_to_hex(c) for c in palette]
        tone = detect_tone(*dominant)

        # Lưu kết quả
        palette_path = os.path.join("data", "palette.json")
        with open(palette_path, "w", encoding="utf-8") as f:
            json.dump({
                "main_color": rgb_to_hex(dominant),
                "palette": hex_palette,
                "tone": tone
            }, f, ensure_ascii=False, indent=2)

        return jsonify({
            "main_color": rgb_to_hex(dominant),
            "colors": hex_palette,
            "tone": tone
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

# ==============================
# 💬 API 2: CHATBOT TƯ VẤN THỜI TRANG
# ==============================
@app.route('/chat', methods=['POST'])
def chat():
    try:
        data = request.get_json()
        user_message = data.get("message", "")

        palette_path = os.path.join("data", "palette.json")
        if not os.path.exists(palette_path):
            return jsonify({
                "reply": "⚠️ Mình chưa thấy hồ sơ của bạn (Test Color). Vui lòng vào trang Test Color trước để chatbot tư vấn cá nhân hoá nhé!"
            })

        with open(palette_path, "r", encoding="utf-8") as f:
            tone_data = json.load(f)

        tone = tone_data.get("tone", "Không rõ tone")

        # 🔥 Gọi Gemini API mới nhất
        model = genai.GenerativeModel("models/gemini-2.5-flash")
        prompt = f"""
        Bạn là chuyên gia thời trang. Dựa trên tone màu {tone},
        hãy trả lời tự nhiên, thân thiện, ngắn gọn cho câu hỏi của khách hàng: "{user_message}".
        Gợi ý thêm về phong cách, màu sắc, chất liệu và thương hiệu Việt Nam phù hợp.
        """

        response = model.generate_content(prompt)
        return jsonify({"reply": response.text.strip()})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"reply": f"❌ Lỗi server: {str(e)}"}), 500

# ==============================
# 🛍️ API 3: DỮ LIỆU BRANDS & OUTFITS
# ==============================
@app.route('/brands')
def brands():
    try:
        with open(os.path.join("data", "brands.json"), "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/outfits')
def outfits():
    try:
        with open(os.path.join("data", "outfits.json"), "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ==============================
# 🚀 CHẠY SERVER (Render)
# ==============================
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    print(f"🌸 Fashion AI backend đang chạy trên cổng {port}")
    app.run(host="0.0.0.0", port=port)

