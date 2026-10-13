# -*- coding: utf-8 -*-
"""
物联网智能小屋 · 云端数据看板（代码版）
- 定时拉取涂鸦云设备数据（DP 透传）
- 温湿度越限报警 / 下雨提醒带伞 / 门口有人提醒
- 豆包 AI 管家（可接火山方舟，未配 Key 时本地模式）

运行: python tuya_dash.py   然后浏览器打开 http://127.0.0.1:5000
登录: admin / 123456
"""
import json
import os
import time
import threading
import itertools
from collections import deque

from flask import Flask, jsonify, render_template, request, session
from tuya_connector import TuyaOpenAPI

# ===== 涂鸦云配置（中国数据中心）=====
ACCESS_ID = "jxa5snjf5yvmtc75g4sw"
ACCESS_SECRET = "f4e28994628340c883b4f971f8aad903"
DEVICE_ID = "6cd4f0a3a7c67125edxtnx"   # 智慧养老小屋 / 物联网智能小屋
ENDPOINT = "https://openapi.tuyacn.com"
POLL_INTERVAL = 10   # 拉取间隔（秒）
HISTORY_MAX = 2000   # 保留历史条数
# =====================================

app = Flask(__name__)
app.secret_key = "qxc-iot-smart-house-demo-2026"
ADMIN_USER = "admin"
ADMIN_PASS = "123456"

# ===== 登录校验：除登录/登出外，所有 /api/ 接口需登录 =====
@app.before_request
def require_login():
    if request.path.startswith("/api/"):
        if request.path not in ("/api/login", "/api/logout"):
            if not session.get("user"):
                return jsonify({"ok": False, "msg": "未登录"}), 401


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(silent=True) or {}
    if data.get("username") == ADMIN_USER and data.get("password") == ADMIN_PASS:
        session["user"] = ADMIN_USER
        return jsonify({"ok": True})
    return jsonify({"ok": False, "msg": "账号或密码错误"}), 401


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"ok": True})


history = deque(maxlen=HISTORY_MAX)
alerts = deque(maxlen=60)
lock = threading.Lock()
_alert_id = itertools.count(1)

current = {"online": False, "temp": None, "hum": None,
           "switch_led": None, "switch_led_1": None,
           "switch_led_2": None, "switch_led_3": None,
           "rain": None, "human": None, "dps": {}}

# 报警阈值（可在网页修改）
config = {"temp_min": 16.0, "temp_max": 32.0,
          "hum_min": 30.0, "hum_max": 80.0}

# 去抖状态：事件持续期间只提醒一次
rule_state = {"temp_low": False, "temp_high": False,
              "hum_low": False, "hum_high": False,
              "rain": False, "human": False}

api = None


def push_alert(level, msg):
    a = {"id": next(_alert_id), "ts": int(time.time() * 1000),
         "level": level, "msg": msg}
    alerts.append(a)
    return a


def check_rules(row):
    """温湿度越限 + 下雨 + 人体 规则引擎（事件变化沿触发一次）"""
    rs = rule_state
    with lock:
        t = row.get("temp")
        h = row.get("hum")
        rain = row.get("rain")
        human = row.get("human")
        cfg = config

        if t is not None:
            if t < cfg["temp_min"] and not rs["temp_low"]:
                rs["temp_low"] = True
                push_alert("danger", "温度过低：当前 %.1f℃，低于下限 %.1f℃" % (t, cfg["temp_min"]))
            elif t > cfg["temp_max"] and not rs["temp_high"]:
                rs["temp_high"] = True
                push_alert("danger", "温度过高：当前 %.1f℃，超过上限 %.1f℃" % (t, cfg["temp_max"]))
            elif cfg["temp_min"] <= t <= cfg["temp_max"]:
                rs["temp_low"] = rs["temp_high"] = False

        if h is not None:
            if h < cfg["hum_min"] and not rs["hum_low"]:
                rs["hum_low"] = True
                push_alert("warning", "湿度过低：当前 %.0f%%，低于下限 %.0f%%" % (h, cfg["hum_min"]))
            elif h > cfg["hum_max"] and not rs["hum_high"]:
                rs["hum_high"] = True
                push_alert("warning", "湿度过高：当前 %.0f%%，超过上限 %.0f%%" % (h, cfg["hum_max"]))
            elif cfg["hum_min"] <= h <= cfg["hum_max"]:
                rs["hum_low"] = rs["hum_high"] = False

        if rain is True and not rs["rain"]:
            rs["rain"] = True
            push_alert("info", "🌧 下雨了！下班回家记得带伞")
        elif rain is False:
            rs["rain"] = False

        if human is True and not rs["human"]:
            rs["human"] = True
            push_alert("warning", "🚪 门口有人通过")
        elif human is False:
            rs["human"] = False


def parse_th(value):
    """解析 control_data 中的温湿度。支持 {"temp":27.5,"hum":60} 格式。"""
    if not value:
        return None, None
    try:
        if isinstance(value, str):
            obj = json.loads(value)
        else:
            obj = value
        return obj.get("temp"), obj.get("hum")
    except Exception:
        return None, None


def poll():
    global current, api
    while True:
        try:
            if api is None:
                api = TuyaOpenAPI(ENDPOINT, ACCESS_ID, ACCESS_SECRET)
                api.connect()
            resp = api.get(f"/v1.0/iot-03/devices/{DEVICE_ID}/status")
            result = resp.get("result") or []
            row = {"ts": int(time.time() * 1000)}
            temp = hum = rain = human = None
            dps = {}
            for item in result:
                code, value = item.get("code"), item.get("value")
                dps[code] = value
                if code == "control_data":
                    t2, h2 = parse_th(value)
                    if t2 is not None:
                        temp, hum = t2, h2
                    continue
                row[code] = value
                if code == "switch_led":
                    current["switch_led"] = value
                elif code == "switch_led_1":
                    current["switch_led_1"] = value
                elif code == "switch_led_2":
                    current["switch_led_2"] = value
                elif code == "switch_led_3":
                    current["switch_led_3"] = value
                elif code == "temp_current":
                    temp = value / 10.0
                elif code == "humidity_current":
                    hum = value
                elif code == "switch_2":
                    rain = bool(value)
                elif code == "infared_switch":
                    human = bool(value)
            if temp is not None:
                row["temp"], row["hum"] = temp, hum
            if rain is not None:
                row["rain"] = rain
            if human is not None:
                row["human"] = human
            with lock:
                current["temp"] = temp if temp is not None else current.get("temp")
                current["hum"] = hum if hum is not None else current.get("hum")
                current["rain"] = rain if rain is not None else current.get("rain")
                current["human"] = human if human is not None else current.get("human")
                current["online"] = True
                current["dps"] = dps
                history.append(row)
            check_rules(row)
        except Exception as e:
            with lock:
                current["online"] = False
        time.sleep(POLL_INTERVAL)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/current")
def api_current():
    with lock:
        return jsonify(dict(current))


@app.route("/api/history")
def api_history():
    with lock:
        return jsonify(list(history))


@app.route("/api/alerts")
def api_alerts():
    with lock:
        return jsonify(list(alerts))


@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    global config
    if request.method == "POST":
        data = request.get_json(force=True, silent=True) or {}
        with lock:
            for k in ("temp_min", "temp_max", "hum_min", "hum_max"):
                if k in data and isinstance(data[k], (int, float)):
                    config[k] = float(data[k])
            # 修改阈值后重置越限去抖状态，让新阈值立即生效
            rule_state.update(temp_low=False, temp_high=False,
                              hum_low=False, hum_high=False)
        return jsonify(dict(config))
    with lock:
        return jsonify(dict(config))


# ================= AI 智能管家（豆包 AI）=================
AI_NAME = "豆包 AI 管家"
# 火山方舟（豆包大模型）API Key：填入后 /api/ai/chat 使用真实豆包大模型对话；
# 留空则使用本地智能分析引擎（无需联网，演示可用）。
# 获取方式：火山引擎方舟控制台 https://console.volcengine.com/ark 创建推理接入点。
ARK_API_KEY = os.environ.get("ARK_API_KEY", "")
ARK_MODEL = "doubao-seed-1-6-250615"   # 豆包模型（可在方舟控制台查看你的模型名）


def ai_greet():
    h = time.localtime().tm_hour
    if h < 5:
        return "夜深了，小屋一切正常，安心休息吧。我是豆包 AI 管家，随时待命。"
    if h < 8:
        return "早上好！我是豆包 AI 管家，新的一天，小屋已为你准备好。"
    if h < 12:
        return "上午好！我是豆包 AI 管家，小屋的温湿度与安全状态尽在掌握。"
    if h < 14:
        return "中午好！我是豆包 AI 管家，记得按时吃饭、注意休息。"
    if h < 18:
        return "下午好！我是豆包 AI 管家，今天的家居数据已为你记录完毕。"
    if h < 23:
        return "晚上好！我是豆包 AI 管家，睡前记得看看小屋状态。"
    return "夜深了，我是豆包 AI 管家，晚安，好梦。"


def ai_tips():
    """基于最新数据的 AI 智能分析（本地规则引擎，模拟 AI 管家分析）"""
    tips = []
    c = current
    t, h = c.get("temp"), c.get("hum")
    if t is not None:
        if t > config["temp_max"]:
            tips.append("温度 %.1f℃ 偏高：建议开窗通风或开启降温设备" % t)
        elif t < config["temp_min"]:
            tips.append("温度 %.1f℃ 偏低：建议适当保暖，避免着凉" % t)
        else:
            tips.append("温度 %.1f℃ 舒适，无需干预" % t)
    if h is not None:
        if h > config["hum_max"]:
            tips.append("湿度 %.0f%% 偏高：建议通风除湿" % h)
        elif h < config["hum_min"]:
            tips.append("湿度 %.0f%% 偏低：建议使用加湿器" % h)
        else:
            tips.append("湿度 %.0f%% 适宜，体感舒适" % h)
    if c.get("rain"):
        tips.append("检测到下雨：出门记得带伞，晾衣架注意防雨")
    if c.get("human"):
        tips.append("门口检测到有人经过，已为你记录")
    if c.get("switch_led"):
        tips.append("客厅灯开启中：需要节能可在 App 或语音关闭")
    else:
        tips.append("灯光已关闭，节能又环保")
    if c.get("switch_led_1") or c.get("switch_led_2"):
        tips.append("有副灯开启，可按需关闭")
    return tips


