# Strategy AI - Project Context

## Owner
- Name: 駱董 (Nick, dpskate)
- GitHub: https://github.com/dpskate/strategy-ai

## Goal
AI 驅動的量化交易策略研發平台，用進化算法自動發現盈利策略

## Tech Stack
Python (FastAPI) + TypeScript (Next.js 16) + SQLite

## Architecture
- Backend: FastAPI on port 8100
- Frontend: Next.js on port 3000
- Data: Binance Futures API
- DB: SQLite (data_cache.db)
- Process Manager: pm2 (strategy-api + strategy-web)

## Location
~/strategy-ai (已從 ~/Desktop/strategy-ai 搬移)

## Completed Optimizations
1. 補測試（pytest）
2. API 安全驗證（Bearer Token）+ Docker 部署
3. WebSocket 實時進度推送 + 錯誤處理改善
4. 前端狀態管理（Zustand 替代 sessionStorage）
5. 項目搬到 ~/strategy-ai，pm2 常駐 + 自動重啟
6. lightningcss 修復

## Pending
- 本地 LLM 支持（Ollama）

## Important Notes
- 不要用 Glob 搜索文件（node_modules 會讓 Glob 卡住）
- 前端用 npm run dev 跑（next start 有問題）
- pm2 管理前後端服務
