# Benchmark v1.5 事件清单与采集指令

记录日期：2026-07-29。事件选择遵循 `BENCHMARK_V1_5_PLAN.md`：1 个 pilot、4 个冻结外部测试事件。先完成 pilot；另外 4 个事件的人工标签在代码、阈值和提示词封存后才可查看。

## 事件清单

| 角色 | event_id | 状态 | 主要错误模式 |
|---|---|---|---|
| rejected pilot | 8·8服务消费节 | 114 条中仅 4 条来自目标事件，不使用 | 宽泛关键词导致跨事件污染 |
| pilot | 不要长期向AI倾泻心事 | 待采集 | 建议、反讽、经验陈述和立场混合 |
| frozen test 1 | 中国队夺得2026机器人世界杯冠军 | 已有 43 条，需补采 | 正向事件中的事实陈述、调侃与负面例外 |
| frozen test 2 | 学校强制老师无偿陪餐摊派到人 | 待采集 | 劳动权益、隐性否定与强烈讽刺 |
| frozen test 3 | 国标版美素佳儿铅含量争议回应 | 待采集 | 风险转述、求证、品牌回应与不可评分 |
| frozen test 4 | 博物馆存包押金退还未到账 | 待采集 | 服务投诉、事实进展、质疑与调侃 |

`京通App正式上线` 当前只有 19 条，暂不进入 v1.5；不要为了凑事件数降低每事件质量门槛。

## 第一步：只采集 pilot

在 `C:\Users\29007\Desktop\PythonProject` 打开 PowerShell，先执行：

```powershell
& ".\.venv\Scripts\python.exe" ".\weibo_spider.py" `
  --event-id "不要长期向AI倾泻心事" `
  --target "长期向AI倾诉情绪和心理问题的行为建议" `
  --keyword "不要长期向AI倾泻心事" `
  --keyword "长期向AI倾泻心事" `
  --keyword "向AI倾诉 情绪依赖" `
  --split train `
  --search-type 综合 `
  --search-pages 6 `
  --max-posts 25 `
  --max-comment-pages 8 `
  --max-comments-per-post 30 `
  --target-comments 120 `
  --cookie-file "C:\Users\29007\weibo_cookie.txt" `
  --output-dir ".\weibo_data_v2"
```

达到 120 条后先停止，做 pilot 的事件相关性过滤、分层筛选和标注；在 pilot 门禁通过前，不开始四个冻结测试事件的人工标注。

## 冻结测试采集指令

以下命令先保存在清单中。完成 pilot、记录冻结 commit 后再依次执行。

### 中国队夺得2026机器人世界杯冠军

```powershell
& ".\.venv\Scripts\python.exe" ".\weibo_spider.py" `
  --event-id "中国队夺得2026机器人世界杯冠军" `
  --target "中国队在RoboCup机器人世界杯的夺冠表现" `
  --keyword "中国队 RoboCup 机器人世界杯 冠军" `
  --keyword "2026机器人世界杯 中国队夺冠" `
  --keyword "RoboCup 中国队 冠军" `
  --keyword "机器人世界杯 中国队 表现" `
  --split test `
  --search-type 综合 `
  --search-pages 8 `
  --max-posts 30 `
  --max-comment-pages 8 `
  --max-comments-per-post 30 `
  --target-comments 120 `
  --cookie-file "C:\Users\29007\weibo_cookie.txt" `
  --output-dir ".\weibo_data_v2"
```

### 博物馆存包押金退还未到账

```powershell
& ".\.venv\Scripts\python.exe" ".\weibo_spider.py" `
  --event-id "博物馆存包押金退还未到账" `
  --target "博物馆存包服务的押金收取和退款处理" `
  --keyword "博物馆存包遭遇押金退还未到账" `
  --keyword "博物馆 存包 押金 退款" `
  --keyword "存包柜 押金未到账" `
  --split test `
  --search-type 综合 `
  --search-pages 6 `
  --max-posts 25 `
  --max-comment-pages 8 `
  --max-comments-per-post 30 `
  --target-comments 120 `
  --cookie-file "C:\Users\29007\weibo_cookie.txt" `
  --output-dir ".\weibo_data_v2"
```

### 学校强制老师无偿陪餐摊派到人

```powershell
& ".\.venv\Scripts\python.exe" ".\weibo_spider.py" `
  --event-id "学校强制老师无偿陪餐摊派到人" `
  --target "学校安排教师无偿陪餐并摊派任务的做法" `
  --keyword "学校强制老师无偿陪餐摊派到人" `
  --keyword "教师 无偿陪餐 摊派" `
  --keyword "老师 陪餐 强制" `
  --split test `
  --search-type 综合 `
  --search-pages 6 `
  --max-posts 25 `
  --max-comment-pages 8 `
  --max-comments-per-post 30 `
  --target-comments 120 `
  --cookie-file "C:\Users\29007\weibo_cookie.txt" `
  --output-dir ".\weibo_data_v2"
```

### 国标版美素佳儿铅含量争议回应

```powershell
& ".\.venv\Scripts\python.exe" ".\weibo_spider.py" `
  --event-id "国标版美素佳儿铅含量争议回应" `
  --target "品牌对国标版美素佳儿铅含量争议的回应" `
  --keyword "品牌方称国标版美素佳儿未检出铅" `
  --keyword "美素佳儿 铅 检测" `
  --keyword "奶粉 铅 品牌回应" `
  --split test `
  --search-type 综合 `
  --search-pages 6 `
  --max-posts 25 `
  --max-comment-pages 8 `
  --max-comments-per-post 30 `
  --target-comments 120 `
  --cookie-file "C:\Users\29007\weibo_cookie.txt" `
  --output-dir ".\weibo_data_v2"
```

## 验收条件

每个事件采集结束后先看日志和 manifest：

- `target_reached` 最好为 `true`；
- 去重后至少 80 条候选，目标为 120 条；
- 至少来自 4 个原帖；
- 不包含用户名、用户 ID、头像或 Cookie；
- 不把抓取时间、点赞数等字段当成人工标签；
- 若一个事件两轮扩词后仍少于 80 条，替换事件，不拼接同义句、不复制评论。
