# WhatDoIDo
AI-powered Personal Decision Engine

## Local Setup (Skeleton Stage)

This repository currently has project scaffolding. You can prepare local configuration now and run services as implementation is added.

### 1) Create app env files

From the repo root:

```bash
cp apps/frontend/.env.example apps/frontend/.env.local
cp apps/backend/.env.example apps/backend/.env
```

### 2) Backend dependencies

Backend dependency file exists at apps/backend/requirements.txt and now includes a baseline set for FastAPI, LangGraph, SQLAlchemy, Groq, Supabase, and LangSmith.

Install them with:

```bash
cd apps/backend
pip install -r requirements.txt
```

### 4) Run commands (when implementation files are added)

Backend:

```bash
cd apps/backend
uvicorn app.main:app --reload --port 8000
```

Frontend:

```bash
cd apps/frontend
npm install
npm run dev
```
