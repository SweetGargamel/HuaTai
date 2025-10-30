import { useState } from "react";
import PDFViewer from "./components/PDFViewer";
import IndicatorPanel from "./components/IndicatorPanel";
import data from "./data/final.json";

export default function App() {
  const company = Object.keys(data)[0];
  const indicators = data[company] || {};
  const [highlight, setHighlight] = useState([]);

  const handleSelect = (info) => {
    setHighlight([info]);
  };

  return (
    <div className="flex h-screen">
      <IndicatorPanel data={indicators} onSelect={handleSelect} />
      <div className="flex-1">
        <PDFViewer
          pdfUrl={`/reports/${company}.pdf`}
          highlights={highlight}
        />
      </div>
    </div>
  );
}
