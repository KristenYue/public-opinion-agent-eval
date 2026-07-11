# Public Demo Cases

这些案例使用合成公开评论，用于 README 和本地演示，不依赖私有微博语料。

| Case | 说明 | review_status | risk_flags |
|---|---|---|---|
| `01_conservative_policy_manual_review` | 保守策略：高分歧时进入人工复核 | `manual_required` | `manual_review_required, review_pending, high_model_disagreement` |
| `02_model_disagreement_manual_review` | 模型分歧：触发 manual_required | `manual_required` | `manual_review_required, review_pending, high_model_disagreement` |
| `03_no_evidence_fallback` | 证据缺失：no_retrieval_evidence fallback | `manual_required` | `manual_review_required, review_pending, no_retrieval_evidence, high_model_disagreement` |

生成命令：

```powershell
.\.venv\Scripts\python.exe scripts\build_public_demo_cases.py
```
