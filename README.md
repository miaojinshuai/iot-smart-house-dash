# 物联网智能小屋 · 云端数据看板（代码版）

基于 Flask + 涂鸦云 OpenAPI 的网页看板：实时展示小屋温度、湿度、下雨、人体感应、灯光状态，提供历史曲线、越限报警、智能提醒与豆包 AI 管家对话。

## 一、本地运行

```bash
# 1. 安装依赖（需 Python 3.8+）
pip install -r requirements.txt

# 2. 启动看板
python tuya_dash.py

# 3. 浏览器打开
http://127.0.0.1:5000
```

登录账号：`admin`　密码：`123456`

> 说明：看板需要能访问外网（涂鸦云 OpenAPI）。豆包 AI 管家默认走本地规则引擎；如需接入豆包大模型，设置环境变量 `ARK_API_KEY`（火山方舟控制台获取）。

## 二、代码结构

```
云端看板/
├── tuya_dash.py          # 后端：Flask 服务 + 涂鸦云轮询 + 规则引擎 + AI 管家（已适配云平台：0.0.0.0 + $PORT）
├── templates/
│   └── index.html        # 前端：登录页 + 仪表盘（内联 CSS/JS，无外部依赖）
├── Procfile              # Render 启动配置（web: python tuya_dash.py）
├── requirements.txt      # Python 依赖
└── .gitignore
```

## 三、部署到 Render（免费，最省事，推荐）

Render 免费 Web Service 可直接运行本 Python 代码，无需重写。部署后公网可访问，适合比赛演示、评委远程查看。

### 3.1 推送代码到 GitHub

1. 注册/登录 GitHub，新建仓库（如 `iot-smart-house-dash`，可设 Private）；
2. 把 `云端看板` 文件夹里的全部文件（含 `Procfile`、`requirements.txt`、`.gitignore`）推上去：

```bash
git init
git add .
git commit -m "物联网智能小屋云端看板"
git branch -M main
git remote add origin https://github.com/<你的用户名>/iot-smart-house-dash.git
git push -u origin main
```

### 3.2 在 Render 创建 Web Service

1. 打开 https://dashboard.render.com ，用 GitHub 账号登录（免费，无需信用卡）；
2. 点击 **New + → Web Service** → 选择刚推送的仓库；
3. Render 会自动识别 `Procfile`（`python tuya_dash.py`），无需额外配置；
4. 如需接入豆包大模型，在 **Environment** 中添加环境变量 `ARK_API_KEY`；
5. 点击 **Create Web Service**，等 2~4 分钟构建完成。

### 3.3 访问与注意事项

- 部署完成后，访问形如 `https://iot-smart-house-dash.onrender.com` 的地址，登录 `admin / 123456`；
- **免费实例会休眠**：约 15 分钟无人访问后进入休眠，再次访问需等约 1 分钟冷启动——比赛演示前请先访问一次"唤醒"；
- 免费实例部署在美国节点，访问国内涂鸦云（openapi.tuyacn.com）一般可用，但延迟比国内平台高；若页面显示"设备离线"，说明海外→涂鸦云链路不稳定，可换腾讯云 SCF（国内节点）部署；
- 代码已监听 `0.0.0.0` 并读取 `$PORT` 环境变量，适配 Render 自动注入的端口。

## 四、部署到腾讯云 EdgeOne（可行性说明）

**结论：可行，但不是直接把本 Python 代码传上去**。EdgeOne 的 Edge Functions 运行时是 JavaScript（V8 隔离），不支持 Python。有两条可行路线：

### 路线 A：Edge Functions（纯边缘，推荐演示用）

用 JavaScript 重写后端逻辑，前端原样托管在 EdgeOne 静态资源：

| 原 Python 能力 | Edge Functions 对应实现 |
|---|---|
| 登录会话（Flask session） | Cookie 签名校验（crypto 生成 HMAC 签名 Cookie，无状态） |
| 涂鸦 OpenAPI 签名 | Web Crypto `crypto.subtle.sign("HMAC", ...)` 实现同样的 t 签名算法 |
| 10 秒轮询 + 历史/去抖状态 | 边缘函数无后台状态 → 改为**前端轮询**，历史与去抖状态存浏览器 localStorage |
| 豆包 AI 对话 | Edge Functions 直接 fetch 火山方舟接口（注意密钥需用环境变量/密钥管理，勿写死在代码） |

前端 `index.html` 的接口路径保持不变（`/api/current` 等），只需把 fetch 地址指向 EdgeOne 函数域名。

### 路线 B：静态托管 + 后端回源（最省事）

EdgeOne 只托管前端页面，后端仍跑在你自己的一台服务器（本 Python 代码原样部署），EdgeOne 通过 API 回源到服务器。适合已有服务器的场景。

### 部署步骤（路线 A 概要）

1. 在 EdgeOne 控制台创建站点，开启 Edge Functions；
2. 将 `index.html` 作为静态资源上传；
3. 新建一个 Edge Function（JS），实现上面表格中的登录 / 涂鸦数据 / AI 三个接口；
4. 配置路由：`/api/*` 指向该函数，其余走静态资源；
5. 涂鸦凭证与 ARK Key 放到 EdgeOne 的环境变量/密钥管理中。

> 需要我直接帮你把后端改写成 EdgeOne 的 JavaScript 版本吗？可以按需提供 `worker.js`（Edge Functions 入口）。