def ai_speak():
    return "，" .join(ai_tips())


def dress_advice(t):
    """穿衣指数：按当前温度推荐穿着"""
    if t is None:
        return "温度数据待更新，先穿件长袖准没错"
    if t < 8:
        return "当前 %.1f℃，天寒建议羽绒服/厚棉服，围巾帽子安排上" % t
    if t < 13:
        return "当前 %.1f℃，建议厚外套+毛衣，早晚记得保暖" % t
    if t < 18:
        return "当前 %.1f℃，风衣或卫衣正合适，早晚可加件薄外套" % t
    if t < 23:
        return "当前 %.1f℃，长袖T恤或衬衫，体感最舒服" % t
    if t < 28:
        return "当前 %.1f℃，短袖或薄长袖，清爽宜人" % t
    return "当前 %.1f℃，建议短袖短裤，注意防暑补水" % t


def life_tips():
    """生活小贴士：穿衣 / 护肤 / 出行 / 睡眠"""
    tips = []
    c = current
    t = c.get("temp")
    h = c.get("hum")
    if t is not None:
        tips.append(dress_advice(t))
    if h is not None:
        if h > config["hum_max"]:
            tips.append("空气偏潮湿（%.0f%%），外出注意防滑，衣柜可放除湿袋" % h)
        elif h < config["hum_min"]:
            tips.append("空气偏干（%.0f%%），记得护肤保湿，多喝水" % h)
        else:
            tips.append("湿度 %.0f%% 刚刚好，皮肤状态很舒服" % h)
    if c.get("rain"):
        tips.append("正在下雨，出门带伞，路面湿滑注意安全")
    hour = time.localtime().tm_hour
    if hour >= 22 or hour < 6:
        tips.append("夜深了，建议调暗灯光早点休息，明天精神更好")
    elif hour >= 12 and hour <= 14:
        tips.append("午休时间，小憩 20 分钟下午效率更高")
    return tips


@app.route("/api/ai")
def api_ai():
    with lock:
        return jsonify({
            "name": AI_NAME,
            "greet": ai_greet(),
            "tips": ai_tips(),
            "life": life_tips(),
            "dressing": dress_advice(current.get("temp")),
            "speak": ai_speak(),
            "ark": bool(ARK_API_KEY),
        })


def ark_chat(messages):
    """调用豆包大模型（火山方舟，OpenAI 兼容接口）"""
    import urllib.request
    body = json.dumps({"model": ARK_MODEL, "messages": messages}).encode("utf-8")
    req = urllib.request.Request(
        "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
        data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + ARK_API_KEY})
    with urllib.request.urlopen(req, timeout=30) as r:
        resp = json.loads(r.read().decode("utf-8"))
    return resp["choices"][0]["message"]["content"]


def local_chat(user_msg):
    """本地 AI 管家回复（未接入豆包 API 时）"""
    c = current
    t = c.get("temp"); h = c.get("hum")
    base = ("我是豆包 AI 管家（本地模式）。小屋当前温度 %s，湿度 %s%s；"
            "当前状态：%s。"
            "接入豆包大模型 API Key 后，我可以更聪明地陪你聊天哦。")
    t_s = ("%.1f℃" % t) if t is not None else "未知"
    h_s = ("%.0f%%" % h) if h is not None else "未知"
    status = "下雨中" if c.get("rain") else ("有人经过" if c.get("human") else "一切正常")
    return base % (t_s, h_s, "" if h is None else "RH", status)


@app.route("/api/ai/chat", methods=["POST"])
def api_ai_chat():
    data = request.get_json(force=True, silent=True) or {}
    msg = (data.get("msg") or "").strip()[:200]
    if not msg:
        return jsonify({"reply": "我是豆包 AI 管家，有什么可以帮你？"})
    try:
        if ARK_API_KEY:
            reply = ark_chat([
                {"role": "system",
                 "content": "你是" + AI_NAME + "，负责物联网智能小屋的数据解说与智能家居助手，"
                            "回答简洁、友好、口语化。"},
                {"role": "user", "content": msg},
            ])
        else:
            reply = local_chat(msg)
    except Exception as e:
        reply = "豆包大模型暂时连不上（%s），先用本地模式回复：%s" % (type(e).__name__, local_chat(msg))
    return jsonify({"reply": reply})


if __name__ == "__main__":
    t = threading.Thread(target=poll, daemon=True)
    t.start()
    port = int(os.environ.get("PORT", "5000"))
    print("=" * 52)
    print("  物联网智能小屋 · 云端数据看板 已启动")
    print("  访问地址： http://127.0.0.1:%d  （Render 部署时自动使用 $PORT）" % port)
    print("  登录账号： admin     密码： 123456")
    print("=" * 52)
    # Render 等云平台要求监听 0.0.0.0；本地运行同样可用
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
