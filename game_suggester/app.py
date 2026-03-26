from flask import Flask, render_template, request, jsonify
import requests

app = Flask(__name__)

# 游戏服务地址
GAME_URL = "http://127.0.0.1:5000"

# 首页：输入房间号
@app.route('/')
def index():
    return render_template('index.html')

# 接口：获取建议
@app.route('/get_suggest', methods=['POST'])
def get_suggest():
    room_code = request.json.get("room_code")

    if not room_code:
        return jsonify({"error": "请输入房间号"}), 400

    try:
        # 1. 获取游戏快照
        res = requests.post(GAME_URL + "/api/coach/snapshot", json={"room_code": room_code})
        snapshot = res.json()

        # 2. 生成建议
        suggest = {
            "recommended_position": "A1",
            "recommended_value": 5,
            "reason": "A1是空位，优先占角",
            "risk": "无风险",
            "confidence": 0.95
        }

        return jsonify({
            "snapshot": snapshot,
            "suggest": suggest
        })

    except Exception as e:
        return jsonify({"error": str(e)})

if __name__ == '__main__':
    app.run(port=5001, debug=True)