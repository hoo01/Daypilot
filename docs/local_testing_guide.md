# 本地测试与延迟对比：分步指南

适用分支：`refactor/schedule-orchestrator`。所有命令都在仓库根目录（`Daypilot/`）执行，除非另有说明。

---

## 0. 先确认两件事

| 检查 | 命令 | 期望 |
|---|---|---|
| Docker 在跑 | `docker info --format '{{.ServerVersion}}'` | 打印版本号。没起来就打开 Docker Desktop，弹出管理员密码框时输入 |
| 8000 端口 | `lsof -nP -iTCP:8000 -sTCP:LISTEN` | 如果被别的服务占了（比如 Cold email automation），后端换个端口，见第 3 步 |

---

## 1. 自动化测试（不访问网络，约 10 秒）

```bash
python -m pytest            # 需要 Docker：testcontainers 会自动起 mongo:7
```

期望 `195 passed`。只看重构相关的回归场景：

```bash
python -m pytest -k "R1 or R2 or R3 or R4 or R5 or R6 or R7 or R8 or R9 or R10" -rA
```

---

## 2. 准备数据库

**推荐：本地 Mongo**。不会碰团队共用的 Atlas，前后两版条件一致。

```bash
docker run -d --name daypilot-bench-mongo -p 27018:27017 mongo:7
MONGODB_URI=mongodb://localhost:27018 MONGODB_DB_NAME=daypilot_bench_after  python scripts/seed_demo.py
MONGODB_URI=mongodb://localhost:27018 MONGODB_DB_NAME=daypilot_bench_before python scripts/seed_demo.py   # 只有做对比时需要
```

本地库没有 Atlas Vector Search（"记忆检索"会失败），也没有 Google Calendar 缓存，其他功能都正常。
要用真实数据就不设 `MONGODB_URI`，直接用 `.env` 里的 Atlas。注意 `seed_demo.py` 会**删掉并重写** `demo_user`。

---

## 3. 启动后端

**一定要用 `python main.py` 启动**，不要用 `uvicorn api.app:app`。`main.py` 会先 `load_dotenv()`、打好代理补丁，
再初始化 telemetry；绕过它的话，`.env` 里的配置（包括 Dynatrace）不会生效。

```bash
env MONGODB_URI=mongodb://localhost:27018 MONGODB_DB_NAME=daypilot_bench_after \
    PORT=8002 \
    python main.py
```

看到 `Uvicorn running on http://0.0.0.0:8002` 后检查：

```bash
curl --noproxy '*' http://127.0.0.1:8002/health                               # {"status":"ok"}
curl --noproxy '*' "http://127.0.0.1:8002/schedule/day?user_id=demo_user"      # "status":"EMPTY"
```

---

## 4. 启动前端

**方式 A（最简单）：让后端直接托管构建好的前端**

```bash
cd frontend && npm run build && cd ..
```

然后用浏览器打开 `http://127.0.0.1:8002/today?user_id=demo_user`。URL 里的 `user_id` 会写进 localStorage。

**方式 B：vite 开发服务器（支持热更新）**

`frontend/vite.config.js` 把 `/api` 代理到 `127.0.0.1:8000`。所以要么让后端跑在 8000（端口空闲时），
要么临时把 `target` 改成 `http://127.0.0.1:8002`（别提交这个改动）：

```bash
cd frontend && npm run dev       # → http://localhost:5173/today?user_id=demo_user
```

---

## 5. 手动验收（对应设计文档 9.3 最后一项）

在 **Chat** 页依次输入，对照"期望"：

| # | 输入 / 操作 | 期望 |
|---|---|---|
| 1 | `What should I focus on today?` | 3–4 句建议，**不出现**方案卡片 |
| 2 | `Plan my day` | 出现 3 张方案卡（Most Productive / Most Relaxed / Fastest），回复点名推荐的那一张 |
| 3 | 刷新页面 | 方案卡还在（数据来自 `GET /schedule/day`，而不是页面状态） |
| 4 | 点 Most Relaxed 的 **Choose Plan** | 提示 "Schedule updated for today"，Today 页显示这套任务 |
| 5 | `Add a team meeting at 4pm today` | 出现一张 "Adjusted" 卡，16:00 有 team meeting；Today 页**还没变** |
| 6 | 输入 `yes` | 走同一个 confirm 接口；Today 页更新为调整后的日程 |
| 7 | `confirm`（此时没有待确认方案） | 回复 "There's no proposed schedule to confirm yet…"，状态不变 |
| 8 | Today 页勾掉一个任务并提交反馈 → 回到 Chat 说 `sure, move them to tomorrow` | 出现明天的方案，包含没完成的任务；确认后 `pending_reschedule` 被清除 |
| 9 | 打开右下角 AgentDrawer 说 `plan my day` | 自动跳转到 Chat 页并显示方案 |
| 10 | 顶部 **Plan Tomorrow** 模式说 `plan tomorrow` | 生成并能确认明天的方案 |

再对照 `docs/demo.md` 和 `docs/demo_script_v2.md` 的话术。日程类回复现在是代码模板生成的，不再有 LLM 自由发挥的那段话。

---

## 6. 延迟对比（重构前 vs 重构后）

### 6.1 准备重构前的代码（不影响当前工作区）

```bash
mkdir -p /tmp/daypilot-before
git archive 3e2853a | tar -x -C /tmp/daypilot-before      # 3e2853a = 重构前最后一个 commit
ln -s "$PWD/.env" /tmp/daypilot-before/.env
```

