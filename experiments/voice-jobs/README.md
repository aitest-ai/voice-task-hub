# 共用語音任務庫：BreezyVoice 接口原型

狀態：**公開程式原型；只有無推論測試，未部署產音服務、未安裝模型、未產生真實人聲。**
基準為 PR #33 的 beb9a88f9a80f291e55f0a97fbfcf5a88b118402；此目錄不修改原語音編輯器。

## 想達成的使用方式

1. 此公開儲存庫只接受程式、文件及明確可公開的虛構範例任務。私人台詞與正式音色任務須使用另行核准的私有工作區。每個專案、任務、版本有固定 ID。
2. GitHub 先做格式／能力／授權資料檢查；受信任的管理者核准任務後，才交給預先配置的運算 worker。
3. Worker 解析受控 voice_id，從本地聲音登錄取得經授權參考音及模型。任務不能提供任意路徑、URL、命令或金鑰。
4. 成果產生 WAV、版本清單、SHA-256，先經聽評。遊戲用既有 GitHub 授權下載成果包，核對任務雜湊後匯入。
5. 同樣台詞／設定／音色參考／引擎版本重送會重用完整且雜湊正確的成果，不重複合成。變動產生新版本，絕不覆蓋舊 WAV。

這裡的 pull 是「下載成果」，不是把大量 WAV 放進 Git 歷史。GitHub 只是任務與版本管理，不是免費常駐 GPU。
BreezyVoice 官方也支持 CPU（需對應依賴），但批次效能未驗證；GPU 是可選的加速配置。

## 引擎能力界線

| 引擎 | 原型狀態 | 不能假裝具備的能力 |
|---|---|---|
| BreezyVoice | 接上官方本地 CLI 的參數組裝與安全檢查；尚未真正執行模型 | 無已確認的 emotion、speed、seed CLI；要求 happy 等情緒會明確拒絕 |
| IndexTTS | 可以表達任務並規劃；run 明確拒絕，仍須接既有 voice_studio 的服務 adapter | 尚無官方 zh-TW 切換；不能保證臺灣口音 |

不會把 BreezyVoice 輸出自動送進 IndexTTS 充當另一個人的參考聲音。引擎、音色權利與輸出用途都要獨立同意及驗收。
官方 BreezyVoice HTTP API 目前未執行語速等欄位、參考聲線固定於服務端；不能直接裸露公開服務。本原型選受控 CLI，不使用它假裝有九種情緒。

## 立即可跑（不用 GPU、無費用）

```sh
cd experiments/voice-jobs
python3 -m unittest discover -s tests -v
python3 voice_jobs.py plan examples/ranch-greeting.json --registry examples/fixture-registry.json
python3 voice_jobs.py mock examples/ranch-greeting.json --registry examples/fixture-registry.json --output /tmp/voice-job-test
```

fixture registry 只允許假資料流程測試；mock WAV 是 0.1 秒的 440Hz 音調，**不是語音，也不是臺灣口音**。
結果 manifest 標示 mode=mock、is_speech=false，預設 pull 拒絕。測試時須明確加 --allow-mock。

```sh
python3 voice_jobs.py pull /tmp/voice-job-test/KEY/mock/attempt-001 /tmp/game-test-audio --allow-mock
# 私有 artifact 下載範例：先以自己的帳號登入官方 gh CLI，勿把 token 寫進命令
python3 voice_jobs.py fetch --repo OWNER/PRIVATE-VOICE-REPO --run-id 123 \
  --artifact voice-greeting-v1 --expected-key SHA256_FROM_PLAN --destination ./game-audio/greeting-v1
```

下載會驗證任務 key、每個 WAV 的雜湊與路徑，不接受符號連結、舊結果或被改動的快取。雜湊只證明完整性；產物來源的真實性仍依賴你明確選定的私有 GitHub repository／可信任 run，並非任意 manifest 的簽章驗證。
GitHub API/下載整合目前只有 mock subprocess 測試，**沒有真的下載新 workflow 產物**。

## 真實 worker 的必要條件

- 經使用者批准的既有運算環境，預先安裝及固定 BreezyVoice 程式和所有依賴／模型；不自動下載、不建立帳號或憑證。
- 私有 registry：voice_id → consent_id、authorization_evidence_id、synthesis_authorized、revoked=false、expires_at、allowed_purposes、output_redistribution_allowed、engine、locale、model_revision、engine_revision、reference_sha256、reference_path、reference_text。
- engine_revision 與 model_revision 分別是已核准程式／模型快照清單 JSON 的 SHA-256。清單格式為 {"files":{"relative/path":"sha256"}}；執行前比對完整檔案目錄與各檔雜湊，拒絕缺檔、額外檔或符號連結（忽略 .git、__pycache__、.pyc）。Python 套件環境另由已核准部署鎖定；此工具不核驗系統 Python 的所有相依套件。
- reference_path/reference_text 只在私有 worker 設定中，不可放進公開 Git。沒有對應本人或權利人授權證據就不能因「檔案在網路上」而使用。
- output_redistribution_allowed 不表示程式自動替你核發授權。正式產品還需同意用途、期限與角色使用；權利文件本身不進 public manifest。
- worker config 含 enabled=true、network_mode=offline、python、script、model_path、engine_manifest、model_manifest。這些路徑由管理者提供，不採用任務輸入。參考聲音、程式／模型清單與檔案的實際 SHA-256 會核對。
- 使用內建離線模式變數避免 HF 自動下載，但這不是 OS 網路隔離。真正網路限制由預先核准部署設定負責；本原型不更改防火牆／安全設定。

```sh
python3 voice_jobs.py run private-jobs/greeting.json \
  --registry /private/voice-registry.json --worker-config /private/worker.json \
  --output /private/voice-results
```

每次明確重試都使用新的 attempt，最多三次；沒有背景重試或額度規避。失敗不寫 completed manifest，留下 error_type，不輸出可能含私人台詞的上游 stdout/stderr。
意外中斷留下 worker.lock，必須由管理者先確認沒有工作執行，不能自動搶鎖。

## GitHub 草稿工作流程

`voice-jobs-worker.yml.example` 是停用的模板，**不是已上線隊列**。
只允許受信任 default branch 的手動 workflow_dispatch，要求 private repository 和受保護 Environment。
不能用 pull_request_target 執行投稿者程式，不能把 GitHub-hosted runner 說成已配置 GPU。

要做到真正 push 後自動產音，還需核准：私有任務庫／音訊保存位置、可信任 worker、語音授權、額度上限，以及哪些使用者／分支可提交。
在此之前，push 只能執行無模型的 CI 檢查。未允許的 private 台詞不應先 push 到 public repo 再期待 CI 保護，因為曝光已經發生。

## 完成標準

格式通過 ≠ 產音成功 ≠ 臺灣口音合格 ≠ 情緒自然 ≠ 具商用權利。
每個真實成果仍須聽評文字正確性、臺灣地名／口音、音色一致性、情緒辨識及失真。
Artifact 有保留期限，長期語音庫要另行批准私有持久儲存，不把七天 CI artifact 當永久倉庫。

## 官方依據

- https://github.com/mtkresearch/BreezyVoice
- https://github.com/mtkresearch/BreezyVoice/blob/main/single_inference.py
- https://github.com/mtkresearch/BreezyVoice/blob/main/api.py
- https://github.com/index-tts/index-tts/blob/main/docs/README_zh.md
- https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions
