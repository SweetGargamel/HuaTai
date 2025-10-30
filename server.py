from flask import Flask, send_from_directory, jsonify, request
import subprocess
import os

app = Flask(__name__, static_folder='frontend/dist', static_url_path='')

# 路由：主页（前端）
@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')

# 路由：API - 调用 main.py 进行指标抽取
@app.route('/api/extract', methods=['POST'])
def extract():
    pdf_path = request.json.get("pdf_path")
    output_dir = "./output"
    if not pdf_path or not os.path.exists(pdf_path):
        return jsonify({"error": "PDF not found"}), 400
    subprocess.run(["python", "main.py", "--pdf", pdf_path, "--output_dir", output_dir])
    return jsonify({"status": "ok", "result": os.path.join(output_dir, "final.json")})

# 路由：返回最新抽取结果
@app.route('/api/result')
def get_result():
    try:
        with open("./output/final.json", "r", encoding="utf-8") as f:
            data = f.read()
        return data
    except Exception:
        return jsonify({"error": "No result yet"}), 404

# 静态文件（前端打包后）
@app.route('/<path:path>')
def static_proxy(path):
    return send_from_directory(app.static_folder, path)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=False)