### 6.2 两个后端同时跑，环境变量完全一样（控制变量）

```bash
# 终端 1：重构前
cd /tmp/daypilot-before && env DT_API_TOKEN= MONGODB_URI=mongodb://localhost:27018 MONGODB_DB_NAME=daypilot_bench_before PORT=8001 python main.py

# 终端 2：重构后
env DT_API_TOKEN= MONGODB_URI=mongodb://localhost:27018 MONGODB_DB_NAME=daypilot_bench_after PORT=8002 python main.py
```

`DT_API_TOKEN=` 用来关掉 Dynatrace 导出（租户已失效，见第 7 节），免得后台导出失败、不断重试，给测量添噪声。

### 6.3 跑压测

```bash
python scripts/bench_chat_latency.py run \
  --target before=http://127.0.0.1:8001,db=daypilot_bench_before \
  --target after=http://127.0.0.1:8002,db=daypilot_bench_after \
  --mongo mongodb://localhost:27018 --rounds 5 --out bench.csv

python scripts/bench_chat_latency.py report bench.csv      # 随时重新出表
```

脚本做了这些事来保证对比公平：
- 每个 target 先发一条不计入结果的 `hi`，把 health / relationship 缓存预热。
- 每轮开始前清空当天的 `daily_schedules`，两版都从同一个状态出发。
- 两个 target **交替**执行（奇数轮 before 先跑，偶数轮 after 先跑），让 Gemini 自身的延迟波动平均分摊到两边。
- 除了延迟，还记录这一轮**有没有真的完成任务**（`ok` 列）。旧版的问题往往不是慢，而是没真正保存。

每轮 5 步：`chat`（问建议）→ `plan` → `confirm_plan`（用自然语言确认）→ `adjust`（加个会）→ `confirm_adjust`。

### 6.4 怎么读结果

- 看每一步的 **p50**（中位数）。Gemini 的长尾很重，**均值没意义**。
- 轮数少的时候 p90 只有参考价值；想得到更稳的结论，用 `--rounds 10` 以上。
- 预期方向：
  - `chat` 会略慢：多了一次意图解析，约 0.5–1 秒。
  - `confirm_*` 会快很多：重构后只调一次意图模型，旧版要"调工具 + 再生成回复"。
  - `plan` 和 `adjust` 取决于生成器本身；省掉的是旧版在工具返回后再复述一遍日程的那次 LLM 调用。
- 一定要和 `ok` 列一起看：快但没有成功不算数。

---

## 7. Dynatrace

### 7.1 现状（2026-11-15 检查）

`python scripts/check_dynatrace.py .` 的结果：**所有 OTLP 接口都返回 404**，租户根地址被重定向到
`myaccount.dynatrace.com/410`（Gone）。也就是说 `.env` 里的租户 `clw46922` 已经失效（多半是试用到期），
现在什么都发不出去。`check_performance` 里的 Problems 查询也会失败；它的本地滚动统计还能用。

### 7.2 想重新用 Dynatrace 的步骤

1. 申请新租户（有免费试用），在 **Access tokens** 里生成一个 token，勾选这些 scope：
   `openTelemetryTrace.ingest`、`metrics.ingest`、`logs.ingest`；要用 API 把数据读回来，再加 `metrics.read`。
2. 更新 `.env`：
   ```
   DT_ENVIRONMENT=https://<新租户id>.apps.dynatrace.com
   DT_API_TOKEN=<新 token>
   OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE=delta
   ```
   最后一行很重要：**Dynatrace 只接收 delta temporality 的 OTLP metrics**，而 Python SDK 默认发 cumulative，
   直方图（比如 `chat.duration`）会被拒收。这个变量由 SDK 直接读取，不用改代码。
3. 验证：`python scripts/check_dynatrace.py .`。traces、metrics、logs 都应该是 `HTTP 200 (all accepted)`。
   `[cumulative]` 那一行如果出现 `rejected=1`，就说明第 2 步的 delta 是必需的。
4. 做前后对比时，**用不同的服务名**区分两个版本，同样不用改代码：
   ```bash
   OTEL_SERVICE_NAME=daypilot-before python main.py     # 重构前
   OTEL_SERVICE_NAME=daypilot-after  python main.py     # 重构后
   ```
   压测时去掉 `DT_API_TOKEN=`，让数据正常上报。
5. 在 Dynatrace 的 Notebooks 里用 DQL 对比（两个版本都有 `chat.handle_request` 这个 span）：
   ```
   fetch spans, from: now()-2h
   | filter span.name == "chat.handle_request"
   | summarize n = count(), p50 = percentile(duration, 50), p90 = percentile(duration, 90), by: { service.name }
   ```
   只有重构后的版本带 `chat.intent` 属性，可以再按意图拆开看：`by: { service.name, chat.intent }`。
   想知道时间花在哪，看同一条 trace 下的子 span：旧版的 `tool.plan_schedule` 等，新版的 `genai` 调用。

> 注意：两版的 `chat.llm.duration` 量的东西不一样。旧版只量 ADK runner，新版量整个 `run_turn`
> （包含上下文加载和意图解析）。**做对比请用 `chat.handle_request` span 或 `chat.duration`**。

---

## 8. 收尾

```bash
docker rm -f daypilot-bench-mongo          # 删掉本地压测库
rm -rf /tmp/daypilot-before
```
后端和前端在各自的终端里按 Ctrl+C 停掉。
