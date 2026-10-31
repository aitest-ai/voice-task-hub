# voice-task-hub

跨專案共用語音任務合約與產物校驗工具。**目前是公開的程式原型，不是已上線的產音服務。**

## 現在可以做什麼

- 用 JSON 描述專案、任務、音色代號與預期用途。
- 驗證引擎能力、授權登錄、版本與檔案 SHA-256。
- 測試重試、快取與經校驗的產物下載流程。
- 使用 BreezyVoice 官方 CLI 接口的本地適配層；真正推論尚未驗證。

主程式與操作說明：[experiments/voice-jobs](experiments/voice-jobs/README.md)。

```sh
python3 -m unittest discover -s experiments/voice-jobs/tests -v
python3 experiments/voice-jobs/voice_jobs.py plan experiments/voice-jobs/examples/ranch-greeting.json --registry experiments/voice-jobs/examples/fixture-registry.json
```

測試只有虛構台詞與短測試音調，不是人聲，也不代表臺灣口音或情緒驗收。
BreezyVoice 沒有此工具已驗證的九種情緒／語速控制；不支援的要求會被拒絕。IndexTTS 目前僅可規劃任務，未接上執行 adapter。

## 公開範圍與費用邊界

這個 repo 只放程式、文件及不含個資的範例。**禁止提交私人台詞、參考錄音、產生的人聲、授權文件、金鑰及模型權重。** .gitignore 只是輔助，提交前仍須檢查；事後轉為私有無法收回已被複製或 fork 的公開內容。

啟用的 GitHub Actions 僅在標準 `ubuntu-latest` 上跑無推論單元測試，沒有 GPU、自架 runner、付費外部 API、模型下載或音訊上傳。設定五分鐘逾時與最小唯讀權限；只有單一 Python 版本，避免不必要的 matrix 運算。

真正產音流程僅為 `voice-jobs-worker.yml.example` 停用模板。它不在 `.github/workflows`，不得直接啟用於此公開 repo。未來需要另行核准可信任 worker、授權臺灣音色、私有任務與長期音訊保存位置，以及成本上限。

**Push 任務不等於已自動產音。** 現階段 push 只能跑無推論測試；pull 音檔是經校驗的 artifact 下載，而不是把大量 WAV 放入 Git 歷史。GitHub artifact 有保留期限，不能當永久語音庫。

## 出處與授權

原型從 `aitest-ai/3dcodeverse-lab` PR #33 的語音實驗旁獨立整理。第三方引擎、模型與個別講者聲音的授權分別處理。本次公開未新增開源授權授予，也未提交第三方程式或模型；欲使用正式聲線，必須先確認對應用途與引擎的權利。
