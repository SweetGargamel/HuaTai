
PDF Highlighter Frontend Template
=================================

This is a minimal React + Vite frontend template to visualize the output of your
financial-aiextract backend. It expects:

  - final.json at src/data/final.json (already provided as a sample)
  - PDF files placed in public/reports/
    * Please replace the placeholder file with your real PDF:
      public/reports/中国南方航空股份有限公司.pdf

Quick start:
-------------
1) Install dependencies
   cd frontend_template
   npm install

2) Run dev server
   npm run dev

3) Open http://localhost:5173

Notes:
- The PDF in public/reports is a placeholder text file. Replace it with the real PDF
  using the exact filename that matches the company name in final.json, e.g.
  中国南方航空股份有限公司.pdf

- If you prefer the frontend to fetch the JSON from backend HTTP endpoint instead,
  edit src/App.jsx to load data via fetch.

