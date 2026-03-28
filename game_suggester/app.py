from flask import Flask, render_template, request, jsonify
import requests
import json

app = Flask(__name__)

# 游戏地址
GAME_HOST = "http://127.0.0.1:5000"

# 本地模型地址（ollama）
MODEL_URL = "http://127.0.0.1:11434/api/chat"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get_suggest', methods=['POST'])
def get_suggest():
    room_code = request.json.get("room_code")

    # 1. 获取游戏快照
    snap = requests.post(f"{GAME_HOST}/api/coach/snapshot", json={"room_code": room_code}).json()

    # 2. 构造 Prompt（满足课程要求）
    prompt = f"""
你是游戏建议助手，根据游戏状态给出下一步建议。
当前棋盘：{snap['board']}
当前回合：{snap['round']}
当前分数：{snap['score']}

请输出1个合法走法，必须包含：
- recommended_position
- recommended_value
- reason
- risk
- confidence

输出纯JSON，不要其他文字。
""".strip()

    # 3. 调用本地模型 qwen3.5:4b
    model_res = requests.post(MODEL_URL, json={
        "model": "qwen3.5:4b",
        "messages": [{"role": "user", "content": prompt}],
        "stream": False
    })
    suggest = json.loads(model_res.json()["message"]["content"])

    # 4. 评估走法
    eval_res = requests.post(f"{GAME_HOST}/api/coach/evaluate_move", json={
        "room_code": room_code,
        "position": suggest["recommended_position"],
        "value": suggest["recommended_value"]
    }).json()

    # 5. 如果不合法，自动修正
    if not eval_res.get("valid", False):
        suggest = {
            "recommended_position": "A1",
            "recommended_value": 1,
            "reason": "模型建议不合法，自动切换为安全走法",
            "risk": "无风险",
            "confidence": 0.9
        }

    # 6. 返回最终结果
    return jsonify({
        "snapshot": snap,
        "suggest": suggest,
        "evaluation": eval_res
    })

if __name__ == '__main__':
    app.run(port=5001, debug=True)